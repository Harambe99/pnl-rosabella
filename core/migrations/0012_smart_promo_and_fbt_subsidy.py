"""Add 3 new SettlementRow fields for July 2026 TikTok Settlement columns.

TikTok added new sub-components to the Shipping and Fees parent aggregates.
Our current P&L doesn't capture them, causing our sum of Shipping/Fees
sub-components to diverge from TikTok's aggregate:

  Shipping parent  (TikTok Reports):  -$115,242.86
  Our 7 sub-components:               -$117,604.59
  Missing:                            +$2,361.73  = FBT overall merchant subsidy

  Fees aggregate   (TikTok Reports):  -$160,847.42
  Our fee sub-components:             -$145,330.53
  Missing:                            -$15,516.89 = Smart Promo fee (-$13,080)
                                                   + Smart Promo campaign fee (-$2,437)

These fees only fire when Smart Promotions is enabled (opted-in June 2026).
FBT overall merchant subsidy started firing June 2026 as well.

Historical months: all 3 fields will be $0 for pre-June statement rows.
Re-uploading Settlement files covering June+ will populate them.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_tt_shop_shipping_incentive_refund'),
    ]

    operations = [
        migrations.AddField(
            model_name='settlementrow',
            name='smart_promo_fee',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='settlementrow',
            name='smart_promo_campaign_period_fee',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='settlementrow',
            name='fbt_overall_merchant_subsidy',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
