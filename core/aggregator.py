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


def _data_version():
    """Latest ImportLog.id — used as a cache invalidation key.
    Every successful import increments this, auto-busting stale daily-PnL
    cache entries the next time the dashboard / daily / export hits us.
    Returns 0 if no imports yet (fresh DB) so first compute still caches."""
    try:
        from .models import ImportLog
        return ImportLog.objects.order_by('-id').values_list('id', flat=True).first() or 0
    except Exception:
        return 0


def compute_daily_pnl(start_date, end_date, use_cache=True):
    """Cached + exception-guarded entry point. Wraps _compute_daily_pnl_impl
    with a per-(range, data-version) cache. If the inner compute raises (DB
    error, OOM unwind, anything), we log the full traceback and return an
    empty-but-valid result so the page can still render with zeros instead of
    a generic 500. The Render logs will show what actually failed."""
    if not use_cache:
        try:
            return _compute_daily_pnl_impl(start_date, end_date)
        except Exception:
            import logging
            logging.getLogger('core').exception(
                'compute_daily_pnl crashed for %s..%s', start_date, end_date)
            return {d: {} for d in date_range(start_date, end_date)}
    from django.core.cache import cache
    key = f'daily_pnl:v{_data_version()}:{start_date.isoformat()}:{end_date.isoformat()}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        result = _compute_daily_pnl_impl(start_date, end_date)
    except Exception:
        import logging
        logging.getLogger('core').exception(
            'compute_daily_pnl crashed for %s..%s', start_date, end_date)
        # Return an empty-but-valid skeleton — don't cache it (transient).
        return {d: {} for d in date_range(start_date, end_date)}
    cache.set(key, result, timeout=60 * 60 * 24)
    return result


