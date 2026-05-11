import json

from django.contrib import admin
from django.contrib import messages
from unfold.admin import ModelAdmin
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
from .services.cloudinary_service import CloudinaryValidationError, attach_images_to_product


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
        "in_stock",
    )
    list_filter = ("category", "tcg", "in_stock", "certification_entity")
    search_fields = ("name", "description")
    readonly_fields = ("slug", "price_ars_display")
    list_editable = ("in_stock", "discount_percent")

    def price_ars_display(self, obj):
        if not obj.pk or not obj.price_usd:
            return "—"
        return f"${obj.price_ars:,.0f}"
    price_ars_display.short_description = "Precio ARS"

    fieldsets = (
        ("Identificación", {
            "fields": ("name", "description", "tcg", "category"),
        }),
        ("Precio y stock", {
            "fields": ("price_usd", "price_ars_display", "discount_percent", "stock_quantity", "in_stock"),
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

    def has_delete_permission(self, request, obj=None):
        return request.user.has_perm("products.delete_product")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)

        raw_payload = form.cleaned_data.get("images_payload") or "[]"
        draft_token = form.cleaned_data.get("cloudinary_draft_token") or ""

        try:
            payload = json.loads(raw_payload)
            image_ids = [int(item["id"]) for item in payload if isinstance(item, dict) and item.get("id")]
            attach_images_to_product(product=obj, draft_token=draft_token, ordered_image_ids=image_ids)
        except (ValueError, json.JSONDecodeError, CloudinaryValidationError) as exc:
            self.message_user(request, f"No se pudieron sincronizar las imágenes: {exc}", level=messages.ERROR)

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
