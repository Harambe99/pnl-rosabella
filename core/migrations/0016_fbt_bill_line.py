"""Add FBTBillLine — itemised breakdown of the FBT Warehouse Service Fee.

HAND-WRITTEN, deliberately additive-only.

`makemigrations` also wants to emit 7 unrelated operations (3 RenameIndex,
3 AlterField id/decimal, 1 AddIndex) that are pre-existing drift between
models.py and the migration history — they are present on clean prod code at
tag `pre-wsf-breakdown` and have nothing to do with this feature. They are
excluded on purpose: the RenameIndex operations would fail the Render release
phase if prod's index names differ from what Django expects, taking the whole
deploy down. This migration only creates one new table, so it cannot affect
any existing data or query path.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_ad_spend_day_audit'),
    ]

    operations = [
        migrations.CreateModel(
            name='FBTBillLine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('billing_period', models.CharField(
                    db_index=True, max_length=7,
                    help_text='Billing month in YYYY-MM format (e.g. "2026-08") — parsed from the file')),
                ('placement_period', models.CharField(
                    blank=True, max_length=7,
                    help_text='Order placement month in YYYY-MM. Blank when the file has no value.')),
                ('entry_type', models.CharField(
                    blank=True, max_length=32, help_text='"Payment" or "Adjustment"')),
                ('business_type', models.CharField(
                    max_length=128,
                    help_text='Fee name verbatim from the Bill, e.g. "Inbound Domestic Delivery Fee"')),
                ('amount', models.DecimalField(
                    decimal_places=2, default=0, max_digits=12,
                    help_text='Positive magnitude as printed on the bill')),
                ('qty', models.IntegerField(blank=True, null=True)),
                ('source_file', models.CharField(blank=True, max_length=255)),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['billing_period', '-amount'],
            },
        ),
        migrations.AddIndex(
            model_name='fbtbillline',
            index=models.Index(fields=['billing_period'],
                               name='core_fbtbil_billing_256809_idx'),
        ),
        migrations.AlterUniqueTogether(
            name='fbtbillline',
            unique_together={('billing_period', 'placement_period',
                              'entry_type', 'business_type')},
        ),
    ]
