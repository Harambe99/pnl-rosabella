"""
File parsers for the 5 TikTok exports.
All dates handled as Python date objects internally — no Sheet locale ambiguity.
"""
import csv
import io
from datetime import date, datetime
from decimal import Decimal
from django.db import transaction
import openpyxl

from .models import Order, SettlementRow, AnalyticsDay, AdSpendDay, MonthlyInput, COGSItem, ImportLog


def _to_dec(v):
    if v is None or v == '': return Decimal('0')
    if isinstance(v, (int, float, Decimal)): return Decimal(str(v))
    s = str(v).replace(',', '').replace('$', '').replace('\t', '').strip()
    s = s.replace('(', '-').replace(')', '')
    try: return Decimal(s)
    except: return Decimal('0')


def _to_int(v):
    if v is None or v == '': return 0
    try: return int(float(str(v).replace('\t', '').strip()))
    except: return 0


def _to_date(v, prefer_dd_mm=False):
    """Parse a date. Handles ambiguous MM/DD vs DD/MM by checking validity.
    `prefer_dd_mm=True` for files known to use DD/MM/YYYY (Shop Analytics, Ad Spend)."""
    if not v: return None
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    s = str(v).strip().replace('\t', '').split(' ')[0]
    # Unambiguous YYYY-first
    for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
        try: return datetime.strptime(s, fmt).date()
        except: pass
    # Ambiguous slash-separated — disambiguate via numeric checks
    parts = s.split('/')
    if len(parts) == 3:
        try:
            p1, p2, p3 = int(parts[0]), int(parts[1]), int(parts[2])
            # Year must be 4 digits and = p3
            if p3 < 100: p3 += 2000
            if p1 > 12 and p2 <= 12:    # MUST be DD/MM/YYYY
                return date(p3, p2, p1)
            if p2 > 12 and p1 <= 12:    # MUST be MM/DD/YYYY
                return date(p3, p1, p2)
            if p1 <= 12 and p2 <= 12:   # AMBIGUOUS — use hint
                if prefer_dd_mm:
                    return date(p3, p2, p1)
                else:
                    return date(p3, p1, p2)
        except (ValueError, TypeError):
            pass
    return None


def _clean_str(v):
    if v is None: return ''
    return str(v).strip().replace('\t', '')


def _cogs_lookup():
    return {c.sku_id: c.cogs_per_order for c in COGSItem.objects.all()}


# ===========================================================================
# 1. Manage Orders CSV importer
# ===========================================================================
def import_manage_orders(file_obj, filename=''):
    text = file_obj.read()
    if isinstance(text, bytes):
        text = text.decode('utf-8-sig', errors='replace')
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if not header:
        return {'added': 0, 'skipped': 0, 'errors': ['Empty file']}

    hdr = [h.strip().lower() for h in header]
    def col(name):
        try: return hdr.index(name.lower())
        except ValueError: return -1

    c_oid = col('Order ID')
    c_status = col('Order Status')
    c_sku = col('SKU ID')
    c_qty = col('Quantity')
    c_gross = col('SKU Subtotal Before Discount')
    c_disc = col('SKU Seller Discount')
    c_refund = col('Order Refund Amount')
    c_created = col('Created Time')

    if c_oid < 0 or c_sku < 0 or c_created < 0:
        return {'added': 0, 'skipped': 0, 'errors': ['Missing required columns (Order ID / SKU ID / Created Time)']}

    cogs_map = _cogs_lookup()
    existing = set(Order.objects.values_list('order_id', 'sku_id'))

    to_create = []
    skipped = 0
    unmapped = set()

    for row in reader:
        if len(row) < max(c_oid, c_sku, c_created) + 1: continue
        oid = _clean_str(row[c_oid])
        sku = _clean_str(row[c_sku])
        if not oid or not sku: continue
        if (oid, sku) in existing:
            skipped += 1; continue
        existing.add((oid, sku))

        created = _to_date(row[c_created] if c_created < len(row) else None)
        if not created: continue
        qty = _to_int(row[c_qty] if c_qty < len(row) else 0)
        status = _clean_str(row[c_status] if c_status >= 0 and c_status < len(row) else '')
        gross = _to_dec(row[c_gross] if c_gross >= 0 and c_gross < len(row) else 0)
        disc = -abs(_to_dec(row[c_disc] if c_disc >= 0 and c_disc < len(row) else 0))
        refund = -abs(_to_dec(row[c_refund] if c_refund >= 0 and c_refund < len(row) else 0))
        cogs_per = cogs_map.get(sku)
        if cogs_per is None:
            unmapped.add(sku); cogs_val = Decimal('0')
        else:
            cogs_val = Decimal(cogs_per) * qty

        to_create.append(Order(
            order_id=oid, sku_id=sku, created_date=created, quantity=qty,
            status=status, gross_sale=gross, seller_discount=disc,
            order_refund=refund, cogs=cogs_val, source_file=filename,
        ))

    with transaction.atomic():
        Order.objects.bulk_create(to_create, batch_size=500)
        ImportLog.objects.create(importer='manage_orders', filename=filename,
                                 rows_added=len(to_create), rows_skipped=skipped,
                                 notes='Unmapped SKUs: ' + ','.join(sorted(unmapped)) if unmapped else '')

    return {'added': len(to_create), 'skipped': skipped, 'unmapped_skus': sorted(unmapped)}


