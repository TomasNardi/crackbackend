from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from apps.orders.mercadopago_service import create_checkout_preference
from apps.orders.models import Order, OrderItem
from apps.orders.serializers import OrderCreateSerializer
from apps.orders.services import reconcile_payment
from apps.products.models import Product, ProductCategory, ProductImage


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


class OrderProductImageIntegrityTests(TestCase):
    def setUp(self):
        self.single_category = ProductCategory.objects.create(name="Single")

    def _create_product(self):
        product = Product.objects.create(
            category=self.single_category,
            name="Charizard Test",
            price_usd=Decimal("100.00"),
            in_stock=True,
            stock_quantity=1,
            image_url="https://cdn.example.com/charizard-main.jpg",
            image_url_2="https://cdn.example.com/charizard-2.jpg",
            image_url_3="https://cdn.example.com/charizard-3.jpg",
        )
        image = ProductImage.objects.create(
            product=product,
            secure_url="https://cdn.example.com/gallery-charizard.jpg",
            source=ProductImage.SOURCE_URL,
            order_index=0,
            status=ProductImage.STATUS_CONFIRMED,
            draft_token="legacy-import",
        )
        return product, image

    def test_cash_checkout_does_not_remove_product_images(self):
        product, image = self._create_product()

        serializer = OrderCreateSerializer(
            data={
                "customer_name": "Cliente Test",
                "customer_email": "cliente@test.com",
                "payment_method": Order.PAYMENT_CASH,
                "shipping_type": Order.SHIPPING_PICKUP,
                "shipping_method": Order.SHIPPING_METHOD_STORE_PICKUP,
                "items": [{"product_id": product.id, "quantity": 1}],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        product.refresh_from_db()
        self.assertEqual(product.image_url, "https://cdn.example.com/charizard-main.jpg")
        self.assertEqual(product.image_url_2, "https://cdn.example.com/charizard-2.jpg")
        self.assertEqual(product.image_url_3, "https://cdn.example.com/charizard-3.jpg")
        self.assertTrue(ProductImage.objects.filter(pk=image.pk, product=product).exists())

    def test_mercadopago_confirmation_does_not_remove_product_images(self):
        product, image = self._create_product()

        order = Order.objects.create(
            customer_name="Cliente MP",
            customer_email="cliente-mp@test.com",
            shipping_type=Order.SHIPPING_PICKUP,
            shipping_method=Order.SHIPPING_METHOD_STORE_PICKUP,
            shipping_zone="",
            shipping_cost=Decimal("0.00"),
            shipping_price=Decimal("0.00"),
            has_shipping=False,
            payment_method=Order.PAYMENT_MERCADOPAGO,
            subtotal=Decimal("100.00"),
            total=Decimal("100.00"),
            status=Order.STATUS_PENDING,
            mp_preference_id="pref-test-123",
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit_price=Decimal("100.00"),
            quantity=1,
        )

        order, paid = reconcile_payment(
            {
                "id": "payment-123",
                "external_reference": order.order_code,
                "status": "approved",
                "payment_method_id": "visa",
                "payment_type_id": "credit_card",
                "transaction_amount": "100.00",
                "transaction_details": {"net_received_amount": "90.00"},
                "metadata": {"preference_id": "pref-test-123"},
            },
            source="test",
        )

        self.assertTrue(paid)
        product.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertEqual(product.image_url, "https://cdn.example.com/charizard-main.jpg")
        self.assertEqual(product.image_url_2, "https://cdn.example.com/charizard-2.jpg")
        self.assertEqual(product.image_url_3, "https://cdn.example.com/charizard-3.jpg")
        self.assertTrue(ProductImage.objects.filter(pk=image.pk, product=product).exists())


class OrderShippingValidationTests(TestCase):
    def setUp(self):
        category = ProductCategory.objects.create(name="Single")
        self.product = Product.objects.create(
            category=category,
            name="Test Card",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=5,
        )

    def test_pickup_shipping_type_overrides_stale_shipping_method(self):
        serializer = OrderCreateSerializer(
            data={
                "customer_name": "Cliente Pickup",
                "customer_email": "pickup@test.com",
                "shipping_type": Order.SHIPPING_PICKUP,
                "shipping_method": Order.SHIPPING_METHOD_BRANCH_EXPRESS,
                "items": [{"product_id": self.product.id, "quantity": 1}],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["shipping_method"],
            Order.SHIPPING_METHOD_STORE_PICKUP,
        )
        self.assertEqual(
            serializer.validated_data["shipping_type"],
            Order.SHIPPING_PICKUP,
        )

    def test_branch_express_is_valid_for_shipping(self):
        serializer = OrderCreateSerializer(
            data={
                "customer_name": "Cliente Sucursal",
                "customer_email": "sucursal@test.com",
                "shipping_type": Order.SHIPPING_HOME,
                "shipping_method": Order.SHIPPING_METHOD_BRANCH_EXPRESS,
                "shipping_province": "Buenos Aires",
                "shipping_branch": "Sucursal Andreani Palermo",
                "items": [{"product_id": self.product.id, "quantity": 1}],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)