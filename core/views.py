"""Views: login, dashboard (Monthly + Daily P&L), uploads, Monthly Inputs, COGS, history."""
from datetime import date
from calendar import monthrange
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt

from .models import COGSItem, MonthlyInput, ImportLog, MonthlyInputAudit
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


def _pct(v, nr):
    """Return value/net_revenue as a percentage, or None if not meaningful."""
    if v is None or nr is None: return None
    try:
        nr_f = float(nr)
        if nr_f == 0: return None
        return float(v) / nr_f * 100
    except (TypeError, ValueError):
        return None


def dashboard(request):
    try:
        year = int(request.GET.get('year', 2026))
        # Sanity-clamp to a sensible range so date() construction doesn't blow up
        if year < 2020 or year > 2099:
            return redirect('dashboard')
    except (TypeError, ValueError):
        return redirect('dashboard')
    monthly = compute_monthly_pnl(year)
    months = [f'{year}-{m:02d}' for m in range(1, 13)]
    rows = []
    # Pre-compute Net Revenue per month (for % column) and YTD Net Revenue
    nr_per_month = [monthly.get(m, {}).get('NET REVENUE') for m in months]
    ytd_nr = sum((nr or Decimal('0')) for nr in nr_per_month)
    for label, rtype in PNL_ROW_LAYOUT:
        if rtype == 'blank':
            rows.append({'label': '', 'type': 'blank', 'cells': [(None, None)]*12,
                         'ytd': None, 'ytd_pct': None})
            continue
        if rtype in ('section', 'sub'):
            rows.append({'label': label, 'type': rtype, 'cells': [(None, None)]*12,
                         'ytd': None, 'ytd_pct': None})
            continue
        cells = []
        ytd = Decimal('0')
        for m, nr in zip(months, nr_per_month):
            v = monthly.get(m, {}).get(label)
            cells.append((v, _pct(v, nr)))
            if v is not None: ytd += v
        ytd_pct = _pct(ytd, ytd_nr) if ytd_nr else None
        rows.append({'label': label, 'type': rtype, 'cells': cells,
                     'ytd': ytd, 'ytd_pct': ytd_pct})
    return render(request, 'core/dashboard.html', {
        'rows': rows, 'months': months, 'year': year,
    })


