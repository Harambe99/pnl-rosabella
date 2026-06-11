"""TikTok Ad Account FIFO reconciliation engine.

Ports the standalone reference_implementation.py into the Django app. Given:
  - AdTransaction rows (TBSM loads, promo grants, card charges)
  - AdSpendDay rows (daily ad spend)
  - AgencyPromoTag rows (which promo days are agency-purchased at what discount)
  - AdLedgerConfig (opening balance + default TBSM discount)

it rebuilds the AdLedgerDay snapshot for a date range using oldest-first FIFO
consumption of credit layers against daily spend.
"""
from collections import deque
from datetime import timedelta
from decimal import Decimal

from django.db import transaction

from .models import (
    AdTransaction, AdSpendDay, AgencyPromoTag,
    AdLedgerConfig, AdLedgerDay,
)


def _build_layers(start_date, end_date, config):
    """Return a sorted list of credit layer dicts: {date, amount, discount, source}."""
    tbsm_disc = float(config.tbsm_default_discount)
    layers = []

    # TBSM loads — every Others/Increase balance row carries the default TBSM discount.
    qs = AdTransaction.objects.filter(sheet='Others', txn_type__iexact='Increase balance')
    for t in qs:
        if t.amount <= 0:
            continue
        layers.append({
            'date': t.txn_time.date(),
            'amount': float(t.amount),
            'discount': tbsm_disc,
            'source': f'TBSM {int(round(tbsm_disc*100))}%',
        })

    # Promotions — net per day (Issued + Expired sums). Tag-table override picks agency days.
    tag_by_date = {t.date: t for t in AgencyPromoTag.objects.all()}
    by_day = {}
    for t in AdTransaction.objects.filter(sheet='Promotions'):
        d = t.txn_time.date()
        by_day[d] = by_day.get(d, Decimal('0')) + (t.amount or Decimal('0'))
    for d, amt in by_day.items():
        if amt <= 0:
            continue
        tag = tag_by_date.get(d)
        if tag and amt >= tag.min_amount:
            disc = float(tag.discount_pct)
            layers.append({
                'date': d, 'amount': float(amt), 'discount': disc,
                'source': f'Agency promo {int(round(disc*100))}%',
            })
        else:
            layers.append({
                'date': d, 'amount': float(amt), 'discount': 1.0,
                'source': 'Free promo',
            })

    layers.sort(key=lambda x: x['date'])
    return layers


def recompute_ledger(start_date, end_date):
    """Wipe AdLedgerDay rows in [start_date, end_date] and rebuild via FIFO.
    The engine walks from the earliest known date (opening / first txn / first spend)
    through end_date so the FIFO queue state at start_date reflects real pre-window
    activity. Only days within [start_date, end_date] are stored.
    Returns the number of days written."""
    config = AdLedgerConfig.objects.filter(pk=1).first()
    if config is None:
        config = AdLedgerConfig.objects.create(pk=1)

    layers = _build_layers(start_date, end_date, config)

    # Daily spend (across all of history, so pre-window draws happen too)
    spend_map = {s.date: float(s.cost) for s in AdSpendDay.objects.all()}

    # Determine walk-start: earliest of opening, first layer, first spend
    candidates = []
    if config.opening_date:
        candidates.append(config.opening_date)
    if layers:
        candidates.append(layers[0]['date'])
    if spend_map:
        candidates.append(min(spend_map.keys()))
    walk_start = min(candidates) if candidates else start_date

    # Per-day display sums (only for the storage window — pre-window is internal-only)
    tbsm_in_map, promo_in_map, card_map = {}, {}, {}
    for t in AdTransaction.objects.filter(txn_time__date__gte=start_date,
                                          txn_time__date__lte=end_date):
        d = t.txn_time.date()
        amt = float(t.amount or 0)
        if t.sheet == 'Others' and t.txn_type.lower() == 'increase balance':
            tbsm_in_map[d] = tbsm_in_map.get(d, 0) + amt
        elif t.sheet == 'Promotions':
            promo_in_map[d] = promo_in_map.get(d, 0) + amt
        elif t.sheet == 'Payments' and t.status.lower() == 'success':
            card_map[d] = card_map.get(d, 0) + amt

    # FIFO queue — seed with opening balance if applicable on/before walk_start.
    q = deque()
    if (config.opening_balance and config.opening_balance > 0
            and config.opening_date and config.opening_date <= walk_start):
        q.append([float(config.opening_balance), float(config.opening_discount),
                  f'TBSM {int(round(float(config.opening_discount)*100))}%'])

    # All layers walked in date order, including pre-window so they accumulate spend draws.
    layers_sorted = list(layers)  # already sorted by _build_layers
    li = 0

    rows = []
    cur = walk_start
    while cur <= end_date:
        # Promote any layers dated <= today into the queue
        while li < len(layers_sorted) and layers_sorted[li]['date'] <= cur:
            l = layers_sorted[li]
            q.append([l['amount'], l['discount'], l['source']])
            li += 1

        opening = sum(x[0] for x in q)
        s = spend_map.get(cur, 0)
        remaining = s
        funded = 0.0
        funded_cost = 0.0
        savings_tbsm = 0.0
        savings_promo = 0.0
        srcs = {}
        while remaining > 1e-9 and q:
            amt, disc, src = q[0]
            take = min(amt, remaining)
            q[0][0] -= take
            remaining -= take
            funded += take
            funded_cost += take * (1 - disc)
            srcs[src] = srcs.get(src, 0) + take
            # Split savings: free promos count fully against "TT Promo Credits";
            # any non-free discount (TBSM 6%, agency 10%) counts against "TBSM Savings".
            if disc >= 1.0 - 1e-9:
                savings_promo += take
            else:
                savings_tbsm += take * disc
            if q[0][0] <= 1e-9:
                q.popleft()

        full_price = remaining
        closing = sum(x[0] for x in q)
        actual_cost = funded_cost + full_price
        disc_on_funded = (1 - funded_cost / funded) if funded > 1e-9 else 0.0
        if funded <= 1e-9:
            source = 'Full price'
        elif len(srcs) == 1:
            source = next(iter(srcs))
        else:
            source = 'Mixed'
        eff_disc = (1 - actual_cost / s) if s > 0 else 0.0

        # Only persist days within the requested storage window
        if start_date <= cur <= end_date:
            rows.append(AdLedgerDay(
                date=cur,
                ad_spend=Decimal(str(round(s, 2))),
                tbsm_in=Decimal(str(round(tbsm_in_map.get(cur, 0), 2))),
                promo_in=Decimal(str(round(promo_in_map.get(cur, 0), 2))),
                card_charge=Decimal(str(round(card_map.get(cur, 0), 2))),
                opening_balance=Decimal(str(round(opening, 2))),
                closing_balance=Decimal(str(round(closing, 2))),
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
