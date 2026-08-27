from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0016_backfill_order_stock_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="card_surcharge_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                verbose_name="% recargo MP aplicado",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="card_surcharge_amount",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10,
                verbose_name="Monto recargo MP",
            ),
        ),
    ]
