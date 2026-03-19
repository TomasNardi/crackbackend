"""
Products Serializers
=====================
"""

from rest_framework import serializers
from .models import TCG, Expansion, ProductType, CardCondition, Product


class TCGSerializer(serializers.ModelSerializer):
    class Meta:
        model = TCG
        fields = ("id", "name", "slug")


class ExpansionSerializer(serializers.ModelSerializer):
    tcg = TCGSerializer(read_only=True)
    tcg_id = serializers.PrimaryKeyRelatedField(
        queryset=TCG.objects.all(), source="tcg", write_only=True
    )

    class Meta:
        model = Expansion
        fields = ("id", "name", "slug", "tcg", "tcg_id")


class ProductTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductType
        fields = ("id", "name")


class CardConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CardCondition
        fields = ("id", "name", "abbreviation")


class ProductListSerializer(serializers.ModelSerializer):
    """Serializer liviano para listados y paginación."""

    tcg = TCGSerializer(read_only=True)
    expansion = serializers.StringRelatedField()
    product_type = serializers.StringRelatedField()
    condition = serializers.StringRelatedField()
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "tcg",
            "expansion",
            "product_type",
            "condition",
            "price",
            "discount_percent",
            "final_price",
            "in_stock",
            "is_single",
            "image_url",
            "created_at",
        )


class ProductDetailSerializer(serializers.ModelSerializer):
    """Serializer completo para el detalle de un producto."""

    tcg = TCGSerializer(read_only=True)
    expansion = ExpansionSerializer(read_only=True)
    product_type = ProductTypeSerializer(read_only=True)
    condition = CardConditionSerializer(read_only=True)
    final_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "tcg",
            "expansion",
            "product_type",
            "condition",
            "price",
            "discount_percent",
            "final_price",
            "is_single",
            "stock_quantity",
            "in_stock",
            "image_url",
            "image_url_2",
            "image_url_3",
            "pricecharting_url",
            "created_at",
            "updated_at",
        )


class ProductWriteSerializer(serializers.ModelSerializer):
    """Serializer para crear/editar productos (solo admin)."""

    class Meta:
        model = Product
        fields = (
            "name",
            "description",
            "tcg",
            "expansion",
            "product_type",
            "condition",
            "price",
            "discount_percent",
            "is_single",
            "stock_quantity",
            "in_stock",
            "image_url",
            "image_url_2",
            "image_url_3",
            "pricecharting_url",
        )