def daily_view(request):
    """Render the FULL year of daily P&L in one scrollable table.
    The month picker is a 'scroll-to' anchor, not a filter."""
    yyyy_mm = request.GET.get('month') or date.today().strftime('%Y-%m')
    try:
        y, m = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
        if y < 2020 or y > 2099 or m < 1 or m > 12:
            return redirect('daily')
    except Exception:
        return redirect('daily')
    start = date(y, 1, 1)
    end = date(y, 12, 31)
    daily = compute_daily_pnl(start, end)
    dates = sorted(daily.keys())
    nr_per_date = [daily.get(d, {}).get('NET REVENUE') for d in dates]
    rows = []
    for label, rtype in PNL_ROW_LAYOUT:
        if rtype == 'blank':
            rows.append({'label': '', 'type': 'blank', 'cells': [(None, None)]*len(dates)})
            continue
        if rtype in ('section', 'sub'):
            rows.append({'label': label, 'type': rtype, 'cells': [(None, None)]*len(dates)})
            continue
        cells = []
        for d, nr in zip(dates, nr_per_date):
            v = daily.get(d, {}).get(label)
            cells.append((v, _pct(v, nr)))
        rows.append({'label': label, 'type': rtype, 'cells': cells})
    return render(request, 'core/daily.html', {
        'rows': rows, 'dates': dates, 'yyyy_mm': yyyy_mm, 'year': y,
        'prev_year': y - 1, 'next_year': y + 1,
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
            changes = []
            for field in MonthlyInput._meta.get_fields():
                if field.name in ('id', 'month', 'updated_at'): continue
                if not hasattr(field, 'attname'): continue
                raw = request.POST.get(field.name)
                if raw is None or str(raw).strip() == '':
                    continue  # empty input = leave existing value alone
                try: new_val = Decimal(raw)
                except: continue
                old_val = getattr(mi, field.name) or Decimal('0')
                if new_val != old_val:
                    changes.append((field.name, old_val, new_val))
                    setattr(mi, field.name, new_val)
            mi.save()
            for fname, old, new in changes:
                MonthlyInputAudit.objects.create(month=month, field_name=fname,
                                                 old_value=old, new_value=new)
            if changes:
                messages.success(request, f'{month}: {len(changes)} field(s) updated.')
            else:
                messages.info(request, f'{month}: no changes (all fields empty or unchanged).')
        return redirect('monthly_inputs')
    months = MonthlyInput.objects.all()
    # Build JSON map {month: {field: value}} for the JS overwrite-warning
    import json as _json
    existing_data = {}
    for m in months:
        existing_data[m.month] = {}
        for field in MonthlyInput._meta.get_fields():
            if field.name in ('id', 'month', 'updated_at'): continue
            if not hasattr(field, 'attname'): continue
            existing_data[m.month][field.name] = str(getattr(m, field.name) or 0)
    audits = MonthlyInputAudit.objects.all()[:100]
    return render(request, 'core/monthly_inputs.html', {
        'months': months,
        'existing_json': _json.dumps(existing_data),
        'audits': audits,
    })


def history(request):
    logs = ImportLog.objects.all()[:200]
    return render(request, 'core/history.html', {'logs': logs})


def readme(request):
    return render(request, 'core/readme.html')


def export_pnl(request):
    """GET: show the export page. With ?mode= & ?month= query: stream CSV."""
    import csv, io
    mode = request.GET.get('mode')
    yyyy_mm = request.GET.get('month', '')

    if not mode:
        # Render the form page
        return render(request, 'core/export.html', {
            'current_month': date.today().strftime('%Y-%m'),
        })

    # Validate inputs
    try:
        y, m = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
        if y < 2020 or y > 2099 or m < 1 or m > 12:
            return HttpResponse('Invalid month', status=400)
    except Exception:
        return HttpResponse('Invalid month', status=400)

    if mode not in ('monthly', 'daily'):
        return HttpResponse('mode must be monthly or daily', status=400)

    buf = io.StringIO()
    w = csv.writer(buf)

    if mode == 'monthly':
        # One column: the chosen month's totals
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        daily = compute_daily_pnl(start, end)
        monthly = {}
        for d, row in daily.items():
            for label, val in row.items():
                monthly[label] = monthly.get(label, Decimal('0')) + (val or Decimal('0'))
        nr = monthly.get('NET REVENUE') or Decimal('0')

        w.writerow(['Line Item', f'{yyyy_mm} ($)', f'{yyyy_mm} (% Net Rev)'])
        for label, rtype in PNL_ROW_LAYOUT:
            if rtype == 'blank':
                w.writerow(['', '', ''])
                continue
            if rtype in ('section', 'sub'):
                w.writerow([label, '', ''])
                continue
            v = monthly.get(label)
            dollar = f'{float(v):.2f}' if v is not None else ''
            pct = ''
            if v is not None and nr and float(nr) != 0:
                pct = f'{float(v) / float(nr) * 100:.1f}%'
            w.writerow([label, dollar, pct])

        filename = f'pnl_monthly_{yyyy_mm}.csv'

    else:  # daily
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        daily = compute_daily_pnl(start, end)
        dates = sorted(daily.keys())
        nr_per_date = [daily.get(d, {}).get('NET REVENUE') for d in dates]
        month_nr = sum((v or Decimal('0')) for v in nr_per_date)

        # Two-row header: dates + sub-header
        header1 = ['Line Item']
        for d in dates:
            header1.extend([d.strftime('%d %b'), ''])
        header1.extend([f'Total {yyyy_mm}', ''])
        w.writerow(header1)
        header2 = ['']
        for _ in dates:
            header2.extend(['$', '% NR'])
        header2.extend(['$', '% NR'])
        w.writerow(header2)

        for label, rtype in PNL_ROW_LAYOUT:
            if rtype == 'blank':
                w.writerow([''] + ['', ''] * (len(dates) + 1))
                continue
            if rtype in ('section', 'sub'):
                w.writerow([label] + ['', ''] * (len(dates) + 1))
                continue
            row_cells = [label]
            month_total = Decimal('0')
            for d, nr in zip(dates, nr_per_date):
                v = daily.get(d, {}).get(label)
                dollar = f'{float(v):.2f}' if v is not None else ''
                pct = ''
                if v is not None and nr and float(nr) != 0:
                    pct = f'{float(v) / float(nr) * 100:.1f}%'
                row_cells.extend([dollar, pct])
                if v is not None: month_total += v
            # Month total column
            mt_dollar = f'{float(month_total):.2f}'
            mt_pct = f'{float(month_total) / float(month_nr) * 100:.1f}%' if month_nr else ''
            row_cells.extend([mt_dollar, mt_pct])
            w.writerow(row_cells)

        filename = f'pnl_daily_{yyyy_mm}.csv'

    resp = HttpResponse(buf.getvalue(), content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


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
    if what in ('all', 'monthly_inputs'):
        counts['monthly_inputs'] = __import__('core.models', fromlist=['MonthlyInput']).MonthlyInput.objects.all().delete()[0]
        counts['monthly_audit'] = __import__('core.models', fromlist=['MonthlyInputAudit']).MonthlyInputAudit.objects.all().delete()[0]
    if what in ('all', 'logs'):
        counts['logs'] = __import__('core.models', fromlist=['ImportLog']).ImportLog.objects.all().delete()[0]
    return HttpResponse('Wiped: ' + str(counts))
