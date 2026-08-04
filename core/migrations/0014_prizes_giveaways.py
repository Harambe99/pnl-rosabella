"""Add Prizes & Giveaways manual monthly input.

New Marketing line item on the P&L, driven by a MonthlyInput value.
Historical months default to $0 until the user backfills.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_ad_ledger_v2'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlyinput',
            name='prizes_giveaways',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
