from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


def backfill_product_images(apps, schema_editor):
    Product = apps.get_model("products", "Product")
    ProductImage = apps.get_model("products", "ProductImage")

    for product in Product.objects.all().iterator(chunk_size=200):
        if ProductImage.objects.filter(product=product).exists():
            continue

        urls = [product.image_url, product.image_url_2, product.image_url_3]
        valid_urls = [url for url in urls if url]
        for index, url in enumerate(valid_urls[:3]):
            ProductImage.objects.create(
                product=product,
                draft_token="",
                secure_url=url,
                public_id="",
                source="url",
                order_index=index,
                status="confirmed",
                metadata={"migrated_from_legacy_fields": True},
            )


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0009_product_suggested_products"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProductImageWebhookEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(choices=[("upload", "Upload"), ("delete", "Delete"), ("eager", "Eager"), ("other", "Other")], default="other", max_length=30, verbose_name="Evento")),
                ("public_id", models.CharField(blank=True, db_index=True, max_length=255, verbose_name="Public ID")),
                ("payload", models.JSONField(default=dict, verbose_name="Payload")),
                ("is_valid_signature", models.BooleanField(default=False, verbose_name="Firma válida")),
                ("processed", models.BooleanField(default=False, verbose_name="Procesado")),
                ("error", models.TextField(blank=True, verbose_name="Error")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Creado")),
                ("processed_at", models.DateTimeField(blank=True, null=True, verbose_name="Procesado en")),
            ],
            options={
                "verbose_name": "Webhook de imagen",
                "verbose_name_plural": "Webhooks de imágenes",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ProductImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("draft_token", models.CharField(blank=True, db_index=True, help_text="Permite persistir imágenes antes de guardar el producto.", max_length=64, verbose_name="Draft token")),
                ("secure_url", models.URLField(max_length=800, verbose_name="Secure URL")),
                ("public_id", models.CharField(blank=True, db_index=True, max_length=255, verbose_name="Public ID")),
                ("source", models.CharField(choices=[("cloudinary", "Cloudinary"), ("url", "URL externa")], default="cloudinary", max_length=20, verbose_name="Origen")),
                ("order_index", models.PositiveSmallIntegerField(default=0, verbose_name="Orden")),
                ("width", models.PositiveIntegerField(blank=True, null=True, verbose_name="Ancho")),
                ("height", models.PositiveIntegerField(blank=True, null=True, verbose_name="Alto")),
                ("bytes", models.PositiveIntegerField(blank=True, null=True, verbose_name="Bytes")),
                ("format", models.CharField(blank=True, max_length=20, verbose_name="Formato")),
                ("status", models.CharField(choices=[("pending", "Pendiente"), ("uploaded", "Subida"), ("confirmed", "Confirmada"), ("failed", "Fallida")], default="pending", max_length=20, verbose_name="Estado")),
                ("metadata", models.JSONField(blank=True, default=dict, verbose_name="Metadata")),
                ("upload_error", models.TextField(blank=True, verbose_name="Error de upload")),
                ("uploaded_at", models.DateTimeField(auto_now_add=True, verbose_name="Subido")),
                ("confirmed_at", models.DateTimeField(blank=True, null=True, verbose_name="Confirmado")),
                ("product", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="images", to="products.product", verbose_name="Producto")),
            ],
            options={
                "verbose_name": "Imagen de producto",
                "verbose_name_plural": "Imágenes de producto",
                "ordering": ["order_index", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="productimage",
            constraint=models.CheckConstraint(condition=Q(order_index__gte=0) & Q(order_index__lte=2), name="products_img_order_between_0_2"),
        ),
        migrations.AddConstraint(
            model_name="productimage",
            constraint=models.CheckConstraint(condition=Q(product__isnull=False) | ~Q(draft_token=""), name="products_img_requires_product_or_draft"),
        ),
        migrations.AddConstraint(
            model_name="productimage",
            constraint=models.UniqueConstraint(condition=Q(product__isnull=False), fields=("product", "order_index"), name="products_img_unique_order_per_product"),
        ),
        migrations.RunPython(backfill_product_images, reverse_code=noop_reverse),
    ]
