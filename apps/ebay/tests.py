"""
Tests de importación eBay.

La fórmula y la resolución de links se prueban solas. Lo que toca la red se
cubre parcheando `get_item`, para que la suite no dependa de eBay ni de tener
credenciales cargadas.
"""

from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.ebay.models import EbayConfig, EbayOrder
from apps.ebay.services import ebay_client
from apps.ebay.services.ebay_client import (
    EbayInvalidUrl,
    EbayItemUnavailable,
    extract_item_id,
    normalize_url,
)
from apps.ebay.services.order_service import OrderBlocked, create_order
from apps.ebay.services.pricing import build_breakdown, sum_breakdowns
from apps.ebay.services.quote_service import QuoteRejected, quote_item


def fake_item(**overrides):
    item = {
        "item_id": "188836541819",
        "title": "Pokemon TCG 151 ETB Snorlax SEALED",
        "image_url": "https://i.ebayimg.com/x.jpg",
        "price": Decimal("548.99"),
        "currency": "USD",
        "shipping": Decimal("6.99"),
        "has_shipping_info": True,
        "item_web_url": "https://www.ebay.com/itm/188836541819",
        "buying_option": "FIXED_PRICE",
        "buying_options": ["FIXED_PRICE"],
        "available": True,
        "seller": "seller",
        "condition": "New",
        "is_mock": False,
    }
    item.update(overrides)
    return item


class PricingTests(TestCase):
    def test_matches_reference_breakdown(self):
        """Los números de la calculadora de referencia, al centavo."""
        breakdown = build_breakdown(
            price=Decimal("548.99"),
            ebay_shipping=Decimal("6.99"),
            arg_shipping=Decimal("3.00"),
            commission_percent=Decimal("10"),
            tax_percent=Decimal("7"),
        )

        self.assertEqual(breakdown["commission"], Decimal("54.90"))
        self.assertEqual(breakdown["tax"], Decimal("38.43"))
        self.assertEqual(breakdown["item_with_fees"], Decimal("642.32"))
        self.assertEqual(breakdown["unit_total"], Decimal("652.31"))

    def test_quantity_multiplies_every_component(self):
        breakdown = build_breakdown(
            price=Decimal("100"), ebay_shipping=Decimal("10"), arg_shipping=Decimal("3"),
            commission_percent=Decimal("10"), tax_percent=Decimal("7"), quantity=3,
        )
        self.assertEqual(breakdown["unit_total"], Decimal("130.00"))
        self.assertEqual(breakdown["line_total"], Decimal("390.00"))

    def test_totals_add_up(self):
        lines = [
            build_breakdown(price=Decimal("100"), ebay_shipping=Decimal("5"),
                            arg_shipping=Decimal("3"), commission_percent=Decimal("10"),
                            tax_percent=Decimal("7"), quantity=2),
            build_breakdown(price=Decimal("50"), ebay_shipping=Decimal("0"),
                            arg_shipping=Decimal("20"), commission_percent=Decimal("10"),
                            tax_percent=Decimal("7"), quantity=1),
        ]
        totals = sum_breakdowns(lines)

        self.assertEqual(totals["items_total"], Decimal("250.00"))
        self.assertEqual(totals["commission_total"], Decimal("25.00"))
        self.assertEqual(totals["arg_shipping_total"], Decimal("26.00"))
        self.assertEqual(
            totals["total"],
            totals["items_total"] + totals["commission_total"] + totals["tax_total"]
            + totals["ebay_shipping_total"] + totals["arg_shipping_total"],
        )


class UrlParsingTests(TestCase):
    def test_accepts_the_shapes_people_actually_paste(self):
        cases = [
            "https://www.ebay.com/itm/188836541819",
            "https://www.ebay.com/itm/188836541819?_skw=pokemon+151&itmmeta=01ABC",
            "https://www.ebay.com/itm/pokemon-tcg-151-etb/188836541819",
            "www.ebay.com/itm/188836541819",
            "188836541819",
        ]
        for url in cases:
            with self.subTest(url=url):
                self.assertEqual(extract_item_id(url), "188836541819")

    def test_rejects_other_domains(self):
        with self.assertRaises(EbayInvalidUrl):
            normalize_url("https://www.mercadolibre.com.ar/p/123456789")

    def test_rejects_link_without_item_id(self):
        with self.assertRaises(EbayInvalidUrl):
            extract_item_id("https://www.ebay.com/sch/i.html?_nkw=pokemon")


