"""
P&L aggregation logic. Pulls from DB, computes daily/monthly P&L lines.
"""
from decimal import Decimal
from datetime import date, timedelta
from calendar import monthrange
from django.db.models import Sum, Q, F
from .models import Order, SettlementRow, AnalyticsDay, AdSpendDay, MonthlyInput, SellerShipmentCost, AdLedgerDay, AdLedgerConfig


ZERO = Decimal('0')


def days_in_month(yyyy_mm):
    y, m = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    return monthrange(y, m)[1]


def date_range(d1, d2):
    cur = d1
    out = []
    while cur <= d2:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def compute_daily_pnl(start_date, end_date):
    """Returns a dict {date: {row_label: amount}} for the given range.

    Attribution methodology (settlement-date basis, per Lindsay + Jack 2026-06-25):
      • Gross Sales / Promos / COGS / Refunds → SettlementRow.statement_date
        of the order's primary 'Order' settlement row (joined via order_id).
      • All TikTok Shop fees (Affiliate, Referral, FBT fee, Co-funded promo, etc.)
        → SettlementRow.statement_date.
      • Cost to Ship to Customer → SellerShipmentCost.shipped_date.
      • Ad Spend / GMV reference / Ad Ledger → unchanged (already daily).
      • Monthly Inputs (manual entries, FBT Billing) → unchanged (flat-spread).

    Orders without a settled 'Order' row in range are NOT counted — they haven't
    cleared TikTok's settlement window yet. They'll appear once they settle and
    a fresh settlement file is uploaded.
    """
    dates = date_range(start_date, end_date)
    result = {d: {} for d in dates}

    # Build {order_id: statement_date} from primary 'Order'-type settlement rows
    # in our range. Use earliest statement_date when an order has multiple rows.
    from django.db.models import Min
    order_stmt_qs = SettlementRow.objects.filter(
        row_type='Order',
        statement_date__gte=start_date,
        statement_date__lte=end_date,
    ).values('order_id').annotate(stmt=Min('statement_date'))
    order_stmt_map = {r['order_id']: r['stmt'] for r in order_stmt_qs}

    # Orders → Gross Sales + Less: Promos & Discounts, attributed by their
    # settlement statement_date (not creation date). Include ALL statuses;
    # Canceled orders that generate refund rows offset cleanly on the same day.
    shipped_canceled_ids = set(SettlementRow.objects.filter(
        row_type='Order', fbt_fee__lt=0,
    ).values_list('order_id', flat=True))

    o_qs = Order.objects.filter(
        order_id__in=order_stmt_map.keys(),
    ).values('order_id', 'gross_sale', 'seller_discount', 'cogs', 'status')

    for o in o_qs:
        d = order_stmt_map.get(o['order_id'])
        if d not in result:
            continue
        row = result[d]
        row['Gross Sales'] = row.get('Gross Sales', ZERO) + (o['gross_sale'] or ZERO)
        row['Less: Promos & Discounts'] = row.get('Less: Promos & Discounts', ZERO) + (o['seller_discount'] or ZERO)
        # COGS — include non-canceled orders, plus Canceled-but-shipped (FBT fee
        # signal). Pre-ship cancellations excluded (no real fulfillment cost).
        is_canceled = (o['status'] or '').strip().lower() == 'canceled'
        if (not is_canceled) or (o['order_id'] in shipped_canceled_ids):
            row['COGS'] = row.get('COGS', ZERO) - (o['cogs'] or ZERO)

    # Settlement aggregations — group by statement_date (was order_created_date).
    # Every settlement row carries its own statement_date so refunds, fees, and
    # adjustments naturally land on the day TikTok processed them.
    s_qs = SettlementRow.objects.filter(
        statement_date__gte=start_date, statement_date__lte=end_date
    ).values('statement_date').annotate(
        referral=Sum('referral_fee'),
        affiliate=Sum('affiliate_total'),
        campaign=Sum('campaign_fee'),
        refund_admin=Sum('refund_admin'),
        fbt_fee=Sum('fbt_fee'),
        fbt_reimb=Sum('fbt_reimb'),
        shipping=Sum('shipping'),
        tt_shop_shipping_incentive=Sum('tt_shop_shipping_incentive'),
        shipping_fee_subsidy=Sum('shipping_fee_subsidy'),
        customer_shipping_fee_offset=Sum('customer_shipping_fee_offset'),
        customer_paid_shipping_fee=Sum('customer_paid_shipping_fee'),
        customer_paid_shipping_refund=Sum('customer_paid_shipping_refund'),
        cofunded_promo=Sum('cofunded_promo'),
        cofunded_promo_campaign_fee=Sum('cofunded_promo_campaign_fee'),
        seller_shipping_fee_discount=Sum('seller_shipping_fee_discount'),
        refund_total=Sum('refund_total'),
        chargeback=Sum('chargeback'),
        violation=Sum('violation'),
        tt_shop_reimb=Sum('tt_shop_reimb'),
        logistics_reimb=Sum('logistics_reimb'),
        fbt_warehouse=Sum('fbt_warehouse'),
        fbt_warehouse_comp=Sum('fbt_warehouse_comp'),
        rebate=Sum('rebate'),
        unclassified=Sum('unclassified'),
    )
    for r in s_qs:
        d = r['statement_date']
        if not d: continue
        result[d]['   Referral Fee'] = r['referral'] or ZERO
        result[d]['   Platform (Affiliate Commission)'] = r['affiliate'] or ZERO
        result[d]['   Campaign Service Fee'] = r['campaign'] or ZERO
        result[d]['   Refund Admin Fee'] = r['refund_admin'] or ZERO
        # Settlement's `Shipping` column (col U) is the parent total of 7 sub-components:
        #   FBT fulfillment fee, FBT fulfillment reimbursement,
        #   TT Shop shipping incentive, Shipping fee subsidy, Customer shipping fee offset,
        #   Customer-paid shipping fee, Customer-paid shipping fee refund.
        # Surfacing each component as its own line gives full P&L visibility and matches
        # TikTok's Reports tab "Shipping" parent exactly when summed.
        result[d]['   FBT Fulfillment Fee'] = r['fbt_fee'] or ZERO
        result[d]['   FBT Fulfillment Reimbursement'] = r['fbt_reimb'] or ZERO
        result[d]['   TT Shop Shipping Incentive'] = r['tt_shop_shipping_incentive'] or ZERO
        result[d]['   Shipping Fee Subsidy'] = r['shipping_fee_subsidy'] or ZERO
        result[d]['   Customer Shipping Fee Offset'] = r['customer_shipping_fee_offset'] or ZERO
        result[d]['   Customer-Paid Shipping Fee'] = r['customer_paid_shipping_fee'] or ZERO
        result[d]['   Customer-Paid Shipping Refund'] = r['customer_paid_shipping_refund'] or ZERO
        result[d]['   Seller Shipping Fee Discount'] = r['seller_shipping_fee_discount'] or ZERO
        result[d]['   Co-funded Promotion (seller-funded)'] = r['cofunded_promo'] or ZERO
        result[d]['   Co-funded Promotion Campaign Period Fee'] = r['cofunded_promo_campaign_fee'] or ZERO
        result[d]['   FBT Warehouse Service Fee'] = r['fbt_warehouse'] or ZERO
        result[d]['Less: Refunds'] = r['refund_total'] or ZERO
        result[d]['   Chargebacks'] = r['chargeback'] or ZERO
        result[d]['   Violation Fee'] = r['violation'] or ZERO
        result[d]['   TikTok Shop Reimb'] = r['tt_shop_reimb'] or ZERO
        result[d]['   Logistics Reimbursement'] = r['logistics_reimb'] or ZERO
        result[d]['   FBT Warehouse Compensation'] = r['fbt_warehouse_comp'] or ZERO
        result[d]['   Rebate'] = r['rebate'] or ZERO
        result[d]['   Unclassified Adjustments'] = r['unclassified'] or ZERO

    # TikTok Shop Analytics GMV — kept as a REFERENCE line only.
    # Method A (computed Gross - Discount from Manage Orders) is now the
    # authoritative GMV for accrual consistency with the rest of the P&L.
    # This line is informational so you can compare to TikTok's headline number.
    for a in AnalyticsDay.objects.filter(date__gte=start_date, date__lte=end_date):
        result[a.date]['GMV (TikTok Analytics — reference)'] = a.gmv

    # Ad spend (raw cost; sign-flip happens in totals)
    for a in AdSpendDay.objects.filter(date__gte=start_date, date__lte=end_date):
        result[a.date]['Ad Spend — Direct to TikTok (cash)'] = -a.cost

    # Monthly Inputs → flat-spread overlays
    months_in_range = set()
    for d in dates:
        months_in_range.add(f'{d.year:04d}-{d.month:02d}')
    mi_map = {mi.month: mi for mi in MonthlyInput.objects.filter(month__in=months_in_range)}

    overlay_fields = {
        '   Team Spend': ('team_spend', -1),
        '   Software & Tools': ('software_tools', -1),
        '   Monthly Retainers': ('monthly_retainers', -1),
        '   Outsourced Agency': ('creatify', -1),
        '   Off-Platform (1% method)': ('off_platform_1pct', -1),
        '   Other G&A': ('other_ga', -1),
        '   Less: TT Promo Credits': ('tt_promo_credits', +1),
        '   Cost to Ship to FBT': ('cost_ship_to_fbt', -1),
        # Cost to Ship to Customer is NOT here — it's populated exclusively from
        # SellerShipmentCost (Seller Shipping CSV import). No manual flat-spread.
        '   FBT Hub Placement Fee': ('fbt_hub_placement', -1),
        '   FBT Storage Fee': ('fbt_storage', -1),
        '   FBT Inbound Shipping Fee': ('fbt_inbound_shipping', -1),
        '   FBT Inbound Incidents Fee': ('fbt_inbound_incidents', -1),
        '   FBT Booking Non-Compliance': ('fbt_booking_noncomp', -1),
        '   FBT Routing Non-Compliance': ('fbt_routing_noncomp', -1),
        '   FBT Outbound No-Show': ('fbt_outbound_noshow', -1),
        '   FBT Delayed Response Fee': ('fbt_delayed_response', -1),
        '   FBT Disposal Fee': ('fbt_disposal', -1),
        '   FBT Return Shipping (VAS)': ('fbt_return_shipping', -1),
        '   FBT Return to Seller Handling': ('fbt_return_seller_handling', -1),
        '   FBT Inbound Return Operation': ('fbt_inbound_return_op', -1),
    }

    for d in dates:
        mkey = f'{d.year:04d}-{d.month:02d}'
        mi = mi_map.get(mkey)
        if not mi: continue
        dim = days_in_month(mkey)
        for label, (field, sign) in overlay_fields.items():
            val = getattr(mi, field) or ZERO
            result[d][label] = Decimal(sign) * val / dim

    # Seller-shipping per-day override for Cost to Ship to Customer.
    # Cost = postage + per_pack + per_pick (the full 3PL line item per shipment).
    # Attribution: shipped_date (the day Jetpack actually shipped the package).
    # Per Lindsay 2026-06-25 — shipping costs land on the day the order was
    # shipped, not the day it was created. This is internally consistent with
    # the Settlement-date methodology elsewhere on the P&L.
    ship_qs = SellerShipmentCost.objects.filter(
        shipped_date__gte=start_date, shipped_date__lte=end_date,
    ).values('shipped_date').annotate(
        total=Sum(F('postage') + F('per_pack') + F('per_pick')),
    )
    daily_ship = {r['shipped_date']: r['total'] or ZERO for r in ship_qs}
    months_with_ship = {f'{d.year:04d}-{d.month:02d}' for d in daily_ship.keys()}
    for d in dates:
        mkey = f'{d.year:04d}-{d.month:02d}'
        if mkey in months_with_ship:
            result[d]['   Cost to Ship to Customer'] = -(daily_ship.get(d, ZERO))

    # Ad Ledger override — only kicks in when AdLedgerConfig.feed_pnl == True,
    # i.e. the user has explicitly enabled the FIFO engine after verifying it.
    # Until then, P&L falls back to the manual values (TBSM Savings = $0,
    # TT Promo Credits = Monthly Input flat-spread) so an in-progress ledger
    # build can't corrupt the P&L.
    ledger_cfg = AdLedgerConfig.objects.filter(pk=1).first()
    if ledger_cfg and ledger_cfg.feed_pnl:
        ledger_qs = AdLedgerDay.objects.filter(date__gte=start_date, date__lte=end_date)
        for ald in ledger_qs:
            d = ald.date
            result[d]['   Less: TBSM Savings'] = ald.savings_tbsm or ZERO
            result[d]['   Less: TT Promo Credits'] = ald.savings_promo or ZERO

    # Compute calc rows per date
    for d in dates:
        row = result[d]
        gross = row.get('Gross Sales', ZERO)
        promos = row.get('Less: Promos & Discounts', ZERO)
        refunds = row.get('Less: Refunds', ZERO)
        # GMV is always computed = Gross + Promos (post-discount, pre-refund).
        # Method A: accrual-consistent with the rest of the P&L. The TikTok
        # Analytics GMV is shown alongside as a reference line but does not
        # drive the math.
        row['GMV'] = gross + promos
        row['NET REVENUE'] = row['GMV'] + refunds

        # GROSS PROFIT
        gp_items = ['NET REVENUE', 'COGS',
                    '   FBT Fulfillment Fee', '   FBT Fulfillment Reimbursement',
                    '   TT Shop Shipping Incentive', '   Shipping Fee Subsidy',
                    '   Customer Shipping Fee Offset',
                    '   Customer-Paid Shipping Fee', '   Customer-Paid Shipping Refund',
                    '   Seller Shipping Fee Discount',
                    '   Cost to Ship to FBT', '   Cost to Ship to Customer',
                    '   Logistics Reimbursement',
                    '   FBT Hub Placement Fee', '   FBT Storage Fee',
                    '   FBT Inbound Shipping Fee', '   FBT Inbound Incidents Fee',
                    '   FBT Booking Non-Compliance', '   FBT Routing Non-Compliance',
                    '   FBT Outbound No-Show', '   FBT Delayed Response Fee',
                    '   FBT Disposal Fee', '   FBT Return Shipping (VAS)',
                    '   FBT Return to Seller Handling', '   FBT Inbound Return Operation',
                    '   FBT Warehouse Compensation', '   FBT Warehouse Service Fee',
                    '   Referral Fee', '   Refund Admin Fee', '   Campaign Service Fee',
                    '   Violation Fee', '   TikTok Shop Reimb', '   Rebate',
                    '   Co-funded Promotion (seller-funded)',
                    '   Co-funded Promotion Campaign Period Fee']
        row['GROSS PROFIT'] = sum((row.get(x, ZERO) for x in gp_items), ZERO)

        # Ad spend: raw cost minus TBSM Savings (FIFO engine) minus TT Promo Credits.
        # ad is negative; savings are positive credits that reduce the negative total.
        ad = row.get('Ad Spend — Direct to TikTok (cash)', ZERO)
        tbsm_sav = row.get('   Less: TBSM Savings', ZERO)
        tt_promo = row.get('   Less: TT Promo Credits', ZERO)
        row['Total Ad Spend'] = ad + tbsm_sav + tt_promo

        # TOTAL MARKETING
        row['TOTAL MARKETING'] = (row['Total Ad Spend']
            + row.get('   Platform (Affiliate Commission)', ZERO)
            + row.get('   Off-Platform (1% method)', ZERO)
            + row.get('   Monthly Retainers', ZERO)
            + row.get('   Outsourced Agency', ZERO))

        # TOTAL SG&A
        row['TOTAL SG&A'] = (row.get('   Team Spend', ZERO)
            + row.get('   Software & Tools', ZERO)
            + row.get('   Other G&A', ZERO)
            + row.get('   Chargebacks', ZERO)
            + row.get('   Unclassified Adjustments', ZERO))

        row['NET PROFIT'] = row['GROSS PROFIT'] + row['TOTAL MARKETING'] + row['TOTAL SG&A']

    return result


