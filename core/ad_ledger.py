"""TikTok Ad Account FIFO reconciliation engine — v2 (2026-07-16).

v2 changes:
  1. Auto-classify Promotions rows by daily-summed amount:
       daily sum >= tbsm_threshold  -> TBSM layer  (discount from per-date override or default)
       daily sum <  tbsm_threshold  -> Free promo layer (100% off)
  2. Two-pool FIFO: Promo pool consumed FIRST, then TBSM pool. Matches TT's real
     behavior (promo credits automatically apply before charging paid balance)
     and eliminates load-ordering artifacts from the earlier single-queue model.
  3. Track separate TBSM Balance + Promo Balance closing values per day so the
     combined balance isn't a black box.

Inputs (unchanged):
  - AdTransaction rows (Others/Increase balance = TBSM loads; Promotions = mixed
    TBSM+promo classified by amount; Payments = card charges for display only)
  - AdSpendDay rows (daily ad spend that draws down credit layers)
  - AgencyPromoTag rows (per-date discount override for TBSM loads — legacy min_amount
    field is IGNORED; auto-classification handles the threshold)
  - AdLedgerConfig (opening balance/date, default TBSM discount, TBSM threshold)
"""
from collections import deque
from datetime import timedelta
from decimal import Decimal

from django.db import transaction

from .models import (
    AdTransaction, AdSpendDay, AgencyPromoTag,
    AdLedgerConfig, AdLedgerDay,
)


def _build_layers(config):
    """Return date-sorted list of credit-layer dicts:
      {date, amount, discount, source, type}   type ∈ {'tbsm', 'promo'}

    Two distinct default discount rates apply, since Others (direct TBSM top-up)
    and large Promotions loads (agency-purchased) historically ran at different rates:
      - Others / Increase balance      -> tbsm_default_discount   (default 6%)
      - Promotions daily-sum >= thres  -> agency_default_discount (default 10%)
    Both channels can be overridden per-date via an AgencyPromoTag row.
    """
    threshold = float(config.tbsm_threshold or 0)
    tbsm_disc_default = float(config.tbsm_default_discount)
    agency_disc_default = float(config.agency_default_discount)
    override_by_date = {t.date: t for t in AgencyPromoTag.objects.all()}
    layers = []

    # 1. Others / Increase balance -> always TBSM at direct-TBSM rate
    for t in AdTransaction.objects.filter(sheet='Others', txn_type__iexact='Increase balance'):
        if t.amount <= 0:
            continue
        d = t.txn_time.date()
        override = override_by_date.get(d)
        disc = float(override.discount_pct) if override else tbsm_disc_default
        layers.append({
            'date': d, 'amount': float(t.amount), 'discount': disc,
            'source': f'TBSM {int(round(disc*100))}%', 'type': 'tbsm',
        })

    # 2. Promotions — sum per day, auto-classify by threshold.
    #    Large loads use the agency default rate (10%) since they're agency-purchased.
    promo_by_day = {}
    for t in AdTransaction.objects.filter(sheet='Promotions'):
        d = t.txn_time.date()
        promo_by_day[d] = promo_by_day.get(d, Decimal('0')) + (t.amount or Decimal('0'))
    for d, amt in promo_by_day.items():
        if amt <= 0:
            continue
        amt_f = float(amt)
        if amt_f >= threshold:
            override = override_by_date.get(d)
            disc = float(override.discount_pct) if override else agency_disc_default
            layers.append({
                'date': d, 'amount': amt_f, 'discount': disc,
                'source': f'TBSM {int(round(disc*100))}%', 'type': 'tbsm',
            })
        else:
            layers.append({
                'date': d, 'amount': amt_f, 'discount': 1.0,
                'source': 'Free promo', 'type': 'promo',
            })

    layers.sort(key=lambda x: x['date'])
    return layers


