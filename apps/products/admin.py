from django.contrib import admin
from .models import TCG, Expansion, ProductType, CardCondition, Product


@admin.register(TCG)
class TCGAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Expansion)
class ExpansionAdmin(admin.ModelAdmin):
    list_display = ("name", "tcg", "slug")
    list_filter = ("tcg",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ProductType)
class ProductTypeAdmin(admin.ModelAdmin):
    list_display = ("name",)


@admin.register(CardCondition)
class CardConditionAdmin(admin.ModelAdmin):
    list_display = ("name", "abbreviation")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name", "product_type", "tcg", "expansion",
        "price", "discount_percent", "in_stock", "is_single", "created_at",
    )
    list_filter = ("product_type", "tcg", "in_stock", "is_single")
    search_fields = ("name", "expansion__name")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
    list_editable = ("in_stock", "discount_percent")
