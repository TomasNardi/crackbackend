"""
Orders Serializers
===================
"""

from rest_framework import serializers
from .models import Order, OrderItem, MercadoPagoPayment, DiscountCode


class OrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ("id", "product", "product_name", "unit_price", "quantity", "subtotal")


class OrderCreateSerializer(serializers.ModelSerializer):
    """Usado para crear una orden desde el checkout."""

    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = (
            "customer_name",
            "customer_email",
            "customer_phone",
            "shipping_type",
            "shipping_address",
            "shipping_city",
            "shipping_province",
            "shipping_zip",
            "shipping_branch",
            "shipping_cost",
            "discount_code",
            "discount_type",
            "discount_amount",
            "subtotal",
            "total",
            "items",
        )

    def create(self, validated_data):
        items_data = validated_data.pop("items")
        order = Order.objects.create(**validated_data)
        for item in items_data:
            OrderItem.objects.create(order=order, **item)
        return order


class OrderReadSerializer(serializers.ModelSerializer):
    """Serializer de lectura con ítems anidados."""

    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "customer_name",
            "customer_email",
            "customer_phone",
            "shipping_type",
            "shipping_address",
            "shipping_city",
            "shipping_province",
            "shipping_zip",
            "shipping_cost",
            "discount_code",
            "discount_amount",
            "subtotal",
            "total",
            "status",
            "items",
            "created_at",
        )


class DiscountCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiscountCode
        fields = (
            "id", "code", "discount_type", "discount_amount",
            "expiration_type", "valid_from", "valid_until",
            "max_uses", "uses", "used",
        )