def recompute_ledger(start_date, end_date):
    """Wipe AdLedgerDay rows in [start_date, end_date] and rebuild via two-pool FIFO.

    Draw order per day:
      1. Promo pool (oldest-first)  — free credits from TikTok
      2. TBSM pool (oldest-first)   — paid loads at discount
      3. Any remainder             — full-price card charge

    Walks from earliest known event (opening date / first layer / first spend)
    so the pool state at start_date reflects real pre-window activity. Only
    days within [start_date, end_date] are persisted.
    """
    config = AdLedgerConfig.objects.filter(pk=1).first()
    if config is None:
        config = AdLedgerConfig.objects.create(pk=1)

    layers = _build_layers(config)
    spend_map = {s.date: float(s.cost) for s in AdSpendDay.objects.all()}

    candidates = []
    if config.opening_date:
        candidates.append(config.opening_date)
    if layers:
        candidates.append(layers[0]['date'])
    if spend_map:
        candidates.append(min(spend_map.keys()))
    walk_start = min(candidates) if candidates else start_date

    threshold = float(config.tbsm_threshold or 0)

    # Per-day display sums for the storage window.
    # Promotions rows are routed to TBSM In vs Promo In by the same threshold
    # that classifies their FIFO layer, so display and math stay consistent.
    promo_by_day_window = {}
    for t in AdTransaction.objects.filter(sheet='Promotions',
                                          txn_time__date__gte=start_date,
                                          txn_time__date__lte=end_date):
        d = t.txn_time.date()
        promo_by_day_window[d] = promo_by_day_window.get(d, 0) + float(t.amount or 0)

    tbsm_in_map, promo_in_map, card_map = {}, {}, {}
    for t in AdTransaction.objects.filter(txn_time__date__gte=start_date,
                                          txn_time__date__lte=end_date):
        d = t.txn_time.date()
        amt = float(t.amount or 0)
        if t.sheet == 'Others' and t.txn_type.lower() == 'increase balance':
            tbsm_in_map[d] = tbsm_in_map.get(d, 0) + amt
        elif t.sheet == 'Promotions':
            daily = promo_by_day_window.get(d, 0)
            if daily >= threshold:
                tbsm_in_map[d] = tbsm_in_map.get(d, 0) + amt
            else:
                promo_in_map[d] = promo_in_map.get(d, 0) + amt
        elif t.sheet == 'Payments' and t.status.lower() == 'success':
            card_map[d] = card_map.get(d, 0) + amt

    # Two FIFO queues, seeded independently
    tbsm_q = deque()
    promo_q = deque()

    if (config.opening_balance and config.opening_balance > 0
            and config.opening_date and config.opening_date <= walk_start):
        tbsm_q.append([float(config.opening_balance), float(config.opening_discount),
                       f'TBSM {int(round(float(config.opening_discount)*100))}%'])

    layers_sorted = list(layers)
    li = 0

    rows = []
    cur = walk_start
    while cur <= end_date:
        # Promote layers dated <= cur into the correct queue
        while li < len(layers_sorted) and layers_sorted[li]['date'] <= cur:
            l = layers_sorted[li]
            item = [l['amount'], l['discount'], l['source']]
            if l['type'] == 'promo':
                promo_q.append(item)
            else:
                tbsm_q.append(item)
            li += 1

        tbsm_open = sum(x[0] for x in tbsm_q)
        promo_open = sum(x[0] for x in promo_q)
        opening = tbsm_open + promo_open

        s = spend_map.get(cur, 0)
        remaining = s
        funded = 0.0
        funded_cost = 0.0
        savings_tbsm = 0.0
        savings_promo = 0.0
        srcs = {}

        # 1. Promo pool first (matches TT priority + user's mental model)
        while remaining > 1e-9 and promo_q:
            amt, disc, src = promo_q[0]
            take = min(amt, remaining)
            promo_q[0][0] -= take
            remaining -= take
            funded += take
            funded_cost += take * (1 - disc)
            srcs[src] = srcs.get(src, 0) + take
            if disc >= 1.0 - 1e-9:
                savings_promo += take
            else:
                savings_tbsm += take * disc
            if promo_q[0][0] <= 1e-9:
                promo_q.popleft()

        # 2. TBSM pool second
        while remaining > 1e-9 and tbsm_q:
            amt, disc, src = tbsm_q[0]
            take = min(amt, remaining)
            tbsm_q[0][0] -= take
            remaining -= take
            funded += take
            funded_cost += take * (1 - disc)
            srcs[src] = srcs.get(src, 0) + take
            if disc >= 1.0 - 1e-9:
                savings_promo += take
            else:
                savings_tbsm += take * disc
            if tbsm_q[0][0] <= 1e-9:
                tbsm_q.popleft()

        full_price = remaining
        tbsm_close = sum(x[0] for x in tbsm_q)
        promo_close = sum(x[0] for x in promo_q)
        closing = tbsm_close + promo_close
        actual_cost = funded_cost + full_price
        disc_on_funded = (1 - funded_cost / funded) if funded > 1e-9 else 0.0

        if funded <= 1e-9:
            source = 'Full price'
        elif len(srcs) == 1:
            source = next(iter(srcs))
        else:
            source = 'Mixed'
        eff_disc = (1 - actual_cost / s) if s > 0 else 0.0

        if start_date <= cur <= end_date:
            rows.append(AdLedgerDay(
                date=cur,
                ad_spend=Decimal(str(round(s, 2))),
                tbsm_in=Decimal(str(round(tbsm_in_map.get(cur, 0), 2))),
                promo_in=Decimal(str(round(promo_in_map.get(cur, 0), 2))),
                card_charge=Decimal(str(round(card_map.get(cur, 0), 2))),
                opening_balance=Decimal(str(round(opening, 2))),
                closing_balance=Decimal(str(round(closing, 2))),
                tbsm_balance=Decimal(str(round(tbsm_close, 2))),
                promo_balance=Decimal(str(round(promo_close, 2))),
                funded=Decimal(str(round(funded, 2))),
                full_price=Decimal(str(round(full_price, 2))),
                savings_tbsm=Decimal(str(round(savings_tbsm, 2))),
                savings_promo=Decimal(str(round(savings_promo, 2))),
                actual_cost=Decimal(str(round(actual_cost, 2))),
                funding_source=source,
                discount_on_funded=Decimal(str(round(disc_on_funded, 4))),
                effective_discount=Decimal(str(round(eff_disc, 4))),
            ))
        cur += timedelta(days=1)

    with transaction.atomic():
        AdLedgerDay.objects.filter(date__gte=start_date, date__lte=end_date).delete()
        AdLedgerDay.objects.bulk_create(rows, batch_size=500)
    return len(rows)
