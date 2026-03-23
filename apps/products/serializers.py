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
            "in_stock", "image_url", "created_at",
        )


class ProductDetailSerializer(serializers.ModelSerializer):
    tcg = TCGSerializer(read_only=True)
    category = ProductCategorySerializer(read_only=True)
    condition = CardConditionSerializer(read_only=True)
    certification_entity = CertificationEntitySerializer(read_only=True)
    certification_grade = CertificationGradeSerializer(read_only=True)
    price_ars = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id", "name", "slug", "description",
            "tcg", "category",
            "condition", "certification_entity", "certification_grade",
            "price_usd", "price_ars", "discount_percent", "final_price",
            "stock_quantity", "in_stock",
            "image_url", "image_url_2", "image_url_3",
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
            "pricecharting_url",
        )
