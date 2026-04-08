from django.db import migrations, models


def forward_to_singleton(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    ProductSuggestion = apps.get_model("orders", "ProductSuggestion")
    SuggestedProductsCarousel = apps.get_model("orders", "SuggestedProductsCarousel")

    selected = []
    seen = set()

    for row in ProductSuggestion.objects.order_by("-updated_at"):
        for p in row.suggested_products.exclude(in_stock=False).order_by("-created_at"):
            if p.pk not in seen:
                seen.add(p.pk)
                selected.append(p)
            if len(selected) == 3:
                break
        if len(selected) == 3:
            break

    if len(selected) < 3:
        for p in Product.objects.exclude(in_stock=False).order_by("-created_at"):
            if p.pk not in seen:
                seen.add(p.pk)
                selected.append(p)
            if len(selected) == 3:
                break

    singleton, _ = SuggestedProductsCarousel.objects.get_or_create(pk=1)
    singleton.suggested_products.set(selected[:3])


def reverse_from_singleton(apps, schema_editor):
    ProductSuggestion = apps.get_model("orders", "ProductSuggestion")
    SuggestedProductsCarousel = apps.get_model("orders", "SuggestedProductsCarousel")

    singleton = SuggestedProductsCarousel.objects.first()
    if not singleton:
        return

    first_product = singleton.suggested_products.first()
    if not first_product:
        return

    row, _ = ProductSuggestion.objects.get_or_create(product=first_product)
    row.suggested_products.set(singleton.suggested_products.all()[:3])


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0004_productsuggestion"),
    ]

    operations = [
        migrations.CreateModel(
            name="SuggestedProductsCarousel",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Creado")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Actualizado")),
                ("suggested_products", models.ManyToManyField(blank=True, help_text="Elegí hasta 3 productos para el carrusel del detalle.", related_name="carousel_suggested_in", to="products.product", verbose_name="Productos sugeridos")),
            ],
            options={
                "verbose_name": "Carrusel de sugeridos",
                "verbose_name_plural": "Productos sugeridos",
                "ordering": ["id"],
            },
        ),
        migrations.RunPython(forward_to_singleton, reverse_from_singleton),
        migrations.DeleteModel(
            name="ProductSuggestion",
        ),
    ]
