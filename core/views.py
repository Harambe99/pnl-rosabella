"""Views: login, dashboard (Monthly + Daily P&L), uploads, Monthly Inputs, COGS, history."""
from datetime import date
from calendar import monthrange
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt

from .models import COGSItem, MonthlyInput, ImportLog
from .aggregator import compute_daily_pnl, compute_monthly_pnl, PNL_ROW_LAYOUT
from .importers import (import_manage_orders, import_settlement,
                        import_shop_analytics, import_ad_spend, import_fbt_billing,
                        import_seller_shipping)


def login_view(request):
    if request.method == 'POST':
        pwd = request.POST.get('password', '')
        if pwd == settings.APP_PASSWORD:
            request.session['app_authed'] = True
            request.session.set_expiry(60 * 60 * 24 * 30)
            return redirect(request.GET.get('next') or 'dashboard')
        messages.error(request, 'Wrong password.')
    return render(request, 'core/login.html')


def logout_view(request):
    request.session.flush()
    return redirect('login')


def dashboard(request):
    year = int(request.GET.get('year', 2026))
    monthly = compute_monthly_pnl(year)
    months = [f'{year}-{m:02d}' for m in range(1, 13)]
    rows = []
    for label, rtype in PNL_ROW_LAYOUT:
        if rtype == 'blank':
            rows.append({'label': '', 'type': 'blank', 'values': [], 'ytd': None})
            continue
        if rtype in ('section', 'sub'):
            rows.append({'label': label, 'type': rtype, 'values': [None]*12, 'ytd': None})
            continue
        vals = []
        ytd = Decimal('0')
        for m in months:
            v = monthly.get(m, {}).get(label)
            vals.append(v)
            if v is not None: ytd += v
        rows.append({'label': label, 'type': rtype, 'values': vals, 'ytd': ytd})
    return render(request, 'core/dashboard.html', {
        'rows': rows, 'months': months, 'year': year,
    })


def daily_view(request):
    yyyy_mm = request.GET.get('month') or date.today().strftime('%Y-%m')
    try:
        y, m = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
    except Exception:
        return redirect('daily')
    daily = compute_daily_pnl(start, end)
    dates = sorted(daily.keys())
    rows = []
    for label, rtype in PNL_ROW_LAYOUT:
        if rtype == 'blank':
            rows.append({'label': '', 'type': 'blank', 'values': [None]*len(dates)})
            continue
        if rtype in ('section', 'sub'):
            rows.append({'label': label, 'type': rtype, 'values': [None]*len(dates)})
            continue
        vals = [daily.get(d, {}).get(label) for d in dates]
        rows.append({'label': label, 'type': rtype, 'values': vals})
    return render(request, 'core/daily.html', {
        'rows': rows, 'dates': dates, 'yyyy_mm': yyyy_mm,
    })


def upload(request):
    if request.method == 'POST':
        kind = request.POST.get('kind')
        f = request.FILES.get('file')
        if not f or not kind:
            messages.error(request, 'Missing file or import type.')
            return redirect('upload')
        try:
            if kind == 'manage_orders':
                result = import_manage_orders(f, f.name)
            elif kind == 'settlement':
                result = import_settlement(f, f.name)
            elif kind == 'shop_analytics':
                result = import_shop_analytics(f, f.name)
            elif kind == 'ad_spend':
                result = import_ad_spend(f, f.name)
            elif kind == 'fbt_billing':
                period = request.POST.get('period', '').strip()
                result = import_fbt_billing(f, period, f.name)
            elif kind == 'seller_shipping':
                result = import_seller_shipping(f, f.name)
            else:
                messages.error(request, 'Unknown import type.')
                return redirect('upload')
            messages.success(request, f'Import done: {result}')
        except Exception as e:
            messages.error(request, f'Import error: {e}')
        return redirect('upload')
    recent = ImportLog.objects.all()[:20]
    return render(request, 'core/upload.html', {'recent': recent})


def cogs(request):
    if request.method == 'POST':
        for k, v in request.POST.items():
            if k.startswith('cogs_'):
                try:
                    pk = int(k.split('_')[1])
                    item = COGSItem.objects.get(pk=pk)
                    item.cogs_per_order = Decimal(v or '0')
                    item.save(update_fields=['cogs_per_order'])
                except Exception:
                    pass
        messages.success(request, 'COGS updated.')
        return redirect('cogs')
    items = COGSItem.objects.all()
    return render(request, 'core/cogs.html', {'items': items})


def monthly_inputs(request):
    if request.method == 'POST':
        month = request.POST.get('month')
        if month:
            mi, _ = MonthlyInput.objects.get_or_create(month=month)
            for field in MonthlyInput._meta.get_fields():
                if field.name in ('id', 'month', 'updated_at'): continue
                if not hasattr(field, 'attname'): continue
                v = request.POST.get(field.name)
                if v is not None:
                    try: setattr(mi, field.name, Decimal(v or '0'))
                    except: pass
            mi.save()
            messages.success(request, f'Monthly inputs for {month} saved.')
        return redirect('monthly_inputs')
    months = MonthlyInput.objects.all()
    return render(request, 'core/monthly_inputs.html', {'months': months})


def history(request):
    logs = ImportLog.objects.all()[:200]
    return render(request, 'core/history.html', {'logs': logs})


def health(request):
    return HttpResponse('OK')


@csrf_exempt
def wipe(request):
    """Wipe imported data (keeps COGS + Monthly Inputs). POST only — protected by app password middleware."""
    if request.method != 'POST':
        return HttpResponse('Use POST. Optionally ?what=orders|settlement|analytics|ad_spend|all', status=405)
    what = request.GET.get('what', 'all')
    counts = {}
    if what in ('all', 'orders'):
        counts['orders'] = __import__('core.models', fromlist=['Order']).Order.objects.all().delete()[0]
    if what in ('all', 'settlement'):
        counts['settlement'] = __import__('core.models', fromlist=['SettlementRow']).SettlementRow.objects.all().delete()[0]
    if what in ('all', 'analytics'):
        counts['analytics'] = __import__('core.models', fromlist=['AnalyticsDay']).AnalyticsDay.objects.all().delete()[0]
    if what in ('all', 'ad_spend'):
        counts['ad_spend'] = __import__('core.models', fromlist=['AdSpendDay']).AdSpendDay.objects.all().delete()[0]
    if what in ('all', 'seller_shipping'):
        counts['seller_shipping'] = __import__('core.models', fromlist=['SellerShipmentCost']).SellerShipmentCost.objects.all().delete()[0]
    return HttpResponse('Wiped: ' + str(counts))
