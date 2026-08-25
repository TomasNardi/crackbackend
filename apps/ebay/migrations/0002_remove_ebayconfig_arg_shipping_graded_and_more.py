"""
El envío a Argentina pasa a ser un valor único.

El owner cobra lo mismo sin importar qué se traiga —carta suelta, calificada o
producto sellado—, así que las dos tarifas se funden en una y el tipo de ítem
desaparece del pedido.

El valor nuevo se inicializa con el de "graded", que era el más alto: si la
migración corre sobre una config ya tocada por el owner, es preferible quedar
cotizando de más (visible, y se corrige en el admin) que de menos.
"""

from decimal import Decimal

from django.db import migrations, models


def carry_over_shipping(apps, schema_editor):
    EbayConfig = apps.get_model("ebay", "EbayConfig")
    for config in EbayConfig.objects.all():
        config.arg_shipping = config.arg_shipping_graded
        config.save(update_fields=["arg_shipping"])


def restore_shipping(apps, schema_editor):
    """Al revertir, el valor único vuelve a las dos tarifas."""
    EbayConfig = apps.get_model("ebay", "EbayConfig")
    for config in EbayConfig.objects.all():
        config.arg_shipping_raw = config.arg_shipping
        config.arg_shipping_graded = config.arg_shipping
        config.save(update_fields=["arg_shipping_raw", "arg_shipping_graded"])


class Migration(migrations.Migration):

    dependencies = [
        ('ebay', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='ebayconfig',
            name='arg_shipping',
            field=models.DecimalField(decimal_places=2, default=Decimal('20'), help_text='Costo de traer una unidad desde el courier en EE.UU. Es único: aplica igual a cartas sueltas, calificadas y productos sellados.', max_digits=10, verbose_name='Envío a Argentina (USD)'),
        ),
        # Va entre el AddField y los RemoveField: necesita las tres columnas vivas.
        migrations.RunPython(carry_over_shipping, restore_shipping),
        migrations.RemoveField(
            model_name='ebayconfig',
            name='arg_shipping_graded',
        ),
        migrations.RemoveField(
            model_name='ebayconfig',
            name='arg_shipping_raw',
        ),
        migrations.RemoveField(
            model_name='ebayorderitem',
            name='item_type',
        ),
    ]