# ===========================================================================
# 2. Settlement xlsx importer
# ===========================================================================
TYPE_TO_FIELD = {
    'Logistics reimbursement': 'logistics_reimb',
    'FBT warehouse service fee using GMV payment': 'fbt_warehouse',
    'Chargeback': 'chargeback',
    'Violation fee （settlement fee）': 'violation',
    'Violation fee (settlement fee)': 'violation',
    'TikTok Shop reimbursement': 'tt_shop_reimb',
    'FBT warehouse compensation': 'fbt_warehouse_comp',
    'Rebate': 'rebate',
}

def import_settlement(file_obj, filename=''):
    wb = openpyxl.load_workbook(file_obj, data_only=True, read_only=False)
    ws_name = next((n for n in wb.sheetnames if n.lower().startswith('order')), wb.sheetnames[0])
    ws = wb[ws_name]

    header = [_clean_str(c) for c in next(ws.iter_rows(min_row=1, max_row=1, values_only=True))]
    h_lower = [h.lower() for h in header]
    def col(name):
        try: return h_lower.index(name.lower())
        except ValueError: return -1

    c_stmt = col('Statement date')
    c_stid = col('Statement ID')
    c_type = col('Type')
    c_oid = col('Order/adjustment ID')
    c_qty = col('Quantity')
    c_created = col('Order created date')
    c_gross_ref = col('Gross sales refund')
    c_disc_ref = col('Seller discount refund')
    c_shipping = col('Shipping')
    c_tt_inc = col('TikTok Shop shipping incentive')
    c_subsidy = col('Shipping fee subsidy')
    c_offset = col('Customer shipping fee offset')
    c_fbt_fee = col('FBT fulfillment fee')
    c_fbt_reimb = col('FBT fulfillment fee reimbursement')
    c_ref = col('Referral fee')
    c_refadmin = col('Refund administration fee')
    c_aff = col('Affiliate Commission')
    c_aff_p = col('Affiliate partner commission')
    c_aff_sa = col('Affiliate Shop Ads commission')
    c_aff_psa = col('Affiliate Partner shop ads commission')
    c_cof = col('Co-funded promotion (seller-funded)')
    c_camp = col('Campaign service fee')
    c_adj = col('Adjustment amount')

    if c_oid < 0 or c_type < 0 or c_stid < 0:
        return {'added': 0, 'skipped': 0, 'errors': ['Missing required Settlement columns']}

    existing = set(SettlementRow.objects.values_list('order_id', 'settlement_id', 'row_type'))
    to_create = []
    skipped = 0
    unknown_types = {}

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[c_type]: continue
        oid = _clean_str(row[c_oid])
        sid = _clean_str(row[c_stid])
        rt = _clean_str(row[c_type])
        if not oid or not sid or not rt: continue
        key = (oid, sid, rt)
        if key in existing: skipped += 1; continue
        existing.add(key)

        created = _to_date(row[c_created]) if c_created >= 0 else None
        stmt = _to_date(row[c_stmt]) if c_stmt >= 0 else None
        date_for_log = created or stmt

        sr = SettlementRow(
            order_created_date=date_for_log,
            statement_date=stmt,
            order_id=oid, settlement_id=sid, row_type=rt,
            quantity=_to_int(row[c_qty]) if c_qty >= 0 else 0,
            source_file=filename,
        )

        if rt == 'Order':
            sr.referral_fee = _to_dec(row[c_ref]) if c_ref >= 0 else 0
            sr.affiliate_total = (
                _to_dec(row[c_aff]) if c_aff >= 0 else 0) + (
                _to_dec(row[c_aff_p]) if c_aff_p >= 0 else 0) + (
                _to_dec(row[c_aff_sa]) if c_aff_sa >= 0 else 0) + (
                _to_dec(row[c_aff_psa]) if c_aff_psa >= 0 else 0)
            sr.campaign_fee = _to_dec(row[c_camp]) if c_camp >= 0 else 0
            sr.refund_admin = _to_dec(row[c_refadmin]) if c_refadmin >= 0 else 0
            sr.fbt_fee = _to_dec(row[c_fbt_fee]) if c_fbt_fee >= 0 else 0
            sr.fbt_reimb = _to_dec(row[c_fbt_reimb]) if c_fbt_reimb >= 0 else 0
            sr.shipping = _to_dec(row[c_shipping]) if c_shipping >= 0 else 0
            sr.tt_ship_net = (
                _to_dec(row[c_tt_inc]) if c_tt_inc >= 0 else 0) + (
                _to_dec(row[c_subsidy]) if c_subsidy >= 0 else 0) + (
                _to_dec(row[c_offset]) if c_offset >= 0 else 0)
            sr.cofunded_promo = _to_dec(row[c_cof]) if c_cof >= 0 else 0
            sr.refund_total = (
                _to_dec(row[c_gross_ref]) if c_gross_ref >= 0 else 0) + (
                _to_dec(row[c_disc_ref]) if c_disc_ref >= 0 else 0)
        else:
            adj = _to_dec(row[c_adj]) if c_adj >= 0 else 0
            field = TYPE_TO_FIELD.get(rt)
            if field:
                setattr(sr, field, adj)
            else:
                sr.unclassified = adj
                unknown_types[rt] = unknown_types.get(rt, 0) + 1

        to_create.append(sr)

    with transaction.atomic():
        SettlementRow.objects.bulk_create(to_create, batch_size=500)
        note = ''
        if unknown_types:
            note = 'Unknown types: ' + '; '.join(f'{k}={v}' for k, v in unknown_types.items())
        ImportLog.objects.create(importer='settlement', filename=filename,
                                 rows_added=len(to_create), rows_skipped=skipped, notes=note)
    return {'added': len(to_create), 'skipped': skipped, 'unknown_types': unknown_types}


