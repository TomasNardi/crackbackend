from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from apps.orders.mercadopago_service import create_checkout_preference
from apps.orders.models import Order, OrderItem


class MercadoPagoPreferenceTests(TestCase):
    @override_settings(
        MERCADOPAGO_ACCESS_TOKEN="test-token",
        FRONTEND_URL="https://front.example",
        BACKEND_PUBLIC_URL="https://api.example",
    )
    @patch("apps.orders.mercadopago_service._sdk")
    def test_checkout_preference_charges_final_order_total(self, mock_sdk):
        sdk = Mock()
        preference_resource = Mock()
        preference_resource.create.return_value = {
            "status": 201,
            "response": {
                "id": "pref-123",
                "init_point": "https://mp.example/checkout",
            },
        }
        sdk.preference.return_value = preference_resource
        mock_sdk.return_value = sdk

        order = Order.objects.create(
            customer_name="Cliente Test",
            customer_email="cliente@test.com",
            shipping_type=Order.SHIPPING_HOME,
            shipping_method=Order.SHIPPING_METHOD_HOME,
            shipping_zone=Order.SHIPPING_ZONE_PROVINCE,
            shipping_cost=Decimal("500.00"),
            shipping_price=Decimal("500.00"),
            has_shipping=True,
            payment_method=Order.PAYMENT_MERCADOPAGO,
            discount_amount=Decimal("200.00"),
            subtotal=Decimal("3000.00"),
            total=Decimal("3300.00"),
        )
        OrderItem.objects.create(
            order=order,
            product_name="Producto A",
            unit_price=Decimal("1500.00"),
            quantity=2,
        )

        result = create_checkout_preference(order)

        payload = preference_resource.create.call_args[0][0]
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["quantity"], 1)
        self.assertEqual(payload["items"][0]["unit_price"], 3300.0)
        self.assertEqual(payload["metadata"]["shipping_amount"], "500.00")
        self.assertEqual(payload["metadata"]["discount_amount"], "200.00")
        self.assertEqual(payload["metadata"]["total_amount"], "3300.00")
        self.assertEqual(result["preference_id"], "pref-123")