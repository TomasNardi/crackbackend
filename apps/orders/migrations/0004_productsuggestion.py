from django.db import migrations, models


def forwards_copy_suggestions(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    ProductSuggestion = apps.get_model("orders", "ProductSuggestion")

    for product in Product.objects.all():
        old_suggested = list(product.suggested_products.exclude(pk=product.pk).order_by("-created_at")[:3])
        if not old_suggested:
            continue

        config, _ = ProductSuggestion.objects.get_or_create(product=product)
        config.suggested_products.set(old_suggested)


def reverse_copy_suggestions(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    ProductSuggestion = apps.get_model("orders", "ProductSuggestion")

    for config in ProductSuggestion.objects.select_related("product").prefetch_related("suggested_products"):
        product = Product.objects.filter(pk=config.product_id).first()
        if not product:
            continue
        product.suggested_products.set(config.suggested_products.exclude(pk=product.pk).all()[:3])


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0003_add_order_code"),
        ("products", "0009_product_suggested_products"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductSuggestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Creado")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Actualizado")),
                ("product", models.OneToOneField(on_delete=models.CASCADE, related_name="suggestion_config", to="products.product", verbose_name="Producto")),
                ("suggested_products", models.ManyToManyField(blank=True, help_text="Elegí hasta 3 productos para el carrusel del detalle.", related_name="suggested_in_configs", to="products.product", verbose_name="Productos sugeridos")),
            ],
            options={
                "verbose_name": "Producto sugerido",
                "verbose_name_plural": "Productos sugeridos",
                "ordering": ["product__name"],
            },
        ),
        migrations.RunPython(forwards_copy_suggestions, reverse_copy_suggestions),
    ]
