from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.orders.mercadopago_service import create_checkout_preference
from apps.orders.models import DiscountCode, Order, OrderItem, ShippingConfig
from apps.orders.serializers import OrderCreateSerializer
from apps.orders.services import reconcile_payment
from apps.orders.tasks import expire_stale_cash_orders
from apps.orders.services.stock_reservation_service import (
    consume_order_stock,
    release_order_stock,
)
from apps.products.models import Product, ProductCategory, ProductImage
from apps.core.models import ExchangeRate, SiteConfig


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

class SingleStockTests(TestCase):
    """
    Un single repetido es UNA publicación con stock N.

    Tres Ampharos NM no son tres avisos en la tienda: es un aviso con stock 3,
    del que el cliente puede llevarse una, dos o las tres.
    """

    def setUp(self):
        self.category = ProductCategory.objects.create(name="Single")
        self.product = Product.objects.create(
            category=self.category,
            name="Ampharos NM",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=3,
        )

    def test_single_keeps_loaded_stock(self):
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)

    def test_single_without_quantity_defaults_to_one(self):
        product = Product.objects.create(
            category=self.category,
            name="Pikachu NM",
            price_usd=Decimal("5.00"),
            in_stock=True,
        )
        self.assertEqual(product.stock_quantity, 1)

    def _checkout(self, quantity):
        return OrderCreateSerializer(
            data={
                "customer_name": "Cliente Test",
                "customer_email": "cliente@test.com",
                "payment_method": Order.PAYMENT_CASH,
                "shipping_type": Order.SHIPPING_PICKUP,
                "shipping_method": Order.SHIPPING_METHOD_STORE_PICKUP,
                "items": [{"product_id": self.product.id, "quantity": quantity}],
            }
        )

    def test_cash_checkout_reserves_without_discounting(self):
        # El pago manual no se cobra en el momento: aparta, no vende.
        serializer = self._checkout(2)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.reserved_quantity, 2)
        self.assertEqual(self.product.available_quantity, 1)
        self.assertTrue(self.product.in_stock)
        self.assertEqual(order.stock_status, Order.STOCK_RESERVED)

    def test_cannot_buy_more_than_stock(self):
        serializer = self._checkout(4)

        self.assertFalse(serializer.is_valid())
        self.assertIn("3 unidades", str(serializer.errors))

    def test_reserving_everything_takes_it_out_of_the_shop(self):
        serializer = self._checkout(3)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.available_quantity, 0)
        self.assertFalse(self.product.in_stock)

    def test_reserved_units_are_not_available_for_a_second_buyer(self):
        first = self._checkout(2)
        self.assertTrue(first.is_valid(), first.errors)
        first.save()

        second = self._checkout(2)

        self.assertFalse(second.is_valid())
        self.assertIn("1 unidad", str(second.errors))

    def test_marking_paid_turns_the_reservation_into_a_sale(self):
        serializer = self._checkout(2)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        consume_order_stock(order)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)
        self.assertEqual(self.product.reserved_quantity, 0)
        self.assertTrue(self.product.in_stock)

    def test_marking_paid_twice_discounts_once(self):
        serializer = self._checkout(2)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        consume_order_stock(order)
        consume_order_stock(order)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)

    def test_releasing_a_reservation_puts_it_back_on_sale(self):
        serializer = self._checkout(3)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        release_order_stock(order)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.reserved_quantity, 0)
        self.assertTrue(self.product.in_stock)

    def test_releasing_a_paid_order_gives_the_units_back(self):
        serializer = self._checkout(2)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()
        consume_order_stock(order)

        release_order_stock(order)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.reserved_quantity, 0)

    def test_releasing_twice_does_not_inflate_stock(self):
        serializer = self._checkout(2)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        release_order_stock(order)
        release_order_stock(order)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.reserved_quantity, 0)


