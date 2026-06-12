"""
P&L aggregation logic. Pulls from DB, computes daily/monthly P&L lines.
"""
from decimal import Decimal
from datetime import date, timedelta
from calendar import monthrange
from django.db.models import Sum, Q
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
    """Returns a dict {date: {row_label: amount}} for the given range."""
    dates = date_range(start_date, end_date)
    result = {d: {} for d in dates}

    # Orders → Gross Sales + Less: Promos & Discounts (include ALL statuses).
    # Canceled orders also generate Settlement refund rows; including their gross
    # and discount here lets the refund line cancel them out cleanly, matching
    # TikTok's Reports tab view of Net Sales. Excluding canceled (the old behavior)
    # caused a double-count where the refund hit P&L with no offsetting gross.
    o_qs = Order.objects.filter(
        created_date__gte=start_date, created_date__lte=end_date
    ).values('created_date').annotate(
        gross=Sum('gross_sale'),
        disc=Sum('seller_discount'),
    )
    for r in o_qs:
        d = r['created_date']
        result[d]['Gross Sales'] = r['gross'] or ZERO
        result[d]['Less: Promos & Discounts'] = r['disc'] or ZERO

    # COGS → include non-canceled orders, PLUS canceled orders that actually
    # shipped (real fulfillment cost was incurred). Signal for "shipped" is the
    # presence of an FBT fulfillment fee row for that order in Settlement.
    # Pre-ship cancellations have no FBT fee → COGS correctly excluded.
    shipped_canceled_ids = set(SettlementRow.objects.filter(
        row_type='Order', fbt_fee__lt=0,
    ).values_list('order_id', flat=True))
    cogs_qs = Order.objects.filter(
        created_date__gte=start_date, created_date__lte=end_date,
    ).filter(
        ~Q(status__iexact='Canceled')
        | Q(status__iexact='Canceled', order_id__in=shipped_canceled_ids)
    ).values('created_date').annotate(cogs=Sum('cogs'))
    for r in cogs_qs:
        d = r['created_date']
        result[d]['COGS'] = -(r['cogs'] or ZERO)

    # Settlement aggregated by order_created_date
    s_qs = SettlementRow.objects.filter(
        order_created_date__gte=start_date, order_created_date__lte=end_date
    ).values('order_created_date').annotate(
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
        d = r['order_created_date']
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
        result[d]['   Co-funded Promotion (seller-funded)'] = r['cofunded_promo'] or ZERO
        result[d]['Less: Refunds'] = r['refund_total'] or ZERO
        result[d]['   Chargebacks'] = r['chargeback'] or ZERO
        result[d]['   Violation Fee'] = r['violation'] or ZERO
        result[d]['   TikTok Shop Reimb'] = r['tt_shop_reimb'] or ZERO
        result[d]['   Logistics Reimbursement'] = r['logistics_reimb'] or ZERO
        result[d]['   FBT Warehouse Compensation'] = r['fbt_warehouse_comp'] or ZERO
        result[d]['   Rebate'] = r['rebate'] or ZERO
        result[d]['   Unclassified Adjustments'] = r['unclassified'] or ZERO

    # Analytics GMV (overrides derived)
    for a in AnalyticsDay.objects.filter(date__gte=start_date, date__lte=end_date):
        result[a.date]['GMV'] = a.gmv

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
    # If any shipment rows exist for a month, use real daily sums for that whole month
    # (overrides the flat-spread from Monthly Inputs).
    ship_qs = SellerShipmentCost.objects.filter(
        shipped_date__gte=start_date, shipped_date__lte=end_date
    ).values('shipped_date').annotate(total=Sum('postage'))
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
        # GMV = Gross + Promos (post-discount, pre-refund). Matches TikTok portal definition.
        # Net Revenue = GMV + Refunds (refunds are stored negative).
        if 'GMV' not in row:
            row['GMV'] = gross + promos
        row['NET REVENUE'] = row['GMV'] + refunds

        # GROSS PROFIT
        gp_items = ['NET REVENUE', 'COGS',
                    '   FBT Fulfillment Fee', '   FBT Fulfillment Reimbursement',
                    '   TT Shop Shipping Incentive', '   Shipping Fee Subsidy',
                    '   Customer Shipping Fee Offset',
                    '   Customer-Paid Shipping Fee', '   Customer-Paid Shipping Refund',
                    '   Cost to Ship to FBT', '   Cost to Ship to Customer',
                    '   Logistics Reimbursement',
                    '   FBT Hub Placement Fee', '   FBT Storage Fee',
                    '   FBT Inbound Shipping Fee', '   FBT Inbound Incidents Fee',
                    '   FBT Booking Non-Compliance', '   FBT Routing Non-Compliance',
                    '   FBT Outbound No-Show', '   FBT Delayed Response Fee',
                    '   FBT Disposal Fee', '   FBT Return Shipping (VAS)',
                    '   FBT Return to Seller Handling', '   FBT Inbound Return Operation',
                    '   FBT Warehouse Compensation',
                    '   Referral Fee', '   Refund Admin Fee', '   Campaign Service Fee',
                    '   Violation Fee', '   TikTok Shop Reimb', '   Rebate',
                    '   Co-funded Promotion (seller-funded)']
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
    """Aggregate Daily P&L into Monthly P&L for the given year."""
    months = {}
    for m in range(1, 13):
        start = date(year, m, 1)
        end = date(year, m, monthrange(year, m)[1])
        daily = compute_daily_pnl(start, end)
        monthly = {}
        for d, row in daily.items():
            for label, val in row.items():
                monthly[label] = monthly.get(label, ZERO) + (val or ZERO)
        months[f'{year:04d}-{m:02d}'] = monthly
    return months


PNL_ROW_LAYOUT = [
    ('REVENUE', 'section'),
    ('Gross Sales', 'row'),
    ('Less: Promos & Discounts', 'row'),
    ('GMV', 'row'),
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
    ('Platform Fees', 'sub'),
    ('   Referral Fee', 'row'),
    ('   Refund Admin Fee', 'row'),
    ('   Campaign Service Fee', 'row'),
    ('   Violation Fee', 'row'),
    ('   TikTok Shop Reimb', 'row'),
    ('   Rebate', 'row'),
    ('   Co-funded Promotion (seller-funded)', 'row'),
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
