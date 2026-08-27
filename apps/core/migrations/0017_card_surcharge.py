from decimal import Decimal

from django.db import migrations, models


DEFAULT_SURCHARGE_PERCENT = Decimal("10.00")


def set_default_surcharge(apps, schema_editor):
    """El valor viejo era un % de descuento por efectivo: ya no aplica."""
    SiteConfig = apps.get_model("core", "SiteConfig")
    SiteConfig.objects.all().update(
        card_surcharge_enabled=True,
        card_surcharge_percent=DEFAULT_SURCHARGE_PERCENT,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_contactmessage_read_audit_fields"),
    ]

    operations = [
        migrations.RenameField(
            model_name="siteconfig",
            old_name="cash_discount_enabled",
            new_name="card_surcharge_enabled",
        ),
        migrations.RenameField(
            model_name="siteconfig",
            old_name="cash_discount_percent",
            new_name="card_surcharge_percent",
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="card_surcharge_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Aplica el recargo cuando el cliente elige pagar con Mercado Pago / tarjeta de crédito.",
                verbose_name="Recargo Mercado Pago activo",
            ),
        ),
        migrations.AlterField(
            model_name="siteconfig",
            name="card_surcharge_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=10,
                help_text="Porcentaje de recargo sobre los productos (no sobre el envío) al pagar con Mercado Pago / tarjeta.",
                max_digits=5,
                verbose_name="% recargo Mercado Pago",
            ),
        ),
        migrations.AlterModelOptions(
            name="paymentsettings",
            options={
                "verbose_name": "Recargo Mercado Pago",
                "verbose_name_plural": "Recargo Mercado Pago",
            },
        ),
        migrations.RunPython(set_default_surcharge, migrations.RunPython.noop),
    ]
