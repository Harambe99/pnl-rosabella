"""Views: login, dashboard (Monthly + Daily P&L), uploads, Monthly Inputs, COGS, history."""
from datetime import date
from calendar import monthrange
from decimal import Decimal
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt

from .models import (COGSItem, MonthlyInput, ImportLog, MonthlyInputAudit,
                     AdLedgerDay, AdLedgerConfig, AgencyPromoTag, AgencyInvoice,
                     AdTransaction)
from .aggregator import compute_daily_pnl, compute_monthly_pnl, PNL_ROW_LAYOUT
from .importers import (import_manage_orders, import_settlement,
                        import_shop_analytics, import_ad_spend, import_fbt_billing,
                        import_seller_shipping, import_ad_transactions)


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
            elif kind == 'ad_transactions':
                result = import_ad_transactions(f, f.name)
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
    """GET: show the export page. With ?mode= & ?month= query: stream XLSX.
    Monthly export has 2 sheets — the P&L + a 'Line Item Guide' with explanations.
    Line item labels in the P&L sheet are hyperlinks that jump to the guide row."""
    import io
    mode = request.GET.get('mode')
    yyyy_mm = request.GET.get('month', '')

    if not mode:
        return render(request, 'core/export.html', {
            'current_month': date.today().strftime('%Y-%m'),
        })

    try:
        y, m = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
        if y < 2020 or y > 2099 or m < 1 or m > 12:
            return HttpResponse('Invalid month', status=400)
    except Exception:
        return HttpResponse('Invalid month', status=400)
    if mode not in ('monthly', 'daily'):
        return HttpResponse('mode must be monthly or daily', status=400)

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from .line_item_docs import LINE_ITEM_DOCS

    wb = openpyxl.Workbook()
    ws = wb.active

    # Style presets
    F_HEAD = Font(bold=True, color='FFFFFF', size=11)
    F_SECTION = Font(bold=True, color='FFFFFF', size=11)
    F_SUB = Font(bold=True, size=10)
    F_TOTAL = Font(bold=True, size=11)
    F_LINK = Font(color='0563C1', underline='single', size=10)
    FILL_HEAD = PatternFill('solid', fgColor='2D3748')
    FILL_SECTION = PatternFill('solid', fgColor='4A5568')
    FILL_SUB = PatternFill('solid', fgColor='E2E8F0')
    FILL_TOTAL = PatternFill('solid', fgColor='EDF2F7')
    THIN = Side(style='thin', color='CBD5E0')
    BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

    # ---- Build Sheet 2 first ('Line Item Guide') so we know each row number ----
    ws_doc = wb.create_sheet('Line Item Guide')
    ws_doc['A1'] = 'Line Item'
    ws_doc['B1'] = 'What it is'
    ws_doc['C1'] = 'Source'
    ws_doc['D1'] = 'Formula'
    ws_doc['E1'] = 'Notes'
    for col, w_ in zip('ABCDE', [38, 60, 50, 60, 70]):
        ws_doc.column_dimensions[col].width = w_
    for c in ws_doc[1]:
        c.font = F_HEAD; c.fill = FILL_HEAD; c.alignment = Alignment(vertical='top')
    doc_row_for_label = {}
    doc_r = 2
    for label, doc in LINE_ITEM_DOCS.items():
        ws_doc.cell(doc_r, 1, label).font = F_TOTAL
        ws_doc.cell(doc_r, 2, doc.get('what', '')).alignment = Alignment(wrap_text=True, vertical='top')
        ws_doc.cell(doc_r, 3, doc.get('source', '')).alignment = Alignment(wrap_text=True, vertical='top')
        ws_doc.cell(doc_r, 4, doc.get('formula', '')).alignment = Alignment(wrap_text=True, vertical='top')
        ws_doc.cell(doc_r, 5, doc.get('notes', '')).alignment = Alignment(wrap_text=True, vertical='top')
        ws_doc.row_dimensions[doc_r].height = 48
        for c in ws_doc[doc_r]: c.border = BORDER
        doc_row_for_label[label.strip()] = doc_r
        doc_r += 1

    def link_label_cell(cell, label):
        """If the label has a doc entry, make it a hyperlink to that doc row."""
        target_row = doc_row_for_label.get(label.strip())
        if target_row:
            cell.hyperlink = f"#'Line Item Guide'!A{target_row}"
            cell.font = F_LINK

    # ---- Sheet 1 — the P&L ----
    if mode == 'monthly':
        ws.title = f'Monthly P&L {yyyy_mm}'
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        daily = compute_daily_pnl(start, end)
        monthly = {}
        for d, row in daily.items():
            for label, val in row.items():
                monthly[label] = monthly.get(label, Decimal('0')) + (val or Decimal('0'))
        nr = monthly.get('NET REVENUE') or Decimal('0')

        # Header
        ws.append(['Line Item', f'{yyyy_mm} ($)', f'{yyyy_mm} (% Net Rev)'])
        for c in ws[1]:
            c.font = F_HEAD; c.fill = FILL_HEAD; c.alignment = Alignment(horizontal='center')
        ws.column_dimensions['A'].width = 42
        ws.column_dimensions['B'].width = 18
        ws.column_dimensions['C'].width = 16

        excel_row = 2
        for label, rtype in PNL_ROW_LAYOUT:
            if rtype == 'blank':
                ws.row_dimensions[excel_row].height = 8
                excel_row += 1; continue
            if rtype in ('section', 'sub'):
                cell = ws.cell(excel_row, 1, label)
                if rtype == 'section':
                    cell.font = F_SECTION; cell.fill = FILL_SECTION
                else:
                    cell.font = F_SUB; cell.fill = FILL_SUB
                excel_row += 1; continue
            v = monthly.get(label)
            label_cell = ws.cell(excel_row, 1, label)
            link_label_cell(label_cell, label)
            if rtype == 'total':
                label_cell.font = F_TOTAL
                for c in [ws.cell(excel_row, 2), ws.cell(excel_row, 3)]:
                    c.font = F_TOTAL; c.fill = FILL_TOTAL
            if v is not None:
                val_cell = ws.cell(excel_row, 2, float(v))
                val_cell.number_format = '$#,##0.00;($#,##0.00)'
                if nr and float(nr) != 0:
                    pct_cell = ws.cell(excel_row, 3, float(v) / float(nr))
                    pct_cell.number_format = '0.0%;(0.0%)'
            excel_row += 1
        ws.freeze_panes = 'B2'
        filename = f'pnl_monthly_{yyyy_mm}.xlsx'

    else:  # daily
        ws.title = f'Daily P&L {yyyy_mm}'
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        daily = compute_daily_pnl(start, end)
        dates = sorted(daily.keys())
        nr_per_date = [daily.get(d, {}).get('NET REVENUE') for d in dates]
        month_nr = sum((v or Decimal('0')) for v in nr_per_date)

        # Two-row header: dates + $/% sub-header
        hdr1 = ['Line Item']
        for d in dates:
            hdr1.extend([d.strftime('%d %b'), ''])
        hdr1.extend([f'Total {yyyy_mm}', ''])
        ws.append(hdr1)
        hdr2 = ['']
        for _ in dates: hdr2.extend(['$', '% NR'])
        hdr2.extend(['$', '% NR'])
        ws.append(hdr2)
        for c in ws[1]:
            c.font = F_HEAD; c.fill = FILL_HEAD; c.alignment = Alignment(horizontal='center')
        for c in ws[2]:
            c.font = F_HEAD; c.fill = FILL_HEAD; c.alignment = Alignment(horizontal='center')
        ws.column_dimensions['A'].width = 42
        for i in range(2, len(hdr1) + 1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 11

        excel_row = 3
        for label, rtype in PNL_ROW_LAYOUT:
            if rtype == 'blank':
                ws.row_dimensions[excel_row].height = 8
                excel_row += 1; continue
            if rtype in ('section', 'sub'):
                cell = ws.cell(excel_row, 1, label)
                if rtype == 'section':
                    cell.font = F_SECTION; cell.fill = FILL_SECTION
                else:
                    cell.font = F_SUB; cell.fill = FILL_SUB
                excel_row += 1; continue
            label_cell = ws.cell(excel_row, 1, label)
            link_label_cell(label_cell, label)
            if rtype == 'total':
                label_cell.font = F_TOTAL
            col = 2
            month_total = Decimal('0')
            for d, nr in zip(dates, nr_per_date):
                v = daily.get(d, {}).get(label)
                if v is not None:
                    c1 = ws.cell(excel_row, col, float(v))
                    c1.number_format = '$#,##0;($#,##0)'
                    if nr and float(nr) != 0:
                        c2 = ws.cell(excel_row, col + 1, float(v) / float(nr))
                        c2.number_format = '0.0%;(0.0%)'
                    month_total += v
                col += 2
            c1 = ws.cell(excel_row, col, float(month_total))
            c1.number_format = '$#,##0;($#,##0)'
            if rtype == 'total':
                c1.font = F_TOTAL; c1.fill = FILL_TOTAL
            if month_nr and float(month_nr) != 0:
                c2 = ws.cell(excel_row, col + 1, float(month_total) / float(month_nr))
                c2.number_format = '0.0%;(0.0%)'
                if rtype == 'total':
                    c2.font = F_TOTAL; c2.fill = FILL_TOTAL
            excel_row += 1
        ws.freeze_panes = 'B3'
        filename = f'pnl_daily_{yyyy_mm}.xlsx'

    # Stream out
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    resp = HttpResponse(
        buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    resp['Content-Disposition'] = f'attachment; filename="{filename}"'
    return resp


def ad_discounts(request):
    """Daily TikTok ad-account ledger: spend, balance, funding source, effective discount.
    Manages opening balance, agency-promo tags, and agency invoices."""
    from datetime import datetime as _dt
    from .ad_ledger import recompute_ledger

    def _parse_date(s):
        if not s: return None
        try: return _dt.strptime(s, '%Y-%m-%d').date()
        except Exception: return None

    try:
        year = int(request.GET.get('year', 2026))
        if year < 2020 or year > 2099: year = 2026
    except (TypeError, ValueError):
        year = 2026

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save_config':
            cfg, _c = AdLedgerConfig.objects.get_or_create(pk=1)
            cfg.opening_balance = Decimal(request.POST.get('opening_balance', '0') or '0')
            cfg.opening_date = _parse_date(request.POST.get('opening_date'))
            cfg.opening_discount = Decimal(request.POST.get('opening_discount', '0.06') or '0.06')
            cfg.tbsm_default_discount = Decimal(request.POST.get('tbsm_default_discount', '0.06') or '0.06')
            cfg.feed_pnl = (request.POST.get('feed_pnl') == 'on')
            cfg.save()
            recompute_ledger(date(year, 1, 1), date(year, 12, 31))
            messages.success(request, 'Config saved + ledger recomputed.')
        elif action == 'add_tag':
            d = _parse_date(request.POST.get('tag_date'))
            if d:
                AgencyPromoTag.objects.update_or_create(
                    date=d,
                    defaults={
                        'min_amount': Decimal(request.POST.get('tag_min', '10000') or '10000'),
                        'discount_pct': Decimal(request.POST.get('tag_disc', '0.10') or '0.10'),
                        'note': request.POST.get('tag_note', ''),
                    },
                )
                recompute_ledger(date(year, 1, 1), date(year, 12, 31))
                messages.success(request, f'Agency promo tag saved for {d}.')
        elif action == 'delete_tag':
            try:
                AgencyPromoTag.objects.filter(pk=int(request.POST.get('tag_id'))).delete()
                recompute_ledger(date(year, 1, 1), date(year, 12, 31))
                messages.success(request, 'Tag deleted.')
            except (TypeError, ValueError):
                pass
        elif action == 'add_invoice':
            AgencyInvoice.objects.create(
                invoice_no=request.POST.get('inv_no', ''),
                issue_date=_parse_date(request.POST.get('inv_date')),
                loaded_value=Decimal(request.POST.get('inv_loaded', '0') or '0'),
                discount_pct=Decimal(request.POST.get('inv_disc', '0.06') or '0.06'),
                amount_paid=Decimal(request.POST.get('inv_paid', '0') or '0'),
                entity=request.POST.get('inv_entity', ''),
                notes=request.POST.get('inv_notes', ''),
            )
            messages.success(request, 'Invoice added.')
        elif action == 'delete_invoice':
            try:
                AgencyInvoice.objects.filter(pk=int(request.POST.get('inv_id'))).delete()
                messages.success(request, 'Invoice deleted.')
            except (TypeError, ValueError):
                pass
        elif action == 'recompute':
            recompute_ledger(date(year, 1, 1), date(year, 12, 31))
            messages.success(request, f'Ledger recomputed for {year}.')
        return redirect(f"{request.path}?year={year}")

    cfg, _c = AdLedgerConfig.objects.get_or_create(pk=1)
    days = list(AdLedgerDay.objects.filter(date__year=year).order_by('date'))
    tags = AgencyPromoTag.objects.all()
    invoices = AgencyInvoice.objects.all()
    txn_count = AdTransaction.objects.count()

    # Monthly rollup
    monthly = {}
    for d in days:
        m = d.date.strftime('%Y-%m')
        if m not in monthly:
            monthly[m] = {'spend': Decimal('0'), 'funded': Decimal('0'),
                          'full_price': Decimal('0'), 'card': Decimal('0'),
                          'actual_cost': Decimal('0'),
                          'savings_tbsm': Decimal('0'), 'savings_promo': Decimal('0'),
                          'end_balance': Decimal('0')}
        m_row = monthly[m]
        m_row['spend'] += d.ad_spend
        m_row['funded'] += d.funded
        m_row['full_price'] += d.full_price
        m_row['card'] += d.card_charge
        m_row['actual_cost'] += d.actual_cost
        m_row['savings_tbsm'] += d.savings_tbsm
        m_row['savings_promo'] += d.savings_promo
        m_row['end_balance'] = d.closing_balance
    for m_key, row in monthly.items():
        row['eff_disc'] = (
            (Decimal('1') - row['actual_cost'] / row['spend']) * 100
            if row['spend'] else Decimal('0'))
    monthly_sorted = sorted(monthly.items())

    return render(request, 'core/ad_discounts.html', {
        'year': year, 'prev_year': year - 1, 'next_year': year + 1,
        'days': days, 'monthly': monthly_sorted,
        'config': cfg, 'tags': tags, 'invoices': invoices,
        'txn_count': txn_count,
    })


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
