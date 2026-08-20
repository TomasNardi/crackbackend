"""
Products Serializers
=====================
"""

from rest_framework import serializers
from .models import TCG, ProductCategory, CardCondition, CertificationEntity, CertificationGrade, Product, ProductImage
from .services.cloudinary_service import (
    DELIVERY_TRANSFORM_DETAIL,
    DELIVERY_TRANSFORM_LIST,
    DELIVERY_TRANSFORM_SEARCH,
    DELIVERY_TRANSFORM_THUMB,
    optimize_cloudinary_url,
)


class ProductImageSerializer(serializers.ModelSerializer):
    secure_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = (
            "id",
            "secure_url",
            "thumbnail_url",
            "public_id",
            "order_index",
            "source",
            "status",
            "width",
            "height",
            "bytes",
            "format",
        )

    def get_secure_url(self, obj):
        return optimize_cloudinary_url(obj.secure_url, DELIVERY_TRANSFORM_DETAIL)

    def get_thumbnail_url(self, obj):
        return optimize_cloudinary_url(obj.secure_url, DELIVERY_TRANSFORM_THUMB)


class CatalogCardSerializer(serializers.ModelSerializer):
    """
    Datos de la carta del catálogo (TCGplayer) que están detrás del producto.

    Se expone anidado en vez de copiarse a `Product`: el catálogo se reimporta
    solo, así el número, la rareza o el set nunca quedan desactualizados. Sirve
    para filtrar y mostrar en el front sin pegarle a otro endpoint.
    """

    set_name = serializers.CharField(source="card_set.name", read_only=True)
    set_abbreviation = serializers.CharField(source="card_set.abbreviation", read_only=True)
    set_slug = serializers.CharField(source="card_set.slug", read_only=True)
    language = serializers.CharField(source="card_set.language", read_only=True)
    released_at = serializers.DateField(source="card_set.released_at", read_only=True)

    class Meta:
        from apps.catalog.models import CatalogCard

        model = CatalogCard
        fields = (
            "id", "external_id", "name", "number", "rarity",
            "set_name", "set_abbreviation", "set_slug", "language", "released_at",
            "image_url", "image_url_medium", "image_url_thumb",
        )


class TCGSerializer(serializers.ModelSerializer):
    class Meta:
        model = TCG
        fields = ("id", "name", "slug")


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ("id", "name", "slug")


class CardConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CardCondition
        fields = ("id", "name", "abbreviation")


class CertificationEntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificationEntity
        fields = ("id", "name", "abbreviation")


class CertificationGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificationGrade
        fields = ("id", "grade")


class ProductSearchSerializer(serializers.ModelSerializer):
    """Serializer liviano para autocomplete — solo campos esenciales."""
    category = serializers.StringRelatedField()
    tcg = serializers.StringRelatedField()
    image_url = serializers.SerializerMethodField()
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    def get_image_url(self, obj):
        return optimize_cloudinary_url(obj.image_url, DELIVERY_TRANSFORM_SEARCH)

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "tcg", "category",
            "image_url", "price_ars", "final_price", "discount_percent",
            "stock_quantity", "available_quantity", "in_stock",
        )


class ProductListSerializer(serializers.ModelSerializer):
    tcg = TCGSerializer(read_only=True)
    category = serializers.StringRelatedField()
    condition = CardConditionSerializer(read_only=True)
    certification_entity = serializers.StringRelatedField()
    certification_grade = serializers.StringRelatedField()
    image_url = serializers.SerializerMethodField()
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)
    catalog = CatalogCardSerializer(source="catalog_card", read_only=True)

    def get_image_url(self, obj):
        return optimize_cloudinary_url(obj.image_url, DELIVERY_TRANSFORM_LIST)

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "tcg", "category",
            "condition", "certification_entity", "certification_grade",
            "price_usd", "price_ars", "discount_percent", "final_price",
            "stock_quantity", "available_quantity", "in_stock", "image_url", "images", "rating", "rating_count", "created_at",
            "catalog",
        )


class ProductSuggestedSerializer(serializers.ModelSerializer):
    category = serializers.StringRelatedField()
    image_url = serializers.SerializerMethodField()
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    images = ProductImageSerializer(many=True, read_only=True)

    def get_image_url(self, obj):
        return optimize_cloudinary_url(obj.image_url, DELIVERY_TRANSFORM_LIST)

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "category",
            "image_url", "images", "price_ars", "final_price", "discount_percent",
            "stock_quantity", "available_quantity", "in_stock",
        )


class ProductDetailSerializer(serializers.ModelSerializer):
    tcg = TCGSerializer(read_only=True)
    category = ProductCategorySerializer(read_only=True)
    condition = CardConditionSerializer(read_only=True)
    certification_entity = CertificationEntitySerializer(read_only=True)
    certification_grade = CertificationGradeSerializer(read_only=True)
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    image_url = serializers.SerializerMethodField()
    image_url_2 = serializers.SerializerMethodField()
    image_url_3 = serializers.SerializerMethodField()
    suggested_products = serializers.SerializerMethodField()
    images = ProductImageSerializer(many=True, read_only=True)
    catalog = CatalogCardSerializer(source="catalog_card", read_only=True)

    def get_image_url(self, obj):
        return optimize_cloudinary_url(obj.image_url, DELIVERY_TRANSFORM_DETAIL)

    def get_image_url_2(self, obj):
        return optimize_cloudinary_url(obj.image_url_2, DELIVERY_TRANSFORM_DETAIL)

    def get_image_url_3(self, obj):
        return optimize_cloudinary_url(obj.image_url_3, DELIVERY_TRANSFORM_DETAIL)

    def get_suggested_products(self, obj):
        from apps.orders.models import SuggestedProductsCarousel

        config = SuggestedProductsCarousel.objects.first()
        if not config:
            return []

        suggested = config.suggested_products.filter(in_stock=True).order_by("-created_at")[:3]
        return ProductSuggestedSerializer(suggested, many=True).data

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "description",
            "tcg", "category",
            "condition", "certification_entity", "certification_grade",
            "price_usd", "price_ars", "discount_percent", "final_price",
            "stock_quantity", "available_quantity", "in_stock",
            "image_url", "image_url_2", "image_url_3",
            "images",
            "suggested_products",
            "rating", "rating_count",
            "pricecharting_url", "created_at", "updated_at",
            "catalog",
        )


class ProductWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = (
            "name", "description", "tcg", "category",
            "condition", "certification_entity", "certification_grade",
            "price_usd", "discount_percent",
            "stock_quantity", "available_quantity", "in_stock",
            "image_url", "image_url_2", "image_url_3",
            "rating", "rating_count",
            "pricecharting_url",
        )
