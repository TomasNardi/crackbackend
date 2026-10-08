"""
Customers Serializers
======================
"""

from rest_framework import serializers

from apps.orders.models import Order, OrderItem

from .models import Customer, CustomerAddress


class CustomerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ("email", "first_name", "last_name", "phone", "provider", "avatar_url")
        read_only_fields = ("email", "provider", "avatar_url")


class CustomerAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerAddress
        fields = (
            "id", "kind", "branch_name", "first_name", "last_name", "phone",
            "address", "city", "province", "zip_code", "is_default",
        )

    def validate_zip_code(self, value):
        value = value.strip()
        if not value.isdigit() or len(value) != 4:
            raise serializers.ValidationError("El código postal debe tener 4 dígitos.")
        return value


class CustomerOrderItemSerializer(serializers.ModelSerializer):
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    image_url = serializers.SerializerMethodField()
    slug = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = ("product_name", "unit_price", "quantity", "subtotal", "image_url", "slug")

    def get_image_url(self, item):
        return (item.product.image_url or "") if item.product else ""

    def get_slug(self, item):
        return (item.product.slug or "") if item.product else ""


def _status(order: Order) -> tuple[str, str]:
    """Estado del pedido como lo entiende el comprador: (texto, tono)."""
    if order.status == Order.STATUS_CANCELLED:
        return "Cancelado", "danger"
    if order.status == Order.STATUS_EXPIRED:
        return "Vencido", "danger"
    if order.status == Order.STATUS_REFUNDED:
        return "Reembolsado", "neutral"
    if order.status == Order.STATUS_PENDING:
        if order.payment_method == Order.PAYMENT_TRANSFER and order.has_receipt:
            return "Verificando pago", "warning"
        return "Pago pendiente", "warning"
    # Pagada
    if order.shipping_type == Order.SHIPPING_PICKUP:
        if order.pickup_ready_notified_at:
            return "Listo para retirar", "success"
        return "Preparando pedido", "info"
    if order.shipping_status == Order.SHIPPING_STATUS_SHIPPED:
        return "Enviado", "success"
    return "Preparando envío", "info"


def _approved_mp_payment(order: Order):
    """El pago aprobado de Mercado Pago, si hay. Usa el prefetch de `mp_payments`."""
    approved = [p for p in order.mp_payments.all() if p.is_paid]
    return max(approved, key=lambda p: p.date_approved or p.created_at) if approved else None


def _timeline(order: Order) -> list[tuple[str, object]]:
    """Lo que ya pasó con el pedido, en orden: (título, fecha). La fecha puede
    ser None: hay hitos (como la acreditación de una transferencia) que no
    guardan su hora."""
    events = [("Pedido realizado", order.created_at)]

    if order.receipt_uploaded_at:
        events.append(("Comprobante de transferencia enviado", order.receipt_uploaded_at))

    mp_payment = _approved_mp_payment(order)
    if mp_payment:
        events.append(("Pago aprobado por Mercado Pago", mp_payment.date_approved))
    elif order.status in (Order.STATUS_PAID, Order.STATUS_REFUNDED):
        events.append(("Pago confirmado", None))

    shipment = getattr(order, "shipment", None)
    if shipment and shipment.status == shipment.STATUS_SHIPPED:
        events.append(("Pedido despachado", shipment.shipped_at))
    elif order.shipping_status == Order.SHIPPING_STATUS_SHIPPED:
        events.append(("Pedido despachado", None))

    if order.pickup_ready_notified_at:
        events.append(("Listo para retirar en el local", order.pickup_ready_notified_at))

    if order.status == Order.STATUS_EXPIRED:
        events.append(("Venció el plazo de pago", None))
    elif order.status == Order.STATUS_CANCELLED:
        events.append(("Pedido cancelado", None))
    elif order.status == Order.STATUS_REFUNDED:
        events.append(("Pago reembolsado", None))
    return events


def _iso(value):
    return serializers.DateTimeField().to_representation(value) if value else None


class CustomerOrderSerializer(serializers.ModelSerializer):
    items = CustomerOrderItemSerializer(many=True, read_only=True)
    status_label = serializers.SerializerMethodField()
    status_tone = serializers.SerializerMethodField()
    payment_method_label = serializers.CharField(source="get_payment_method_display", read_only=True)
    shipping_method_label = serializers.CharField(source="get_shipping_method_display", read_only=True)
    tracking = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "order_code", "created_at", "status", "status_label", "status_tone",
            "payment_method", "payment_method_label",
            "shipping_type", "shipping_method", "shipping_method_label",
            "shipping_address", "shipping_city", "shipping_province", "shipping_zip", "shipping_branch",
            "subtotal", "shipping_cost", "discount_amount", "card_surcharge_amount", "total",
            "tracking", "timeline", "payment", "items",
        )

    def get_status_label(self, order):
        return _status(order)[0]

    def get_status_tone(self, order):
        return _status(order)[1]

    def get_timeline(self, order):
        return [{"title": title, "at": _iso(at)} for title, at in _timeline(order)]

    def get_payment(self, order):
        mp_payment = _approved_mp_payment(order)
        return {
            "operation_id": mp_payment.payment_id if mp_payment else "",
            "approved_at": _iso(mp_payment.date_approved) if mp_payment else None,
        }

    def get_tracking(self, order):
        shipment = getattr(order, "shipment", None)
        if not shipment or not shipment.tracking_code:
            return None
        return {
            "code": shipment.tracking_code,
            "carrier": shipment.get_carrier_display(),
            "url": shipment.carrier_tracking_url,
        }