class MercadoPagoMultiUnitStockTests(TestCase):
    """
    Con MP el stock se descuenta recién cuando el pago queda aprobado. Si la
    orden lleva 2 unidades de un single con stock 3, tiene que quedar en 1 y
    seguir publicado, no despublicarse con la primera venta.
    """

    def test_paid_order_discounts_every_unit(self):
        category = ProductCategory.objects.create(name="Single")
        product = Product.objects.create(
            category=category,
            name="Ampharos NM",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=3,
        )
        order = Order.objects.create(
            customer_name="Cliente MP",
            customer_email="cliente-mp@test.com",
            shipping_type=Order.SHIPPING_PICKUP,
            shipping_method=Order.SHIPPING_METHOD_STORE_PICKUP,
            payment_method=Order.PAYMENT_MERCADOPAGO,
            subtotal=Decimal("200.00"),
            total=Decimal("200.00"),
            status=Order.STATUS_PENDING,
            mp_preference_id="pref-multi-1",
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            unit_price=Decimal("100.00"),
            quantity=2,
        )

        order, paid = reconcile_payment(
            {
                "id": "payment-multi-1",
                "external_reference": order.order_code,
                "status": "approved",
                "payment_method_id": "visa",
                "payment_type_id": "credit_card",
                "transaction_amount": "200.00",
                "metadata": {"preference_id": "pref-multi-1"},
            },
            source="test",
        )

        self.assertTrue(paid)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 1)
        self.assertTrue(product.in_stock)


