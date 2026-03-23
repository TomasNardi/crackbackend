"""
Orders Serializers
===================
"""

from decimal import Decimal
from rest_framework import serializers
from apps.products.models import Product
from .models import Order, OrderItem, MercadoPagoPayment, DiscountCode


class OrderItemInputSerializer(serializers.Serializer):
    """Input para cada ítem al crear una orden."""
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)


class OrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ("id", "product", "product_name", "unit_price", "quantity", "subtotal")


class OrderCreateSerializer(serializers.Serializer):
    """
    Crea una orden validando stock y calculando precios desde el backend.
    El frontend solo envía product_id + quantity — los precios los calcula el servidor.
    """

    customer_name = serializers.CharField(max_length=255)
    customer_email = serializers.EmailField()
    customer_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    shipping_type = serializers.ChoiceField(choices=Order.SHIPPING_CHOICES, default=Order.SHIPPING_HOME)
    shipping_address = serializers.CharField(max_length=500, required=False, allow_blank=True)
    shipping_city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    shipping_province = serializers.CharField(max_length=100, required=False, allow_blank=True)
    shipping_zip = serializers.CharField(max_length=20, required=False, allow_blank=True)
    shipping_branch = serializers.CharField(max_length=255, required=False, allow_blank=True)
    shipping_cost = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    items = OrderItemInputSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("La orden debe tener al menos un ítem.")
        return items

    def validate(self, data):
        """Valida stock y resuelve productos."""
        items_input = data["items"]
        product_ids = [i["product_id"] for i in items_input]

        # Fetch todos los productos de una sola query
        products = {
            p.id: p for p in Product.objects.select_related(
                "category", "certification_grade"
            ).filter(id__in=product_ids, in_stock=True)
        }

        errors = []
        for item in items_input:
            pid = item["product_id"]
            qty = item["quantity"]
            product = products.get(pid)

            if not product:
                errors.append(f"Producto {pid} no encontrado o sin stock.")
                continue

            category_name = product.category.name if product.category else ""
            is_unique = category_name in ("Slab", "Single")

            if is_unique and qty > 1:
                errors.append(f"'{product.name}' es único — solo se puede comprar 1 unidad.")
                continue

            if not is_unique and product.stock_quantity is not None:
                if qty > product.stock_quantity:
                    errors.append(
                        f"'{product.name}' solo tiene {product.stock_quantity} unidades disponibles."
                    )
                    continue

        if errors:
            raise serializers.ValidationError(errors)

        data["_products"] = products
        return data

    def create(self, validated_data):
        items_input = validated_data.pop("items")
        products = validated_data.pop("_products")

        # Validar y aplicar código de descuento
        discount_code_str = validated_data.get("discount_code", "")
        discount_type = Order.DISCOUNT_NONE
        discount_amount = Decimal("0")

        if discount_code_str:
            dc = DiscountCode.objects.filter(code__iexact=discount_code_str).first()
            if dc and dc.is_valid():
                discount_type = dc.discount_type
                discount_amount = dc.discount_amount
                dc.activate()

        # Calcular subtotal con precios del servidor
        subtotal = Decimal("0")
        items_to_create = []
        for item in items_input:
            product = products[item["product_id"]]
            unit_price = product.final_price
            qty = item["quantity"]
            subtotal += unit_price * qty
            items_to_create.append({
                "product": product,
                "product_name": product.name,
                "unit_price": unit_price,
                "quantity": qty,
            })

        # Calcular descuento
        if discount_type == DiscountCode.DISCOUNT_PERCENT:
            discount_value = subtotal * discount_amount / Decimal("100")
        elif discount_type == DiscountCode.DISCOUNT_FIXED:
            discount_value = min(discount_amount, subtotal)
        else:
            discount_value = Decimal("0")

        shipping_cost = validated_data.get("shipping_cost", Decimal("0"))
        total = subtotal - discount_value + shipping_cost

        order = Order.objects.create(
            customer_name=validated_data["customer_name"],
            customer_email=validated_data["customer_email"],
            customer_phone=validated_data.get("customer_phone", ""),
            shipping_type=validated_data.get("shipping_type", Order.SHIPPING_HOME),
            shipping_address=validated_data.get("shipping_address", ""),
            shipping_city=validated_data.get("shipping_city", ""),
            shipping_province=validated_data.get("shipping_province", ""),
            shipping_zip=validated_data.get("shipping_zip", ""),
            shipping_branch=validated_data.get("shipping_branch", ""),
            shipping_cost=shipping_cost,
            discount_code=discount_code_str.upper() if discount_code_str else "",
            discount_type=discount_type,
            discount_amount=discount_value,
            subtotal=subtotal,
            total=total,
        )

        for item in items_to_create:
            OrderItem.objects.create(order=order, **item)

        # Decrementar stock para productos no únicos
        for item in items_to_create:
            product = item["product"]
            category_name = product.category.name if product.category else ""
            if category_name not in ("Slab", "Single") and product.stock_quantity is not None:
                product.stock_quantity = max(0, product.stock_quantity - item["quantity"])
                if product.stock_quantity == 0:
                    product.in_stock = False
                product.save(update_fields=["stock_quantity", "in_stock"])

        return order


class OrderReadSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id", "customer_name", "customer_email", "customer_phone",
            "shipping_type", "shipping_address", "shipping_city",
            "shipping_province", "shipping_zip", "shipping_cost",
            "discount_code", "discount_amount",
            "subtotal", "total", "status",
            "items", "created_at",
        )


class DiscountCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DiscountCode
        fields = (
            "id", "code", "discount_type", "discount_amount",
            "expiration_type", "valid_from", "valid_until",
            "max_uses", "uses", "used",
        )