def _compute_daily_pnl_impl(start_date, end_date):
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

    # Gross Sales + Promos & Discounts + COGS — aggregated entirely at the DB
    # level via a single JOIN between Order and SettlementRow. Previously we
    # built an in-memory {order_id: statement_date} dict of ~200k entries and
    # then materialized ~200k Order rows into Python, which caused OOM kills
    # on the Standard tier when the year was data-heavy. The raw SQL below
    # never materializes order-level rows in Python — Postgres does the join,
    # the GROUP BY, and the SUM, then returns one row per statement_date.
    #
    # COGS exclusion rule (pre-ship cancellations): a Canceled order is only
    # included in COGS when an FBT fulfillment fee row exists for it (signal
    # that it actually shipped). The CASE expression handles that inline.
    from django.db import connection
    with connection.cursor() as cur:
        # Single CTE-driven aggregation. We use a LEFT JOIN against the
        # "shipped_canceled" set instead of a correlated IN-subquery so
        # Postgres uses a hash join (fast) rather than a nested-loop lookup
        # per row (catastrophic on 200k orders).
        # MIN(statement_date) must be computed over ALL history (no date filter
        # inside the CTE) so the order's attribution is STABLE regardless of
        # which date range we're computing. Otherwise the same order moves
        # between months depending on whether you query May-only vs full-year
        # (a settlement-row in Mar + another in May → MIN-in-May-range = May,
        # MIN-in-full-year = Mar → different attribution → dashboard ≠ export).
        # We filter at the OUTER query so each order has exactly one canonical
        # statement_date forever.
        cur.execute(
            '''
            WITH order_stmt AS (
                SELECT order_id, MIN(statement_date) AS stmt_date
                FROM core_settlementrow
                WHERE row_type = 'Order'
                  AND statement_date IS NOT NULL
                GROUP BY order_id
            ),
            shipped_canceled AS (
                SELECT DISTINCT order_id
                FROM core_settlementrow
                WHERE row_type = 'Order' AND fbt_fee < 0
            )
            SELECT
                os.stmt_date,
                SUM(o.gross_sale)       AS gross,
                SUM(o.seller_discount)  AS promos,
                SUM(CASE
                    WHEN LOWER(COALESCE(o.status, '')) <> 'canceled'
                         OR sc.order_id IS NOT NULL
                    THEN o.cogs ELSE 0
                END) AS cogs
            FROM core_order o
            INNER JOIN order_stmt os ON os.order_id = o.order_id
            LEFT  JOIN shipped_canceled sc ON sc.order_id = o.order_id
            WHERE os.stmt_date BETWEEN %s AND %s
            GROUP BY os.stmt_date
            ''', [start_date, end_date])
        for stmt_d, gross, promos, cogs in cur.fetchall():
            if stmt_d not in result:
                continue
            row = result[stmt_d]
            row['Gross Sales'] = Decimal(gross or 0)
            row['Less: Promos & Discounts'] = Decimal(promos or 0)
            row['COGS'] = -Decimal(cogs or 0)

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
        tt_shop_shipping_incentive_refund=Sum('tt_shop_shipping_incentive_refund'),
        shipping_fee_subsidy=Sum('shipping_fee_subsidy'),
        customer_shipping_fee_offset=Sum('customer_shipping_fee_offset'),
        customer_paid_shipping_fee=Sum('customer_paid_shipping_fee'),
        customer_paid_shipping_refund=Sum('customer_paid_shipping_refund'),
        cofunded_promo=Sum('cofunded_promo'),
        cofunded_promo_campaign_fee=Sum('cofunded_promo_campaign_fee'),
        # NOTE: `seller_shipping_fee_discount` intentionally NOT aggregated for the
        # P&L. Per Jack 2026-06-30: TikTok's "Customer-paid shipping fee" column
        # is ALREADY the net (= before-discounts + seller-shipping-discount +
        # tt-shop-shipping-discount). Booking Seller Shipping Fee Discount as a
        # separate P&L line was double-counting the seller's portion.
        # The DB field still exists + Settlement importer still populates it
        # (visible in Source — Settlement sheet) for transparency / audit.
        refund_total=Sum('refund_total'),
        chargeback=Sum('chargeback'),
        violation=Sum('violation'),
        tt_shop_reimb=Sum('tt_shop_reimb'),
        logistics_reimb=Sum('logistics_reimb'),
        fbt_warehouse=Sum('fbt_warehouse'),
        fbt_warehouse_comp=Sum('fbt_warehouse_comp'),
        rebate=Sum('rebate'),
        unclassified=Sum('unclassified'),
        smart_promo_fee=Sum('smart_promo_fee'),
        smart_promo_campaign_period_fee=Sum('smart_promo_campaign_period_fee'),
        fbt_overall_merchant_subsidy=Sum('fbt_overall_merchant_subsidy'),
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
        result[d]['   TT Shop Shipping Incentive Refund'] = r['tt_shop_shipping_incentive_refund'] or ZERO
        result[d]['   Shipping Fee Subsidy'] = r['shipping_fee_subsidy'] or ZERO
        result[d]['   Customer Shipping Fee Offset'] = r['customer_shipping_fee_offset'] or ZERO
        result[d]['   Customer-Paid Shipping Fee'] = r['customer_paid_shipping_fee'] or ZERO
        result[d]['   Customer-Paid Shipping Refund'] = r['customer_paid_shipping_refund'] or ZERO
        # `seller_shipping_fee_discount` not surfaced — see Settlement annotate
        # comment for the double-count rationale (Jack 2026-06-30).
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
        # New (Jul 2026): sub-components of TikTok's Shipping + Fees parent aggregates.
        # See migration 0012 for the rationale.
        result[d]['   Smart Promotion Fee'] = r['smart_promo_fee'] or ZERO
        result[d]['   Smart Promotion Campaign Period Fee'] = r['smart_promo_campaign_period_fee'] or ZERO
        result[d]['   FBT Overall Merchant Subsidy'] = r['fbt_overall_merchant_subsidy'] or ZERO

    # TikTok Shop Analytics GMV — kept as a REFERENCE line only.
    # Method A (computed Gross - Discount from Manage Orders) is now the
    # authoritative GMV for accrual consistency with the rest of the P&L.
    # This line is informational so you can compare to TikTok's headline number.
    for a in AnalyticsDay.objects.filter(date__gte=start_date, date__lte=end_date):
        result[a.date]['GMV (TikTok Analytics — reference)'] = a.gmv

    # Ad spend (raw cost; sign-flip happens in totals)
    for a in AdSpendDay.objects.filter(date__gte=start_date, date__lte=end_date):
        result[a.date]['Ad Spend — Direct to TikTok (cash)'] = -a.cost

    # Monthly Inputs — split into two groups by attribution method:
    #
    #   NON_FBT_OVERLAY: stays flat-spread across the SERVICES month (current
    #   behavior). These are manual entries with no statement-date concept,
    #   and Cost to Ship to FBT which comes from Jetpack invoices not TikTok.
    #
    #   FBT_OVERLAY: 12 TikTok-billed FBT detail lines (Hub Placement, Storage,
    #   etc.). When an FBTBillingSchedule exists for a services month, these
    #   are attributed to the DESTINATION month (statement_date's month) and
    #   flat-spread across the destination month's days — keeping the daily
    #   P&L smooth (no day-1 spikes) while pushing the cost to the month
    #   TikTok actually charged it. Without a schedule, falls back to
    #   flat-spread within the services month (legacy behavior).
    #
    # Per Lindsay 2026-06-26.
    NON_FBT_OVERLAY = {
        '   Team Spend': ('team_spend', -1),
        '   Software & Tools': ('software_tools', -1),
        '   Monthly Retainers': ('monthly_retainers', -1),
        '   Outsourced Agency': ('creatify', -1),
        '   Off-Platform (1% method)': ('off_platform_1pct', -1),
        '   Other G&A': ('other_ga', -1),
        '   Less: TT Promo Credits': ('tt_promo_credits', +1),
        '   Cost to Ship to FBT': ('cost_ship_to_fbt', -1),
    }
    FBT_OVERLAY = {
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

    # Build {dest_month_YYYY_MM: services_period_YYYY_MM} from FBTBillingSchedule.
    # Each schedule row says: "the period that was billed → settled on this
    # statement_date." The destination month is the month of the statement_date.
    # If a period has multiple statement_dates (e.g., Jan 2026 settled Feb 2 +
    # Feb 10), they typically land in the same destination month so we map
    # period→dest_month directly. (If they ever splinter across months we'd
    # need to allocate by amount — leaving that for later.)
    from .models import FBTBillingSchedule as _Sched
    sched_map = {}  # dest_month → services_period
    for sch in _Sched.objects.all():
        dest_month = f'{sch.statement_date.year:04d}-{sch.statement_date.month:02d}'
        # If multiple rows land on same dest_month, keep the same period (they
        # share one). If a period somehow spans dest_months, last write wins —
        # acceptable given how TikTok actually settles.
        sched_map[dest_month] = sch.period

    # Pre-load MonthlyInput rows for ALL services months that might feed into
    # the destination months we're rendering (a few months back to be safe).
    services_periods_needed = set()
    for d in dates:
        dest_mkey = f'{d.year:04d}-{d.month:02d}'
        if dest_mkey in sched_map:
            services_periods_needed.add(sched_map[dest_mkey])
        # Also still need MonthlyInput for the day's own month (non-FBT overlay)
        services_periods_needed.add(dest_mkey)
    mi_map = {mi.month: mi for mi in MonthlyInput.objects.filter(month__in=services_periods_needed)}

    for d in dates:
        dest_mkey = f'{d.year:04d}-{d.month:02d}'
        dim = days_in_month(dest_mkey)

        # ---- Non-FBT overlay: spread the day's own month's value ----
        mi_for_day = mi_map.get(dest_mkey)
        if mi_for_day:
            for label, (field, sign) in NON_FBT_OVERLAY.items():
                val = getattr(mi_for_day, field) or ZERO
                result[d][label] = Decimal(sign) * val / dim

        # ---- FBT overlay: services-month attribution ----
        # REVERTED (Jul 2026) per Jack: FBT detail lines (Hub Placement,
        # Storage, Routing Non-Compliance, Incidents, Delayed Response,
        # Disposal, etc.) now attribute to the SERVICES month — the month
        # the warehouse work happened — NOT the month TikTok charged.
        # This matches how Jack reads the P&L side-by-side with TikTok's
        # own billing period grouping. FBTBillingSchedule table + Payment
        # Cycle upload are still in the codebase in case we ever need to
        # switch back, but they no longer drive attribution.
        if mi_for_day:
            for label, (field, sign) in FBT_OVERLAY.items():
                val = getattr(mi_for_day, field) or ZERO
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
                    '   TT Shop Shipping Incentive', '   TT Shop Shipping Incentive Refund',
                    '   Shipping Fee Subsidy',
                    '   Customer Shipping Fee Offset',
                    '   Customer-Paid Shipping Fee', '   Customer-Paid Shipping Refund',
                    # '   Seller Shipping Fee Discount' removed 2026-06-30 — its
                    # value is already baked into the NET Customer-Paid Shipping
                    # Fee column. Including it double-counted the seller portion.
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
                    '   Co-funded Promotion Campaign Period Fee',
                    '   Smart Promotion Fee',
                    '   Smart Promotion Campaign Period Fee',
                    '   FBT Overall Merchant Subsidy']
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

        # TOTAL G&A
        row['TOTAL G&A'] = (row.get('   Team Spend', ZERO)
            + row.get('   Software & Tools', ZERO)
            + row.get('   Other G&A', ZERO)
            + row.get('   Chargebacks', ZERO)
            + row.get('   Unclassified Adjustments', ZERO))

        row['NET PROFIT'] = row['GROSS PROFIT'] + row['TOTAL MARKETING'] + row['TOTAL G&A']

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
    ('   TT Shop Shipping Incentive Refund', 'row'),
    ('   Shipping Fee Subsidy', 'row'),
    ('   FBT Overall Merchant Subsidy', 'row'),  # New Jul 2026 — 8th component of Shipping parent
    ('   Customer Shipping Fee Offset', 'row'),
    ('   Customer-Paid Shipping Fee', 'row'),
    ('   Customer-Paid Shipping Refund', 'row'),
    # Seller Shipping Fee Discount removed 2026-06-30 — was double-counting the
    # seller portion already included in net Customer-Paid Shipping Fee.
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
    ('   Smart Promotion Fee', 'row'),  # New Jul 2026 — enabled Smart Promos in June
    ('   Smart Promotion Campaign Period Fee', 'row'),  # New Jul 2026
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
    ('G&A', 'section'),
    ('   Team Spend', 'row'),
    ('   Software & Tools', 'row'),
    ('   Other G&A', 'row'),
    ('   Chargebacks', 'row'),
    ('   Unclassified Adjustments', 'row'),
    ('TOTAL G&A', 'total'),
    ('', 'blank'),
    ('NET PROFIT', 'total'),
]
