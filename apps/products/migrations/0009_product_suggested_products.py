from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0008_alter_cardcondition_abbreviation_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="suggested_products",
            field=models.ManyToManyField(
                blank=True,
                help_text="Seleccionar hasta 3 productos sugeridos para el carrusel del detalle.",
                related_name="suggested_in",
                symmetrical=False,
                to="products.product",
                verbose_name="Productos sugeridos",
            ),
        ),
    ]
