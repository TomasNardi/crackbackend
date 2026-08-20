"""
Marca el estado de stock de las órdenes que ya existían.

Antes de las reservas, una orden en efectivo descontaba el stock apenas se
creaba y Mercado Pago recién al aprobarse el pago. Si estas quedaran en "sin
efecto", marcar como pagada una orden vieja en efectivo descontaría el stock una
segunda vez.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Order = apps.get_model("orders", "Order")

    # Efectivo: descontaba al crear la orden, en cualquier estado.
    # Mercado Pago: descontaba solo al quedar pagada.
    Order.objects.filter(payment_method="cash").update(stock_status="consumed")
    Order.objects.filter(payment_method="mercadopago", status="paid").update(
        stock_status="consumed"
    )


def unbackfill(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    Order.objects.update(stock_status="none")


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0015_order_stock_status_alter_order_shipping_method"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