def compute_monthly_pnl(year):
    """Aggregate Daily P&L into Monthly P&L for the given year.

    Runs ONE year-wide compute_daily_pnl and buckets the result by month.
    Previously called compute_daily_pnl 12 times, which made the Monthly P&L
    page do ~12× the database round-trips it needed. Same numbers, much faster.
    """
    daily = compute_daily_pnl(date(year, 1, 1), date(year, 12, 31))
    months = {f'{year:04d}-{m:02d}': {} for m in range(1, 13)}
    for d, row in daily.items():
        mkey = f'{d.year:04d}-{d.month:02d}'
        mrow = months[mkey]
        for label, val in row.items():
            mrow[label] = mrow.get(label, ZERO) + (val or ZERO)
    return months


PNL_ROW_LAYOUT = [
    ('REVENUE', 'section'),
    ('Gross Sales', 'row'),
    ('Less: Promos & Discounts', 'row'),
    ('GMV', 'row'),
    ('GMV (TikTok Analytics — reference)', 'row'),
    ('Less: Refunds', 'row'),
    ('NET REVENUE', 'total'),
    ('', 'blank'),
    ('COGS, FULFILLMENT & PLATFORM', 'section'),
    ('COGS', 'row'),
    ('Fulfillment', 'sub'),
    ('   FBT Fulfillment Fee', 'row'),
    ('   FBT Fulfillment Reimbursement', 'row'),
    ('   TT Shop Shipping Incentive', 'row'),
    ('   Shipping Fee Subsidy', 'row'),
    ('   Customer Shipping Fee Offset', 'row'),
    ('   Customer-Paid Shipping Fee', 'row'),
    ('   Customer-Paid Shipping Refund', 'row'),
    ('   Seller Shipping Fee Discount', 'row'),
    ('   Cost to Ship to FBT', 'row'),
    ('   Cost to Ship to Customer', 'row'),
    ('   Logistics Reimbursement', 'row'),
    ('   FBT Hub Placement Fee', 'row'),
    ('   FBT Storage Fee', 'row'),
    ('   FBT Inbound Shipping Fee', 'row'),
    ('   FBT Inbound Incidents Fee', 'row'),
    ('   FBT Booking Non-Compliance', 'row'),
    ('   FBT Routing Non-Compliance', 'row'),
    ('   FBT Outbound No-Show', 'row'),
    ('   FBT Delayed Response Fee', 'row'),
    ('   FBT Disposal Fee', 'row'),
    ('   FBT Return Shipping (VAS)', 'row'),
    ('   FBT Return to Seller Handling', 'row'),
    ('   FBT Inbound Return Operation', 'row'),
    ('   FBT Warehouse Compensation', 'row'),
    ('   FBT Warehouse Service Fee', 'row'),
    ('Platform Fees', 'sub'),
    ('   Referral Fee', 'row'),
    ('   Refund Admin Fee', 'row'),
    ('   Campaign Service Fee', 'row'),
    ('   Violation Fee', 'row'),
    ('   TikTok Shop Reimb', 'row'),
    ('   Rebate', 'row'),
    ('   Co-funded Promotion (seller-funded)', 'row'),
    ('   Co-funded Promotion Campaign Period Fee', 'row'),
    ('GROSS PROFIT', 'total'),
    ('', 'blank'),
    ('MARKETING', 'section'),
    ('Ad Spend — Direct to TikTok (cash)', 'row'),
    ('   Less: TBSM Savings', 'row'),
    ('   Less: TT Promo Credits', 'row'),
    ('Total Ad Spend', 'total'),
    ('Creator Commissions', 'sub'),
    ('   Platform (Affiliate Commission)', 'row'),
    ('   Off-Platform (1% method)', 'row'),
    ('Creator Retainers', 'sub'),
    ('   Monthly Retainers', 'row'),
    ('   Outsourced Agency', 'row'),
    ('TOTAL MARKETING', 'total'),
    ('', 'blank'),
    ('SG&A', 'section'),
    ('   Team Spend', 'row'),
    ('   Software & Tools', 'row'),
    ('   Other G&A', 'row'),
    ('   Chargebacks', 'row'),
    ('   Unclassified Adjustments', 'row'),
    ('TOTAL SG&A', 'total'),
    ('', 'blank'),
    ('NET PROFIT', 'total'),
]
