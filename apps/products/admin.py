import json

from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import path
from unfold.admin import ModelAdmin
from . import bulk_load
from . import merge_duplicates_views  # TEMPORAL: se va con las rutas de duplicados
from .forms import ProductAdminForm
from .models import (
    TCG,
    ProductCategory,
    CardCondition,
    CertificationEntity,
    CertificationGrade,
    Product,
    ProductImage,
    ProductImageWebhookEvent,
)
from .services.cloudinary_service import CloudinaryValidationError, sync_product_gallery


@admin.register(TCG)
class TCGAdmin(ModelAdmin):
    list_display = ("name",)
    readonly_fields = ("slug",)
    exclude = ("slug",)


@admin.register(ProductCategory)
class ProductCategoryAdmin(ModelAdmin):
    list_display = ("name",)
    readonly_fields = ("slug",)
    exclude = ("slug",)


@admin.register(CardCondition)
class CardConditionAdmin(ModelAdmin):
    list_display = ("name", "abbreviation")


@admin.register(CertificationEntity)
class CertificationEntityAdmin(ModelAdmin):
    list_display = ("name", "abbreviation")


@admin.register(CertificationGrade)
class CertificationGradeAdmin(ModelAdmin):
    list_display = ("grade",)


@admin.register(Product)
class ProductAdmin(ModelAdmin):
    form = ProductAdminForm
    list_display = (
        "name", "category", "tcg",
        "price_usd", "price_ars_display", "discount_percent",
        "stock_quantity", "reserved_display", "in_stock",
    )
    list_filter = ("category", "tcg", "in_stock", "certification_entity")
    search_fields = ("name", "description")
    # `reserved_quantity` lo maneja el flujo de órdenes: tocarlo a mano
    # descuadraría las reservas vivas.
    readonly_fields = ("slug", "price_ars_display", "reserved_quantity")
    # El stock se edita desde el listado: vendiste una en mano, bajás el número
    # y listo, sin abrir la ficha ni tocar la publicación.
    list_editable = ("stock_quantity", "in_stock", "discount_percent")

    @admin.display(description="Reservado")
    def reserved_display(self, obj):
        """Unidades apartadas por órdenes de pago manual todavía sin cobrar."""
        if not obj.reserved_quantity:
            return "—"
        return f"{obj.reserved_quantity} apartadas"

    def price_ars_display(self, obj):
        if not obj.pk or not obj.price_usd:
            return "—"
        return f"${obj.price_ars:,.0f}"
    price_ars_display.short_description = "Precio ARS"

    autocomplete_fields = ("catalog_card",)

    fieldsets = (
        ("Carta del catálogo", {
            "fields": ("catalog_card",),
            "description": (
                "Buscá la carta por nombre, número o set —por ejemplo <code>charizard 4/102</code>— "
                "y se completan solos el nombre, el TCG y la imagen. "
                "Para sellados y accesorios, dejalo vacío."
            ),
        }),
        ("Identificación", {
            "fields": ("name", "description", "tcg", "category"),
        }),
        ("Precio y stock", {
            "fields": ("price_usd", "price_ars_display", "discount_percent", "stock_quantity", "reserved_quantity", "in_stock"),
        }),
        ("Imágenes", {
            "fields": ("cloudinary_draft_token", "images_payload", "image_url", "image_url_2", "image_url_3"),
        }),
        # --- Campos condicionales (JS los muestra/oculta según categoría) ---
        ("Singles — Condición", {
            "fields": ("condition",),
            "classes": ("fieldset-singles",),
        }),
        ("Slabs — Certificación", {
            "fields": ("certification_entity", "certification_grade"),
            "classes": ("fieldset-slabs",),
        }),
        ("Referencias externas (Opcional)", {
            "fields": ("pricecharting_url",),
        }),
    )

    # Le agrega el botón "Carga de stock" arriba del listado de productos.
    change_list_template = "admin/products/product/change_list.html"

    def get_urls(self):
        custom_urls = [
            path(
                "carga-stock/",
                self.admin_site.admin_view(self.bulk_load_view),
                name="products_product_bulk_load",
            ),
            path(
                "carga-stock/buscar/",
                self.admin_site.admin_view(bulk_load.search_view),
                name="products_product_bulk_search",
            ),
            path(
                "carga-stock/guardar/",
                self.admin_site.admin_view(bulk_load.save_view),
                name="products_product_bulk_save",
            ),
            # TEMPORAL: junta los duplicados que dejó el criterio viejo (una
            # publicación por copia). Borrar esta ruta y el módulo cuando esté.
            path(
                "duplicados/",
                self.admin_site.admin_view(merge_duplicates_views.merge_view),
                name="products_product_merge_duplicates",
            ),
        ]
        return custom_urls + super().get_urls()

    def bulk_load_view(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied
        return bulk_load.page_view(self, request)

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm("products.delete_product")

    def save_model(self, request, obj, form, change):
        self._ensure_catalog_image(request, obj)
        super().save_model(request, obj, form, change)

        cleaned_data = getattr(form, "cleaned_data", {}) or {}
        # Sin el campo no hubo uploader en juego: guardar el stock desde el
        # listado no tiene por qué tocar la galería.
        if "images_payload" not in cleaned_data:
            return

        raw_payload = cleaned_data.get("images_payload")
        if raw_payload is None:
            return

        draft_token = cleaned_data.get("cloudinary_draft_token") or ""

        try:
            payload = json.loads(raw_payload or "[]")
            items = [item for item in payload if isinstance(item, dict)]
            # La lista vacía es una orden, no un descuido: el formulario arranca
            # con las imágenes que el producto ya tenía —galería y image_url—,
            # así que solo llega vacía si las sacaste todas a mano.
            sync_product_gallery(
                product=obj, draft_token=draft_token, items=items, admin_context=True
            )
        except (ValueError, json.JSONDecodeError, CloudinaryValidationError) as exc:
            self.message_user(request, f"No se pudieron sincronizar las imágenes: {exc}", level=messages.ERROR)

    def _ensure_catalog_image(self, request, obj):
        """
        Baja la imagen del catálogo en el momento, si esa carta todavía no la tiene.

        Cubre el caso de cargar stock de un set recién importado sin haber corrido
        `sync_catalog_images`. Si falla, el producto se guarda igual: no vale
        frenar una carga por una imagen.
        """
        card = obj.catalog_card
        if not card or card.has_image:
            return

        from apps.catalog.services import images as catalog_images
        from apps.catalog.services import r2

        if not r2.is_configured():
            return

        try:
            catalog_images.process_card(card)
        except Exception as exc:  # noqa: BLE001 — nunca frenar el guardado por esto
            self.message_user(
                request,
                f"No se pudo bajar la imagen del catálogo: {exc}",
                level=messages.WARNING,
            )

    class Media:
        css = {
            "all": ("admin/css/product_admin_uploader.css",),
        }
        js = ("admin/js/product_admin_uploader.js",)


@admin.register(ProductImage)
class ProductImageAdmin(ModelAdmin):
    list_display = ("id", "product", "source", "order_index", "status", "uploaded_at")
    list_filter = ("source", "status")
    search_fields = ("public_id", "secure_url", "draft_token")
    readonly_fields = ("uploaded_at", "confirmed_at", "metadata")


@admin.register(ProductImageWebhookEvent)
class ProductImageWebhookEventAdmin(ModelAdmin):
    list_display = ("id", "event_type", "public_id", "is_valid_signature", "processed", "created_at")
    list_filter = ("event_type", "is_valid_signature", "processed")
    search_fields = ("public_id",)
    readonly_fields = ("created_at", "processed_at", "payload")
