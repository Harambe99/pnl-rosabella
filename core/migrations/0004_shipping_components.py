from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_monthlyinputaudit'),
    ]

    operations = [
        migrations.AddField(
            model_name='settlementrow',
            name='tt_shop_shipping_incentive',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='settlementrow',
            name='shipping_fee_subsidy',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='settlementrow',
            name='customer_shipping_fee_offset',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='settlementrow',
            name='customer_paid_shipping_fee',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
        migrations.AddField(
            model_name='settlementrow',
            name='customer_paid_shipping_refund',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=12),
        ),
    ]