# ===========================================================================
# 3. Shop Analytics importer
# ===========================================================================
def import_shop_analytics(file_obj, filename=''):
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    start = -1
    for i, r in enumerate(rows):
        if r and str(r[0] or '').lower() == 'date':
            start = i + 1; break
    if start < 0:
        return {'added': 0, 'skipped': 0, 'errors': ['Could not find "Date" header']}

    # Pre-scan to detect format: if any row has day > 12, format is DD/MM/YYYY
    prefer_dd_mm = False
    for r in rows[start:]:
        if not r or not r[0]: continue
        s = str(r[0]).strip().split(' ')[0]
        parts = s.split('/')
        if len(parts) == 3:
            try:
                if int(parts[0]) > 12: prefer_dd_mm = True; break
            except: pass

    count = 0
    for r in rows[start:]:
        d = _to_date(r[0] if len(r) > 0 else None, prefer_dd_mm=prefer_dd_mm)
        gmv = _to_dec(r[1] if len(r) > 1 else 0)
        if not d: continue
        orders = _to_int(r[2] if len(r) > 2 else 0)
        items_sold = _to_int(r[4] if len(r) > 4 else 0)
        AnalyticsDay.objects.update_or_create(
            date=d, defaults={'gmv': gmv, 'orders': orders, 'items_sold': items_sold})
        count += 1
    ImportLog.objects.create(importer='shop_analytics', filename=filename, rows_added=count)
    return {'added': count, 'format_detected': 'DD/MM/YYYY' if prefer_dd_mm else 'MM/DD/YYYY'}