class QuoteServiceTests(TestCase):
    def setUp(self):
        self.config = EbayConfig.get()

    @patch("apps.ebay.services.quote_service.get_item")
    def test_arg_shipping_comes_from_config(self, mocked):
        """El envío es único: no importa si es suelta, calificada o sellada."""
        mocked.return_value = fake_item()
        self.config.arg_shipping = Decimal("15.00")
        self.config.save()

        quoted = quote_item("https://www.ebay.com/itm/188836541819")
        self.assertEqual(quoted["quote"]["arg_shipping"], Decimal("15.00"))

    @patch("apps.ebay.services.quote_service.get_item")
    def test_auction_is_rejected(self, mocked):
        mocked.return_value = fake_item(buying_option="AUCTION", buying_options=["AUCTION"])

        with self.assertRaises(QuoteRejected) as ctx:
            quote_item("https://www.ebay.com/itm/188836541819")
        self.assertEqual(ctx.exception.code, "auction_not_supported")

    @patch("apps.ebay.services.quote_service.get_item")
    def test_non_usd_is_rejected(self, mocked):
        mocked.return_value = fake_item(currency="EUR")

        with self.assertRaises(QuoteRejected) as ctx:
            quote_item("https://www.ebay.com/itm/188836541819")
        self.assertEqual(ctx.exception.code, "currency_not_supported")

    @patch("apps.ebay.services.quote_service.get_item")
    def test_sold_out_is_rejected(self, mocked):
        mocked.return_value = fake_item(available=False)

        with self.assertRaises(EbayItemUnavailable):
            quote_item("https://www.ebay.com/itm/188836541819")

    @patch("apps.ebay.services.quote_service.get_item")
    def test_quantity_is_capped_by_config(self, mocked):
        mocked.return_value = fake_item()
        self.config.max_quantity_per_item = 2
        self.config.save()

        quoted = quote_item("https://www.ebay.com/itm/188836541819", quantity=99)
        self.assertEqual(quoted["quote"]["quantity"], 2)


class OrderCreationTests(TestCase):
    def setUp(self):
        config = EbayConfig.get()
        config.arg_shipping = Decimal("3.00")
        config.save()
        self.payload = {
            "customer_name": "Tomás",
            "customer_email": "tomas@example.com",
            "customer_phone": "1150588131",
            "delivery_type": EbayOrder.DELIVERY_PICKUP,
            "shipping_address": "", "shipping_city": "", "shipping_province": "",
            "shipping_zip": "", "shipping_branch": "", "customer_notes": "",
            "items": [{
                "url": "https://www.ebay.com/itm/188836541819",
                "quantity": 1,
                "quoted_price": Decimal("548.99"),
            }],
        }

    @patch("apps.ebay.services.quote_service.get_item")
    def test_totals_come_from_the_server(self, mocked):
        mocked.return_value = fake_item()

        order = create_order(dict(self.payload))

        self.assertEqual(order.status, EbayOrder.STATUS_PENDING)
        self.assertEqual(order.total, Decimal("652.31"))
        self.assertEqual(order.commission_percent, Decimal("10.00"))
        self.assertFalse(order.has_price_changes)
        self.assertEqual(len(order.order_code), 6)

    @patch("apps.ebay.services.quote_service.get_item")
    def test_price_change_is_recorded_but_does_not_block(self, mocked):
        mocked.return_value = fake_item(price=Decimal("600.00"))

        order = create_order(dict(self.payload))
        item = order.items.first()

        self.assertTrue(order.has_price_changes)
        self.assertTrue(item.price_changed)
        self.assertEqual(item.original_price, Decimal("548.99"))
        self.assertEqual(item.price, Decimal("600.00"))
        # El total sigue al precio real, no al que mandó el front.
        self.assertEqual(order.items_total, Decimal("600.00"))

    @patch("apps.ebay.services.quote_service.get_item")
    def test_sold_out_blocks_the_order_but_keeps_the_record(self, mocked):
        mocked.return_value = fake_item(available=False)

        with self.assertRaises(OrderBlocked) as ctx:
            create_order(dict(self.payload))

        blocked = ctx.exception.order
        self.assertIsNotNone(blocked)
        # Sobrevive fuera de la transacción del pedido bueno: es el historial.
        self.assertTrue(EbayOrder.objects.filter(pk=blocked.pk).exists())
        self.assertEqual(blocked.status, EbayOrder.STATUS_BLOCKED)
        self.assertIn("disponible", blocked.block_reason)
        self.assertEqual(blocked.items.count(), 0)


class ApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        config = EbayConfig.get()
        config.arg_shipping = Decimal("3.00")
        config.save()

    def test_config_endpoint_is_public(self):
        response = self.client.get(reverse("ebay_config"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("arg_shipping", response.data)
        self.assertEqual(len(response.data["delivery_types"]), 3)

    @patch("apps.ebay.services.quote_service.get_item")
    def test_quote_endpoint(self, mocked):
        mocked.return_value = fake_item()

        response = self.client.post(reverse("ebay_quote"), {
            "url": "https://www.ebay.com/itm/188836541819",
        }, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Decimal(response.data["quote"]["unit_total"]), Decimal("652.31"))

    def test_quote_endpoint_rejects_a_non_ebay_link(self):
        response = self.client.post(reverse("ebay_quote"), {
            "url": "https://www.amazon.com/dp/B01",
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "invalid_url")

    @patch("apps.ebay.services.quote_service.get_item")
    def test_create_and_track_order(self, mocked):
        mocked.return_value = fake_item()

        created = self.client.post(reverse("ebay_order_create"), {
            "customer_name": "Tomás",
            "customer_email": "tomas@example.com",
            "delivery_type": "pickup",
            "items": [{"url": "https://www.ebay.com/itm/188836541819", "quantity": 1}],
        }, format="json")

        self.assertEqual(created.status_code, 201)
        code = created.data["order_code"]

        tracked = self.client.get(reverse("ebay_order_detail", args=[code]))
        self.assertEqual(tracked.status_code, 200)
        self.assertEqual(tracked.data["status"], EbayOrder.STATUS_PENDING)
        # El seguimiento es solo por código: nada de datos de contacto.
        self.assertNotIn("customer_email", tracked.data)
        self.assertNotIn("customer_phone", tracked.data)

    def test_home_delivery_requires_an_address(self):
        response = self.client.post(reverse("ebay_order_create"), {
            "customer_name": "Tomás",
            "customer_email": "tomas@example.com",
            "delivery_type": "home",
            "items": [{"url": "https://www.ebay.com/itm/188836541819"}],
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("shipping_address", response.data)

    @patch("apps.ebay.services.quote_service.get_item")
    def test_sold_out_returns_409_with_the_offending_index(self, mocked):
        mocked.return_value = fake_item(available=False)

        response = self.client.post(reverse("ebay_order_create"), {
            "customer_name": "Tomás",
            "customer_email": "tomas@example.com",
            "delivery_type": "pickup",
            "items": [{"url": "https://www.ebay.com/itm/188836541819"}],
        }, format="json")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "order_blocked")
        self.assertEqual(response.data["item_index"], 0)

    def test_unknown_code_is_a_404(self):
        response = self.client.get(reverse("ebay_order_detail", args=["ZZZZZZ"]))
        self.assertEqual(response.status_code, 404)

    @patch("apps.ebay.services.quote_service.get_item")
    def test_blocked_orders_are_not_publicly_visible(self, mocked):
        mocked.return_value = fake_item(available=False)
        try:
            create_order({
                "customer_name": "Tomás", "customer_email": "t@example.com",
                "customer_phone": "", "delivery_type": "pickup",
                "shipping_address": "", "shipping_city": "", "shipping_province": "",
                "shipping_zip": "", "shipping_branch": "", "customer_notes": "",
                "items": [{"url": "https://www.ebay.com/itm/188836541819",
                           "quantity": 1, "quoted_price": None}],
            })
        except OrderBlocked as exc:
            code = exc.order.order_code

        response = self.client.get(reverse("ebay_order_detail", args=[code]))
        self.assertEqual(response.status_code, 404)


class WorkflowTests(TestCase):
    def setUp(self):
        EbayConfig.get()
        self.order = EbayOrder.objects.create(
            customer_name="Tomás", customer_email="t@example.com", total=Decimal("100"),
        )

    def test_mark_stamps_the_step(self):
        self.order.mark(EbayOrder.STATUS_APPROVED)
        self.order.refresh_from_db()

        self.assertEqual(self.order.status, EbayOrder.STATUS_APPROVED)
        self.assertIsNotNone(self.order.approved_at)
        self.assertIsNone(self.order.payment_received_at)

    def test_mark_does_not_move_a_timestamp_already_set(self):
        self.order.mark(EbayOrder.STATUS_APPROVED)
        first = EbayOrder.objects.get(pk=self.order.pk).approved_at

        self.order.mark(EbayOrder.STATUS_APPROVED)
        self.assertEqual(EbayOrder.objects.get(pk=self.order.pk).approved_at, first)


class MockModeTests(TestCase):
    def test_mock_mode_is_on_without_credentials(self):
        with self.settings(EBAY_CLIENT_ID="", EBAY_CLIENT_SECRET=""):
            self.assertTrue(ebay_client.is_mock_mode())

    def test_mock_returns_a_usable_item(self):
        with self.settings(EBAY_MOCK=True):
            item = ebay_client.get_item("188836541819")

        self.assertTrue(item["is_mock"])
        self.assertEqual(item["currency"], "USD")
        self.assertGreater(item["price"], 0)
