"""Add AdSpendDayAudit — tracks manual edits to AdSpendDay from the new
Ad Spend Input page. Mirrors MonthlyInputAudit exactly, but with a DateField
instead of a YYYY-MM CharField.

Used when TikTok's Campaign Overview export is unavailable / broken and the
user needs to enter ad spend manually per day. Every manual save writes an
audit row so we always have a full trail of what changed when.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_prizes_giveaways'),
    ]

    operations = [
        migrations.CreateModel(
            name='AdSpendDayAudit',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(db_index=True)),
                ('field_name', models.CharField(max_length=64)),
                ('old_value', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('new_value', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('changed_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                'ordering': ['-changed_at'],
            },
        ),
    ]
