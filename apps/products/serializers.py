"""
Products Serializers
=====================
"""

from rest_framework import serializers
from .models import TCG, ProductCategory, CardCondition, CertificationEntity, CertificationGrade, Product


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
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "tcg", "category",
            "image_url", "price_ars", "final_price", "discount_percent",
            "stock_quantity", "in_stock",
        )


class ProductListSerializer(serializers.ModelSerializer):
    tcg = TCGSerializer(read_only=True)
    category = serializers.StringRelatedField()
    condition = serializers.StringRelatedField()
    certification_entity = serializers.StringRelatedField()
    certification_grade = serializers.StringRelatedField()
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "tcg", "category",
            "condition", "certification_entity", "certification_grade",
            "price_usd", "price_ars", "discount_percent", "final_price",
            "stock_quantity", "in_stock", "image_url", "rating", "rating_count", "created_at",
        )


class ProductSuggestedSerializer(serializers.ModelSerializer):
    category = serializers.StringRelatedField()
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "category",
            "image_url", "price_ars", "final_price", "discount_percent",
            "stock_quantity", "in_stock",
        )


class ProductDetailSerializer(serializers.ModelSerializer):
    tcg = TCGSerializer(read_only=True)
    category = ProductCategorySerializer(read_only=True)
    condition = CardConditionSerializer(read_only=True)
    certification_entity = CertificationEntitySerializer(read_only=True)
    certification_grade = CertificationGradeSerializer(read_only=True)
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    suggested_products = serializers.SerializerMethodField()

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
            "stock_quantity", "in_stock",
            "image_url", "image_url_2", "image_url_3",
            "suggested_products",
            "rating", "rating_count",
            "pricecharting_url", "created_at", "updated_at",
        )


class ProductWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = (
            "name", "description", "tcg", "category",
            "condition", "certification_entity", "certification_grade",
            "price_usd", "discount_percent",
            "stock_quantity", "in_stock",
            "image_url", "image_url_2", "image_url_3",
            "rating", "rating_count",
            "pricecharting_url",
        )
