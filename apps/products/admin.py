from django.contrib import admin
from .models import TCG, ProductCategory, CardCondition, CertificationEntity, CertificationGrade, Product


@admin.register(TCG)
class TCGAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(CardCondition)
class CardConditionAdmin(admin.ModelAdmin):
    list_display = ("name", "abbreviation")


@admin.register(CertificationEntity)
class CertificationEntityAdmin(admin.ModelAdmin):
    list_display = ("name", "abbreviation")


@admin.register(CertificationGrade)
class CertificationGradeAdmin(admin.ModelAdmin):
    list_display = ("grade",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name", "category", "tcg",
        "price_usd", "price_ars_display", "discount_percent", "in_stock", "created_at",
    )
    list_filter = ("category", "tcg", "in_stock", "certification_entity")
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("slug", "price_ars_display", "created_at", "updated_at")
    list_editable = ("in_stock", "discount_percent")

    def price_ars_display(self, obj):
        return f"${obj.price_ars:,.0f}"
    price_ars_display.short_description = "Precio ARS"

    fieldsets = (
        ("Identificación", {
            "fields": ("name", "slug", "description", "tcg", "category"),
        }),
        ("Precio y stock", {
            "fields": ("price_usd", "price_ars_display", "discount_percent", "stock_quantity", "in_stock"),
        }),
        ("Imágenes", {
            "fields": ("image_url", "image_url_2", "image_url_3"),
            "classes": ("collapse",),
        }),
        ("Singles — Condición", {
            "fields": ("condition",),
            "classes": ("collapse",),
        }),
        ("Slabs — Certificación", {
            "fields": ("certification_entity", "certification_grade"),
            "classes": ("collapse",),
        }),
        ("Referencias externas", {
            "fields": ("pricecharting_url",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
