"""Add FBTBillingSchedule model — maps services period → statement_date.

Populated by uploading the 'Payment Cycle' XLSX from TikTok Seller Center.
Used by the aggregator to attribute the 12 monthly FBT detail lines (Hub
Placement, Storage, Inbound Incidents, Routing Non-Compliance, etc.) to the
correct destination month (settlement-date basis) — per Lindsay 2026-06-26.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_statement_date_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='FBTBillingSchedule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('period', models.CharField(db_index=True, max_length=7,
                                            help_text='Services month in YYYY-MM format (e.g. "2026-04")')),
                ('statement_date', models.DateField(db_index=True,
                                                    help_text='Day TikTok actually charged this period')),
                ('amount', models.DecimalField(decimal_places=2, default=0, max_digits=12,
                                               help_text='Total $ TikTok billed (Settled column on Payment Cycle file)')),
                ('status', models.CharField(blank=True, max_length=32)),
                ('source_file', models.CharField(blank=True, max_length=255)),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['statement_date'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='fbtbillingschedule',
            unique_together={('period', 'statement_date')},
        ),
        migrations.AddIndex(
            model_name='fbtbillingschedule',
            index=models.Index(fields=['period'], name='core_fbtbill_period_idx'),
        ),
        migrations.AddIndex(
            model_name='fbtbillingschedule',
            index=models.Index(fields=['statement_date'], name='core_fbtbill_stmt_idx'),
        ),
    ]
