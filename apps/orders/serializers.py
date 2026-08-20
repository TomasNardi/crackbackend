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
from .models import Order, OrderItem, MercadoPagoPayment, DiscountCode, Shipment
from .services.stock_reservation_service import reserve_order_stock
from .services.shipping_service import normalize_shipping_zone, resolve_shipping_price


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
    shipping_method = serializers.ChoiceField(
        choices=Order.SHIPPING_METHOD_CHOICES,
        required=False,
        allow_blank=True,
    )
    shipping_zone = serializers.ChoiceField(
        choices=Order.SHIPPING_ZONE_CHOICES,
        required=False,
        allow_blank=True,
    )
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

            # El tope es lo disponible, en todas las categorías: el stock menos
            # lo que ya está apartado por órdenes de pago manual sin cobrar.
            available = product.available_quantity
            if available is not None and quantity > available:
                unidad = "unidad" if available == 1 else "unidades"
                errors.append(
                    f"'{product.name}' solo tiene {available} {unidad} disponibles."
                )

        return errors

    def _validate_shipping(self, data):
        shipping_method = data.get("shipping_method")
        shipping_type = data.get("shipping_type", Order.SHIPPING_HOME)

        # shipping_type tiene prioridad para evitar inconsistencias cuando el cliente
        # deja un shipping_method previo al cambiar a retiro.
        if shipping_type == Order.SHIPPING_PICKUP:
            shipping_method = Order.SHIPPING_METHOD_STORE_PICKUP
        elif not shipping_method:
            shipping_method = Order.SHIPPING_METHOD_HOME

        is_store_pickup = shipping_method == Order.SHIPPING_METHOD_STORE_PICKUP
        is_home_delivery = shipping_method == Order.SHIPPING_METHOD_HOME
        is_branch_delivery = shipping_method in {
            Order.SHIPPING_METHOD_BRANCH_NORMAL,
            Order.SHIPPING_METHOD_BRANCH_EXPRESS,
        }

        if not (is_store_pickup or is_home_delivery or is_branch_delivery):
            raise serializers.ValidationError(
                {"shipping_method": "Método de envío inválido."}
            )

        data["shipping_method"] = shipping_method
        data["shipping_type"] = Order.SHIPPING_PICKUP if is_store_pickup else Order.SHIPPING_HOME

        if is_store_pickup:
            data["shipping_zone"] = ""
        else:
            shipping_zone = normalize_shipping_zone(
                shipping_province=data.get("shipping_province", ""),
                explicit_zone=data.get("shipping_zone", ""),
            )
            data["shipping_zone"] = shipping_zone

        if is_store_pickup:
            required_fields = {}
        elif is_home_delivery:
            required_fields = {
                "shipping_address": "La dirección es obligatoria para envío a domicilio.",
                "shipping_city": "La ciudad es obligatoria para envío a domicilio.",
                "shipping_province": "La provincia es obligatoria para envío a domicilio.",
                "shipping_zip": "El código postal es obligatorio para envío a domicilio.",
            }
        elif is_branch_delivery:
            required_fields = {
                "shipping_branch": "La sucursal es obligatoria para retiro en punto.",
            }
        else:
            required_fields = {}

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

            shipping_method = validated_data.get("shipping_method", Order.SHIPPING_METHOD_HOME)
            shipping_zone = validated_data.get("shipping_zone", Order.SHIPPING_ZONE_PROVINCE)
            if shipping_method == Order.SHIPPING_METHOD_STORE_PICKUP:
                shipping_price = Decimal("0")
                shipping_zone = ""
            else:
                try:
                    shipping_price = resolve_shipping_price(shipping_method, shipping_zone)
                except Exception as exc:
                    raise serializers.ValidationError({"shipping_method": str(exc)}) from exc

            total = subtotal - discount_value - cash_discount_amount + shipping_price
            total = max(total, Decimal("0"))

            order = Order.objects.create(
                customer_name=validated_data["customer_name"],
                customer_email=validated_data["customer_email"],
                customer_phone=validated_data.get("customer_phone", ""),
                shipping_type=validated_data.get("shipping_type", Order.SHIPPING_HOME),
                shipping_method=shipping_method,
                shipping_zone=shipping_zone,
                shipping_address=validated_data.get("shipping_address", ""),
                shipping_city=validated_data.get("shipping_city", ""),
                shipping_province=validated_data.get("shipping_province", ""),
                shipping_zip=validated_data.get("shipping_zip", ""),
                shipping_branch=validated_data.get("shipping_branch", ""),
                shipping_cost=shipping_price,
                shipping_price=shipping_price,
                has_shipping=shipping_method != Order.SHIPPING_METHOD_STORE_PICKUP,
                shipping_status=Order.SHIPPING_STATUS_PENDING,
                payment_method=payment_method,
                discount_code=discount_code.code.upper() if discount_code else "",
                discount_type=discount_type,
                discount_amount=discount_value + cash_discount_amount,
                cash_discount_percent=cash_discount_percent,
                cash_discount_amount=cash_discount_amount,
                subtotal=subtotal,
                total=total,
            )

            Shipment.objects.create(order=order, status=Shipment.STATUS_PENDING)

            for item in items_to_create:
                OrderItem.objects.create(order=order, **item)

            # Guardar email en EmailSubscription (para campañas posteriores)
            customer_email = validated_data.get("customer_email", "").strip()
            if customer_email:
                EmailSubscription.objects.get_or_create(
                    email=customer_email,
                    defaults={"is_active": True}
                )

            # Mercado Pago descuenta el stock recién cuando el pago queda
            # aprobado. El pago manual (efectivo, transferencia, crypto) no se
            # cobra en el momento: aparta la mercadería y la descuenta cuando
            # marcás la orden como pagada desde el admin.
            if payment_method == Order.PAYMENT_CASH:
                reserve_order_stock(order)

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
            "shipping_method", "shipping_zone", "shipping_price", "has_shipping", "shipping_status",
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