class CashOrderExpirationTests(TestCase):
    """
    La reserva no es eterna: pasado el plazo del email, la mercadería vuelve a
    la tienda y la orden queda vencida.
    """

    def setUp(self):
        self.category = ProductCategory.objects.create(name="Single")
        self.product = Product.objects.create(
            category=self.category,
            name="Ampharos NM",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=2,
        )

    def _cash_order(self, quantity=2, age_hours=0):
        serializer = OrderCreateSerializer(
            data={
                "customer_name": "Cliente Test",
                "customer_email": "cliente@test.com",
                "payment_method": Order.PAYMENT_CASH,
                "shipping_type": Order.SHIPPING_PICKUP,
                "shipping_method": Order.SHIPPING_METHOD_STORE_PICKUP,
                "items": [{"product_id": self.product.id, "quantity": quantity}],
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        if age_hours:
            created = timezone.now() - timedelta(hours=age_hours)
            Order.objects.filter(pk=order.pk).update(created_at=created)
            order.refresh_from_db()

        return order

    @override_settings(CASH_ORDER_EXPIRATION_HOURS=24)
    def test_order_within_the_deadline_keeps_its_reservation(self):
        order = self._cash_order(age_hours=5)

        result = expire_stale_cash_orders()

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(result["expired"], 0)
        self.assertEqual(order.status, Order.STATUS_PENDING)
        self.assertEqual(self.product.reserved_quantity, 2)

    @override_settings(CASH_ORDER_EXPIRATION_HOURS=24)
    def test_expired_order_returns_the_stock_to_the_shop(self):
        order = self._cash_order(age_hours=30)

        result = expire_stale_cash_orders()

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(result["expired"], 1)
        self.assertEqual(order.status, Order.STATUS_EXPIRED)
        self.assertEqual(order.stock_status, Order.STOCK_RELEASED)
        self.assertEqual(self.product.reserved_quantity, 0)
        self.assertEqual(self.product.stock_quantity, 2)
        self.assertTrue(self.product.in_stock)

    @override_settings(CASH_ORDER_EXPIRATION_HOURS=24)
    def test_paid_order_is_never_expired(self):
        order = self._cash_order(age_hours=30)
        consume_order_stock(order)
        Order.objects.filter(pk=order.pk).update(status=Order.STATUS_PAID)

        result = expire_stale_cash_orders()

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(result["expired"], 0)
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertEqual(self.product.stock_quantity, 0)


class ReturnStockAdminTests(TestCase):
    """El botón "Regresar al stock" del admin: devuelve y cancela la orden."""

    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user(
            username="staff-orders",
            email="staff-orders@test.com",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.staff)

        category = ProductCategory.objects.create(name="Single")
        self.product = Product.objects.create(
            category=category,
            name="Ampharos NM",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=3,
        )

    def _cash_order(self, quantity=3):
        serializer = OrderCreateSerializer(
            data={
                "customer_name": "Cliente Test",
                "customer_email": "cliente@test.com",
                "payment_method": Order.PAYMENT_CASH,
                "shipping_type": Order.SHIPPING_PICKUP,
                "shipping_method": Order.SHIPPING_METHOD_STORE_PICKUP,
                "items": [{"product_id": self.product.id, "quantity": quantity}],
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_returns_a_reservation_and_cancels_the_order(self):
        order = self._cash_order()
        url = reverse("admin:orders_order_return_stock", args=[order.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_CANCELLED)
        self.assertEqual(self.product.reserved_quantity, 0)
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertTrue(self.product.in_stock)

    def test_returns_a_sale_that_was_already_paid(self):
        order = self._cash_order(quantity=2)
        consume_order_stock(order)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)

        self.client.get(reverse("admin:orders_order_return_stock", args=[order.pk]))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(self.product.reserved_quantity, 0)

    def test_marking_cash_paid_from_the_admin_discounts_the_reservation(self):
        order = self._cash_order(quantity=2)
        url = reverse("admin:orders_order_mark_cash_paid", args=[order.pk])

        self.client.get(url)

        order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
        self.assertEqual(self.product.stock_quantity, 1)
        self.assertEqual(self.product.reserved_quantity, 0)


class CardSurchargePricingTests(TestCase):
    """
    El precio publicado es el precio en efectivo. Pagar con Mercado Pago suma
    un recargo que se calcula SOLO sobre los productos, nunca sobre el envío.
    """

    def setUp(self):
        ExchangeRate.objects.update_or_create(pk=1, defaults={"usd_to_ars": Decimal("1000")})
        config = SiteConfig.get()
        config.card_surcharge_enabled = True
        config.card_surcharge_percent = Decimal("10.00")
        config.save()

        ShippingConfig.objects.update_or_create(
            key=ShippingConfig.KEY_HOME_PROVINCE,
            defaults={"price": Decimal("13000.00")},
        )

        self.category = ProductCategory.objects.create(name="Single")
        # price_usd 10 x cotizacion 1000 = $10.000 de precio en efectivo.
        self.product = Product.objects.create(
            category=self.category,
            name="Sorin TOPPS",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=5,
        )

    def _checkout(self, payment_method, quantity=1, discount_code="", pickup=False):
        data = {
            "customer_name": "Cliente Test",
            "customer_email": "cliente@test.com",
            "payment_method": payment_method,
            "items": [{"product_id": self.product.id, "quantity": quantity}],
        }
        if pickup:
            data.update({
                "shipping_type": Order.SHIPPING_PICKUP,
                "shipping_method": Order.SHIPPING_METHOD_STORE_PICKUP,
            })
        else:
            data.update({
                "shipping_type": Order.SHIPPING_HOME,
                "shipping_method": Order.SHIPPING_METHOD_HOME,
                "shipping_zone": Order.SHIPPING_ZONE_PROVINCE,
                "shipping_address": "Calle Falsa 123",
                "shipping_city": "Rosario",
                "shipping_province": "Santa Fe",
                "shipping_zip": "2000",
            })
        if discount_code:
            data["discount_code"] = discount_code

        serializer = OrderCreateSerializer(data=data)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        return serializer.save()

    def test_cash_order_pays_the_published_price_without_surcharge(self):
        order = self._checkout(Order.PAYMENT_CASH)

        self.assertEqual(order.subtotal, Decimal("10000.00"))
        self.assertEqual(order.card_surcharge_amount, Decimal("0"))
        self.assertEqual(order.card_surcharge_percent, Decimal("0"))
        self.assertEqual(order.total, Decimal("23000.00"))  # 10.000 + 13.000 de envio

    def test_mercadopago_surcharge_applies_only_to_products_not_shipping(self):
        order = self._checkout(Order.PAYMENT_MERCADOPAGO)

        # El recargo es sobre los $10.000 de productos, NO sobre los $13.000 de envio.
        self.assertEqual(order.card_surcharge_percent, Decimal("10.00"))
        self.assertEqual(order.card_surcharge_amount, Decimal("1000.00"))
        self.assertEqual(order.total, Decimal("24000.00"))

        # Si el recargo tocara el envio el total seria 25.300: lo dejamos explicito
        # para que un cambio futuro que mueva el calculo rompa el test.
        surcharge_over_everything = (order.subtotal + order.shipping_price) * Decimal("0.10")
        self.assertNotEqual(order.card_surcharge_amount, surcharge_over_everything)

    def test_surcharge_is_computed_after_the_coupon(self):
        DiscountCode.objects.create(
            code="CRACK20",
            discount_type=DiscountCode.DISCOUNT_PERCENT,
            discount_amount=Decimal("20"),
        )
        order = self._checkout(Order.PAYMENT_MERCADOPAGO, discount_code="CRACK20")

        # 10.000 - 20% = 8.000 -> recargo 800 -> total 8.000 + 800 + 13.000
        self.assertEqual(order.discount_amount, Decimal("2000.00"))
        self.assertEqual(order.card_surcharge_amount, Decimal("800.00"))
        self.assertEqual(order.total, Decimal("21800.00"))

    def test_discount_amount_no_longer_mixes_coupon_and_payment_adjustment(self):
        """El recargo viaja en su propio campo: discount_amount es solo el cupon."""
        DiscountCode.objects.create(
            code="FIJO500",
            discount_type=DiscountCode.DISCOUNT_FIXED,
            discount_amount=Decimal("500"),
        )
        order = self._checkout(Order.PAYMENT_MERCADOPAGO, discount_code="FIJO500")

        self.assertEqual(order.discount_amount, Decimal("500.00"))
        self.assertEqual(order.cash_discount_amount, Decimal("0"))
        self.assertEqual(order.card_surcharge_amount, Decimal("950.00"))

    def test_surcharge_can_be_turned_off_from_the_admin(self):
        config = SiteConfig.get()
        config.card_surcharge_enabled = False
        config.save()

        order = self._checkout(Order.PAYMENT_MERCADOPAGO)

        self.assertEqual(order.card_surcharge_amount, Decimal("0"))
        self.assertEqual(order.total, Decimal("23000.00"))

    def test_surcharge_percent_comes_from_the_admin_not_from_a_constant(self):
        config = SiteConfig.get()
        config.card_surcharge_percent = Decimal("25.00")
        config.save()

        order = self._checkout(Order.PAYMENT_MERCADOPAGO)

        self.assertEqual(order.card_surcharge_percent, Decimal("25.00"))
        self.assertEqual(order.card_surcharge_amount, Decimal("2500.00"))

    def test_pickup_order_has_no_shipping_to_surcharge(self):
        order = self._checkout(Order.PAYMENT_MERCADOPAGO, pickup=True)

        self.assertEqual(order.shipping_price, Decimal("0"))
        self.assertEqual(order.card_surcharge_amount, Decimal("1000.00"))
        self.assertEqual(order.total, Decimal("11000.00"))


class CheckoutPriceTamperingTests(TestCase):
    """El cliente solo manda product_id + quantity: los precios los pone el server."""

    def setUp(self):
        ExchangeRate.objects.update_or_create(pk=1, defaults={"usd_to_ars": Decimal("1000")})
        config = SiteConfig.get()
        config.card_surcharge_enabled = True
        config.card_surcharge_percent = Decimal("10.00")
        config.save()

        self.category = ProductCategory.objects.create(name="Single")
        self.product = Product.objects.create(
            category=self.category,
            name="Sorin TOPPS",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=5,
        )

    def _payload(self, **overrides):
        data = {
            "customer_name": "Cliente Test",
            "customer_email": "cliente@test.com",
            "payment_method": Order.PAYMENT_MERCADOPAGO,
            "shipping_type": Order.SHIPPING_PICKUP,
            "shipping_method": Order.SHIPPING_METHOD_STORE_PICKUP,
            "items": [{"product_id": self.product.id, "quantity": 1}],
        }
        data.update(overrides)
        return data

    def test_client_supplied_prices_are_ignored(self):
        serializer = OrderCreateSerializer(data=self._payload(
            subtotal="1.00",
            total="1.00",
            card_surcharge_amount="0",
            card_surcharge_percent="0",
            items=[{"product_id": self.product.id, "quantity": 1, "unit_price": "1.00"}],
        ))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        self.assertEqual(order.subtotal, Decimal("10000.00"))
        self.assertEqual(order.card_surcharge_amount, Decimal("1000.00"))
        self.assertEqual(order.total, Decimal("11000.00"))
        self.assertEqual(order.items.first().unit_price, Decimal("10000.00"))

    def test_unknown_discount_code_does_not_discount(self):
        serializer = OrderCreateSerializer(data=self._payload(discount_code="NOEXISTE"))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        self.assertEqual(order.discount_amount, Decimal("0"))
        self.assertEqual(order.total, Decimal("11000.00"))

    def test_expired_discount_code_does_not_discount(self):
        DiscountCode.objects.create(
            code="VENCIDO",
            discount_type=DiscountCode.DISCOUNT_PERCENT,
            discount_amount=Decimal("50"),
            expiration_type=DiscountCode.EXPIRATION_DATE,
            valid_from=timezone.now() - timedelta(days=10),
            valid_until=timezone.now() - timedelta(days=1),
        )
        serializer = OrderCreateSerializer(data=self._payload(discount_code="VENCIDO"))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        self.assertEqual(order.discount_amount, Decimal("0"))
        self.assertEqual(order.total, Decimal("11000.00"))

    @override_settings(
        MERCADOPAGO_ACCESS_TOKEN="test-token",
        FRONTEND_URL="https://front.example",
        BACKEND_PUBLIC_URL="https://api.example",
    )
    @patch("apps.orders.mercadopago_service._sdk")
    def test_mercadopago_preference_charges_the_total_with_surcharge(self, mock_sdk):
        sdk = Mock()
        preference_resource = Mock()
        preference_resource.create.return_value = {
            "status": 201,
            "response": {"id": "pref-abc", "init_point": "https://mp.example/checkout"},
        }
        sdk.preference.return_value = preference_resource
        mock_sdk.return_value = sdk

        serializer = OrderCreateSerializer(data=self._payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        order = serializer.save()

        create_checkout_preference(order)

        payload = preference_resource.create.call_args[0][0]
        self.assertEqual(payload["items"][0]["unit_price"], 11000.0)
        self.assertEqual(payload["metadata"]["card_surcharge_amount"], "1000.00")


class MercadoPagoUnderpaymentTests(TestCase):
    """MP no puede aprobar una orden pagando menos que el total con recargo."""

    def setUp(self):
        self.category = ProductCategory.objects.create(name="Single")
        self.product = Product.objects.create(
            category=self.category,
            name="Sorin TOPPS",
            price_usd=Decimal("10.00"),
            in_stock=True,
            stock_quantity=5,
        )
        self.order = Order.objects.create(
            customer_name="Cliente Test",
            customer_email="cliente@test.com",
            shipping_type=Order.SHIPPING_PICKUP,
            shipping_method=Order.SHIPPING_METHOD_STORE_PICKUP,
            payment_method=Order.PAYMENT_MERCADOPAGO,
            subtotal=Decimal("10000.00"),
            card_surcharge_percent=Decimal("10.00"),
            card_surcharge_amount=Decimal("1000.00"),
            total=Decimal("11000.00"),
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            unit_price=Decimal("10000.00"),
            quantity=1,
        )

    def _payment_data(self, amount):
        return {
            "id": "pay-1",
            "status": "approved",
            "external_reference": self.order.order_code,
            "transaction_amount": str(amount),
            "payment_method_id": "visa",
            "payment_type_id": "credit_card",
            "transaction_details": {"net_received_amount": str(amount)},
            "metadata": {"order_code": self.order.order_code},
        }

    def test_paying_the_cash_price_does_not_mark_the_order_as_paid(self):
        # El atacante paga $10.000 (precio en efectivo) una orden de $11.000.
        order, paid = reconcile_payment(self._payment_data("10000.00"), source="webhook")

        self.assertFalse(paid)
        order.refresh_from_db()
        self.assertNotEqual(order.status, Order.STATUS_PAID)

    def test_paying_the_full_total_marks_the_order_as_paid(self):
        order, paid = reconcile_payment(self._payment_data("11000.00"), source="webhook")

        self.assertTrue(paid)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.STATUS_PAID)
