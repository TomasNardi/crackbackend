"""
Orders Serializers
===================
"""

from collections import OrderedDict
from decimal import Decimal
from django.db import transaction
from rest_framework import serializers
from apps.products.models import Product
from apps.core.models import SiteConfig, EmailSubscription
from .models import Order, OrderItem, MercadoPagoPayment, DiscountCode


UNIQUE_ORDER_CATEGORIES = {"single", "singles", "slab", "slabs"}


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
    payment_method = serializers.ChoiceField(choices=Order.PAYMENT_METHOD_CHOICES, default=Order.PAYMENT_MERCADOPAGO)
    discount_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    items = OrderItemInputSerializer(many=True)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("La orden debe tener al menos un ítem.")
        return items

    def _normalize_items(self, items_input):
        normalized = OrderedDict()
        for item in items_input:
            product_id = item["product_id"]
            if product_id not in normalized:
                normalized[product_id] = {"product_id": product_id, "quantity": 0}
            normalized[product_id]["quantity"] += item["quantity"]
        return list(normalized.values())

    def _get_products_map(self, product_ids, for_update=False):
        queryset = Product.objects.all()
        if for_update:
            queryset = queryset.select_for_update()
        queryset = queryset.select_related("category")
        return {product.id: product for product in queryset.filter(id__in=product_ids)}

    def _get_availability_errors(self, items_input, products):
        errors = []

        for item in items_input:
            product_id = item["product_id"]
            quantity = item["quantity"]
            product = products.get(product_id)

            if not product:
                errors.append(f"Producto ID {product_id} no existe o ya no está disponible.")
                continue

            if not product.in_stock:
                errors.append(f"'{product.name}' fue comprado recientemente y ya no está disponible.")
                continue

            category_name = product.category.name if product.category else ""
            is_unique = category_name.strip().lower() in UNIQUE_ORDER_CATEGORIES

            if is_unique and quantity > 1:
                errors.append(f"'{product.name}' es único y solo permite 1 unidad.")
                continue

            if not is_unique and product.stock_quantity is not None and quantity > product.stock_quantity:
                errors.append(
                    f"'{product.name}' solo tiene {product.stock_quantity} unidades disponibles."
                )

        return errors

    def _validate_shipping(self, data):
        shipping_type = data.get("shipping_type", Order.SHIPPING_HOME)

        if shipping_type == Order.SHIPPING_HOME:
            required_fields = {
                "shipping_address": "La dirección es obligatoria para envío a domicilio.",
                "shipping_city": "La ciudad es obligatoria para envío a domicilio.",
                "shipping_province": "La provincia es obligatoria para envío a domicilio.",
                "shipping_zip": "El código postal es obligatorio para envío a domicilio.",
            }
        else:
            required_fields = {
                "shipping_branch": "La sucursal es obligatoria para retiro en punto.",
            }

        shipping_errors = {
            field: message
            for field, message in required_fields.items()
            if not (data.get(field) or "").strip()
        }
        if shipping_errors:
            raise serializers.ValidationError(shipping_errors)

    def validate(self, data):
        """Valida stock y resuelve productos."""
        self._validate_shipping(data)

        normalized_items = self._normalize_items(data["items"])
        products = self._get_products_map([item["product_id"] for item in normalized_items])
        errors = self._get_availability_errors(normalized_items, products)

        if errors:
            raise serializers.ValidationError({"items": errors})

        data["_normalized_items"] = normalized_items
        return data

    def create(self, validated_data):
        items_input = validated_data.pop("_normalized_items", validated_data.pop("items"))

        with transaction.atomic():
            products = self._get_products_map(
                [item["product_id"] for item in items_input],
                for_update=True,
            )
            errors = self._get_availability_errors(items_input, products)
            if errors:
                raise serializers.ValidationError({"items": errors})

            discount_code_str = (validated_data.get("discount_code") or "").strip()
            discount_type = ""
            discount_amount = Decimal("0")
            discount_code = None

            if discount_code_str:
                discount_code = DiscountCode.objects.select_for_update().filter(
                    code__iexact=discount_code_str
                ).first()
                if discount_code and discount_code.is_valid():
                    discount_type = discount_code.discount_type
                    discount_amount = discount_code.discount_amount

            subtotal = Decimal("0")
            items_to_create = []
            for item in items_input:
                product = products[item["product_id"]]
                unit_price = product.final_price
                quantity = item["quantity"]
                subtotal += unit_price * quantity
                items_to_create.append({
                    "product": product,
                    "product_name": product.name,
                    "unit_price": unit_price,
                    "quantity": quantity,
                })

            if discount_type == DiscountCode.DISCOUNT_PERCENT:
                discount_value = subtotal * discount_amount / Decimal("100")
            elif discount_type == DiscountCode.DISCOUNT_FIXED:
                discount_value = min(discount_amount, subtotal)
            else:
                discount_value = Decimal("0")

            cash_discount_percent = Decimal("0")
            cash_discount_amount = Decimal("0")
            payment_method = validated_data.get("payment_method", Order.PAYMENT_MERCADOPAGO)
            if payment_method == Order.PAYMENT_CASH:
                config = SiteConfig.get()
                if config.cash_discount_enabled and config.cash_discount_percent > 0:
                    cash_discount_percent = Decimal(config.cash_discount_percent)
                    cash_discount_amount = (subtotal - discount_value) * cash_discount_percent / Decimal("100")

            shipping_cost = Decimal("0")
            total = subtotal - discount_value - cash_discount_amount + shipping_cost
            total = max(total, Decimal("0"))

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
                payment_method=payment_method,
                discount_code=discount_code.code.upper() if discount_code else "",
                discount_type=discount_type,
                discount_amount=discount_value + cash_discount_amount,
                cash_discount_percent=cash_discount_percent,
                cash_discount_amount=cash_discount_amount,
                subtotal=subtotal,
                total=total,
            )

            for item in items_to_create:
                OrderItem.objects.create(order=order, **item)

            # Guardar email en EmailSubscription (para campañas posteriores)
            customer_email = validated_data.get("customer_email", "").strip()
            if customer_email:
                EmailSubscription.objects.get_or_create(
                    email=customer_email,
                    defaults={"is_active": True}
                )

            # Para Mercado Pago, el stock y el código se aplican recién cuando el pago queda aprobado.
            if payment_method == Order.PAYMENT_CASH:
                for item in items_to_create:
                    product = item["product"]
                    category_name = product.category.name if product.category else ""
                    is_unique = category_name.strip().lower() in UNIQUE_ORDER_CATEGORIES

                    if is_unique:
                        product.in_stock = False
                        product.save(update_fields=["in_stock", "updated_at"])
                        continue

                    if product.stock_quantity is not None:
                        product.stock_quantity = max(0, product.stock_quantity - item["quantity"])
                        product.in_stock = product.stock_quantity > 0
                        product.save(update_fields=["stock_quantity", "in_stock", "updated_at"])

                if discount_code:
                    discount_code.activate()

        return order


class OrderReadSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id", "order_code",
            "customer_name", "customer_email", "customer_phone",
            "shipping_type", "shipping_address", "shipping_city",
            "shipping_province", "shipping_zip", "shipping_cost",
            "payment_method", "cash_discount_percent", "cash_discount_amount",
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
