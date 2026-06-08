from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_sellershipmentcost'),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyInputAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('month', models.CharField(db_index=True, max_length=7)),
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
