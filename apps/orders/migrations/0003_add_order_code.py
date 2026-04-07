import random
from django.db import migrations, models

_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _generate_code(existing: set) -> str:
    for _ in range(100):
        code = "".join(random.choices(_ALPHABET, k=6))
        if code not in existing:
            return code
    return "".join(random.choices(_ALPHABET, k=8))


def populate_order_codes(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    existing = set(
        Order.objects.exclude(order_code="").values_list("order_code", flat=True)
    )
    to_update = []
    for order in Order.objects.filter(order_code=""):
        code = _generate_code(existing)
        existing.add(code)
        order.order_code = code
        to_update.append(order)
    if to_update:
        Order.objects.bulk_update(to_update, ["order_code"])


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0002_alter_discountcode_activated_at_and_more'),
    ]

    operations = [
        # Paso 1: agregar campo sin unique (permite vacío temporal)
        migrations.AddField(
            model_name='order',
            name='order_code',
            field=models.CharField(
                blank=True, db_index=False,
                help_text='Generado automáticamente. Usado como external_reference en MercadoPago.',
                max_length=8, unique=False, verbose_name='Código de orden',
                default='',
            ),
        ),
        # Paso 2: rellenar filas existentes con código único
        migrations.RunPython(populate_order_codes, migrations.RunPython.noop),
        # Paso 3: agregar el unique constraint ahora que no hay duplicados
        migrations.AlterField(
            model_name='order',
            name='order_code',
            field=models.CharField(
                blank=True, db_index=True, unique=True,
                help_text='Generado automáticamente. Usado como external_reference en MercadoPago.',
                max_length=8, verbose_name='Código de orden',
            ),
        ),
    ]
