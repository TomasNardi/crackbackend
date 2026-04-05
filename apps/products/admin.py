from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import TCG, ProductCategory, CardCondition, CertificationEntity, CertificationGrade, Product


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
            "fields": ("image_url", "image_url_2", "image_url_3"),
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
        ("Referencias externas", {
            "fields": ("pricecharting_url",),
        }),
    )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    class Media:
        js = ("admin/js/product_admin.js",)
