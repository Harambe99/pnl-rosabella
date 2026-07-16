"""Ad Ledger v2 (2026-07-16):

  * Auto-classify Promotions-sheet loads by amount (>= tbsm_threshold => TBSM,
    < threshold => Free promo) instead of relying on per-date tag min_amount.
  * Two-pool FIFO: Promo pool drained before TBSM pool — matches TikTok's real
    behavior (promo credits applied before charging paid balance) and removes
    ordering artifacts from the earlier single-queue model.
  * Track separate TBSM Balance + Promo Balance columns on AdLedgerDay so the
    combined `closing_balance` isn't a black box.
  * Split default discount into two channels:
      - tbsm_default_discount   = 0.06  (Others/Increase balance — direct TBSM top-up)
      - agency_default_discount = 0.10  (large Promotions loads — agency-purchased)
    This preserves the historical rates for Jan/Feb/Mar 2026 Others loads
    while auto-classifying new agency-loaded credits at 10%.
"""
from decimal import Decimal
from django.db import migrations, models


def set_defaults(apps, schema_editor):
    """Backfill defaults on the existing singleton config.

    We're strictly ADDING information — the tbsm_default_discount stays at 6%
    (matches historical Others loads) and we add agency_default_discount at 10%
    for the newly auto-classified Promotions loads.
    """
    AdLedgerConfig = apps.get_model('core', 'AdLedgerConfig')
    cfg = AdLedgerConfig.objects.filter(pk=1).first()
    if cfg is None:
        return
    if not cfg.tbsm_threshold or cfg.tbsm_threshold == Decimal('0'):
        cfg.tbsm_threshold = Decimal('15000.00')
    if not cfg.agency_default_discount or cfg.agency_default_discount == Decimal('0'):
        cfg.agency_default_discount = Decimal('0.10')
    cfg.save()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_smart_promo_and_fbt_subsidy'),
    ]

    operations = [
        migrations.AddField(
            model_name='adledgerconfig',
            name='tbsm_threshold',
            field=models.DecimalField(
                max_digits=12, decimal_places=2, default=Decimal('15000.00'),
                help_text="Promotions-sheet loads at or above this daily total are classified "
                          "as TBSM (paid, discounted) instead of free promo credit. Default $15,000."),
        ),
        migrations.AddField(
            model_name='adledgerconfig',
            name='agency_default_discount',
            field=models.DecimalField(
                max_digits=5, decimal_places=4, default=Decimal('0.10'),
                help_text="Default discount for large Promotions-sheet loads (agency-purchased). "
                          "Applies to any Promotions daily-sum >= tbsm_threshold. Historical rate is 10%."),
        ),
        migrations.AlterField(
            model_name='adledgerconfig',
            name='tbsm_default_discount',
            field=models.DecimalField(
                max_digits=5, decimal_places=4, default=Decimal('0.06'),
                help_text="Default discount for Others / Increase balance loads (direct TBSM top-up). "
                          "Historical rate is 6%. Overridable per date via a Discount Override entry."),
        ),
        migrations.AddField(
            model_name='adledgerday',
            name='tbsm_balance',
            field=models.DecimalField(
                max_digits=12, decimal_places=2, default=0,
                help_text='Closing TBSM (paid, discounted) pool balance.'),
        ),
        migrations.AddField(
            model_name='adledgerday',
            name='promo_balance',
            field=models.DecimalField(
                max_digits=12, decimal_places=2, default=0,
                help_text='Closing Promo (free) pool balance.'),
        ),
        migrations.RunPython(set_defaults, noop_reverse),
    ]