# ===========================================================================
# 4. Ad Spend importer
# ===========================================================================
def import_ad_spend(file_obj, filename=''):
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    start = -1
    for i, r in enumerate(rows):
        if r and 'by day' in str(r[0] or '').lower():
            start = i + 1; break
    if start < 0:
        return {'added': 0, 'skipped': 0, 'errors': ['Could not find "By Day" header']}

    # Pre-scan format
    prefer_dd_mm = False
    for r in rows[start:]:
        if not r or not r[0]: continue
        s = str(r[0]).strip().split(' ')[0]
        parts = s.split('/')
        if len(parts) == 3:
            try:
                if int(parts[0]) > 12: prefer_dd_mm = True; break
            except: pass

    count = 0
    for r in rows[start:]:
        d = _to_date(r[0] if len(r) > 0 else None, prefer_dd_mm=prefer_dd_mm)
        cost = _to_dec(r[1] if len(r) > 1 else 0)
        if not d: continue
        sku_orders = _to_int(r[2] if len(r) > 2 else 0)
        gross_rev = _to_dec(r[4] if len(r) > 4 else 0)
        AdSpendDay.objects.update_or_create(
            date=d, defaults={'cost': cost, 'sku_orders': sku_orders, 'gross_revenue': gross_rev})
        count += 1
    ImportLog.objects.create(importer='ad_spend', filename=filename, rows_added=count)
    return {'added': count, 'format_detected': 'DD/MM/YYYY' if prefer_dd_mm else 'MM/DD/YYYY'}


# ===========================================================================
# 5. FBT Billing importer
# ===========================================================================
FBT_LINE_TO_FIELD = {
    'Hub placement fee': 'fbt_hub_placement',
    'Storage fee': 'fbt_storage',
    'Inbound shipping fee': 'fbt_inbound_shipping',
    'Inbound incidents fee': 'fbt_inbound_incidents',
    'Inbound booking non-compliance fee': 'fbt_booking_noncomp',
    'Routing non-compliance fee': 'fbt_routing_noncomp',
    'Outbound appointment no-show fee': 'fbt_outbound_noshow',
    'Delayed response fee': 'fbt_delayed_response',
    'Disposal fee': 'fbt_disposal',
    'Return shipping fee': 'fbt_return_shipping',
    'Return to seller handling fee': 'fbt_return_seller_handling',
    'Inbound return operation fee': 'fbt_inbound_return_op',
}

def import_fbt_billing(file_obj, period, filename=''):
    """period must be 'YYYY-MM'."""
    if not period or len(period) != 7 or period[4] != '-':
        return {'errors': ['Invalid period — expected YYYY-MM']}
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    ws = wb[wb.sheetnames[0]]
    mi, _ = MonthlyInput.objects.get_or_create(month=period)
    count = 0
    for r in ws.iter_rows(values_only=True):
        if not r: continue
        line = _clean_str(r[1]) if len(r) > 1 else ''
        amt = _to_dec(r[2]) if len(r) > 2 else 0
        field = FBT_LINE_TO_FIELD.get(line)
        if field:
            setattr(mi, field, abs(amt))
            count += 1
    mi.save()
    ImportLog.objects.create(importer='fbt_billing', filename=filename,
                             rows_added=count, notes=f'Period: {period}')
    return {'added': count, 'period': period}
