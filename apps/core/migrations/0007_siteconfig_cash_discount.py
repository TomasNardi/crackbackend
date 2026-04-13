from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_alter_contactmessage_created_at_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="siteconfig",
            name="cash_discount_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Aplica descuento cuando el cliente elige pagar en efectivo.",
                verbose_name="Descuento por efectivo activo",
            ),
        ),
        migrations.AddField(
            model_name="siteconfig",
            name="cash_discount_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=15,
                help_text="Porcentaje de descuento para pago en efectivo.",
                max_digits=5,
                verbose_name="% descuento efectivo",
            ),
        ),
    ]
