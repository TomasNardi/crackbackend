"""
Las órdenes de pago manual pasan de "cash" a "transfer".

El método era uno solo con tres nombres ("Efectivo / Transferencia / Crypto") y
quedó en transferencia sola, que es la única que deja rastro: el comprobante.
Las órdenes viejas se cobraron por alguna de las tres, pero todas por fuera de
Mercado Pago, así que caen en el mismo casillero y el admin las sigue mostrando
igual. Mover el valor evita tener que arrastrar "cash" en cada consulta.
"""

from django.db import migrations


def cash_a_transferencia(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(payment_method="cash").update(payment_method="transfer")


def transferencia_a_cash(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.filter(payment_method="transfer").update(payment_method="cash")


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0019_order_receipt_content_type_order_receipt_key_and_more"),
    ]

    operations = [
        migrations.RunPython(cash_a_transferencia, transferencia_a_cash),
    ]
