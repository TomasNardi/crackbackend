"""
Serializers de importación eBay
================================
El front manda links y cantidades; los precios los pone siempre el servidor.
Nada de lo que llega del cliente entra en un total.
"""

from rest_framework import serializers

from apps.ebay.models import EbayConfig, EbayOrder, EbayOrderItem


class EbayConfigSerializer(serializers.ModelSerializer):
    """Lo que el front necesita saber para dibujar la calculadora."""

    delivery_types = serializers.SerializerMethodField()
    whatsapp_url = serializers.SerializerMethodField()

    class Meta:
        model = EbayConfig
        fields = [
            "is_active", "commission_percent", "tax_percent",
            "quote_ttl_minutes", "max_items_per_order", "max_quantity_per_item",
            "intro_text", "arg_shipping", "delivery_types", "whatsapp_url",
        ]

    def get_delivery_types(self, obj):
        return [{"value": value, "label": label} for value, label in EbayOrder.DELIVERY_CHOICES]

    def get_whatsapp_url(self, obj):
        return f"https://wa.me/{obj.whatsapp_number}"


class QuoteRequestSerializer(serializers.Serializer):
    url = serializers.CharField(max_length=1000)
    quantity = serializers.IntegerField(min_value=1, max_value=99, default=1)


class OrderItemInputSerializer(serializers.Serializer):
    """Una línea del carrito tal como la manda el front."""

    url = serializers.CharField(max_length=1000)
    quantity = serializers.IntegerField(min_value=1, max_value=99, default=1)
    # Solo sirve para detectar si el precio se movió desde que lo cotizó.
    # Nunca se usa para calcular el total.
    quoted_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True,
    )


class EbayOrderCreateSerializer(serializers.Serializer):
    customer_name = serializers.CharField(max_length=255)
    customer_email = serializers.EmailField()
    customer_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)

    delivery_type = serializers.ChoiceField(
        choices=EbayOrder.DELIVERY_CHOICES, default=EbayOrder.DELIVERY_PICKUP,
    )
    shipping_address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    shipping_city = serializers.CharField(max_length=120, required=False, allow_blank=True)
    shipping_province = serializers.CharField(max_length=120, required=False, allow_blank=True)
    shipping_zip = serializers.CharField(max_length=20, required=False, allow_blank=True)
    shipping_branch = serializers.CharField(max_length=255, required=False, allow_blank=True)
    customer_notes = serializers.CharField(required=False, allow_blank=True)

    items = OrderItemInputSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("El pedido está vacío.")

        max_items = EbayConfig.get().max_items_per_order
        if len(value) > max_items:
            raise serializers.ValidationError(
                f"El pedido no puede tener más de {max_items} publicaciones."
            )
        return value

    def validate(self, attrs):
        """Si eligió envío, la dirección deja de ser opcional."""
        delivery = attrs.get("delivery_type", EbayOrder.DELIVERY_PICKUP)

        if delivery == EbayOrder.DELIVERY_HOME:
            missing = [
                field for field in ("shipping_address", "shipping_city", "shipping_province")
                if not (attrs.get(field) or "").strip()
            ]
            if missing:
                raise serializers.ValidationError(
                    {field: "Requerido para envío a domicilio." for field in missing}
                )

        if delivery == EbayOrder.DELIVERY_BRANCH:
            if not (attrs.get("shipping_province") or "").strip():
                raise serializers.ValidationError(
                    {"shipping_province": "Requerido para envío a sucursal."}
                )

        return attrs


class EbayOrderItemReadSerializer(serializers.ModelSerializer):
    unit_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    price_delta = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = EbayOrderItem
        fields = [
            "id", "ebay_item_id", "ebay_url", "title", "image_url", "quantity",
            "price", "commission", "tax", "ebay_shipping", "arg_shipping",
            "unit_total", "line_total",
            "price_changed", "original_price", "price_delta",
        ]


class EbayOrderReadSerializer(serializers.ModelSerializer):
    """Vista completa — solo para el admin."""

    items = EbayOrderItemReadSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    delivery_type_label = serializers.CharField(source="get_delivery_type_display", read_only=True)
    delivery_summary = serializers.CharField(read_only=True)

    class Meta:
        model = EbayOrder
        fields = [
            "order_code", "customer_name", "customer_email", "customer_phone",
            "status", "status_label",
            "delivery_type", "delivery_type_label", "delivery_summary",
            "shipping_address", "shipping_city", "shipping_province", "shipping_zip",
            "shipping_branch", "customer_notes",
            "commission_percent", "tax_percent",
            "items_total", "commission_total", "tax_total",
            "ebay_shipping_total", "arg_shipping_total", "total",
            "has_price_changes", "rejection_message", "block_reason",
            "approved_at", "rejected_at", "payment_received_at", "arrived_at", "delivered_at",
            "created_at", "items",
        ]


class EbayOrderPublicSerializer(serializers.ModelSerializer):
    """
    Lo que devuelve la página de seguimiento.

    El pedido se consulta solo con el código, así que acá va lo mínimo para que
    el cliente reconozca su pedido y vea en qué paso está. Email, teléfono,
    calle y código postal quedan afuera a propósito: un código de seis
    caracteres es adivinable y no queremos que eso exponga datos de contacto.
    """

    items = EbayOrderItemReadSerializer(many=True, read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    delivery_type_label = serializers.CharField(source="get_delivery_type_display", read_only=True)

    class Meta:
        model = EbayOrder
        fields = [
            "order_code", "customer_name", "status", "status_label",
            "delivery_type", "delivery_type_label",
            "shipping_city", "shipping_province",
            "commission_percent", "tax_percent",
            "items_total", "commission_total", "tax_total",
            "ebay_shipping_total", "arg_shipping_total", "total",
            "has_price_changes", "rejection_message",
            "approved_at", "rejected_at", "payment_received_at", "arrived_at", "delivered_at",
            "created_at", "items",
        ]
