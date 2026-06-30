"""Add tt_shop_shipping_incentive_refund field to SettlementRow.

Per Jack 2026-06-30: TikTok's "TikTok Shop shipping incentive refund" column
clawbacks the original shipping incentive credit. We were missing this from
the P&L. Adding it as a separate line — pairs with TT Shop Shipping Incentive
the way Customer-Paid Shipping Refund pairs with Customer-Paid Shipping Fee.

NOTE: Existing SettlementRow rows default to 0 — they won't reflect the
historical refund values until Settlement files are re-uploaded so the
importer populates the new field.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_fbt_billing_schedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='settlementrow',
            name='tt_shop_shipping_incentive_refund',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
