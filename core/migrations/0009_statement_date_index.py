"""Add db_index + composite (row_type, statement_date) index to SettlementRow.

Required for the settlement-date P&L attribution methodology (2026-06-25
change per Lindsay/Jack). compute_daily_pnl filters and groups SettlementRow
by statement_date heavily; without an index those queries become a full scan
on every dashboard / export load.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_seller_shipping_order_date'),
    ]

    operations = [
        migrations.AlterField(
            model_name='settlementrow',
            name='statement_date',
            field=models.DateField(db_index=True, null=True),
        ),
        migrations.AddIndex(
            model_name='settlementrow',
            index=models.Index(fields=['row_type', 'statement_date'],
                               name='core_settlementr_rt_stmt_idx'),
        ),
    ]
