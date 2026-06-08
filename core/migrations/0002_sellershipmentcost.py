from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SellerShipmentCost',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('shipment_number', models.CharField(db_index=True, max_length=64, unique=True)),
                ('shipped_date', models.DateField(db_index=True)),
                ('postage', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('reference_number', models.CharField(blank=True, max_length=64)),
                ('carrier_service', models.CharField(blank=True, max_length=64)),
                ('tracking', models.CharField(blank=True, max_length=128)),
                ('channel_name', models.CharField(blank=True, max_length=64)),
                ('source_file', models.CharField(blank=True, max_length=255)),
                ('imported_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
