"""Tests de la velocidad del admin y la tienda (ver apps/core/admin_performance.py)."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.forms import CheckboxInput, HiddenInput, NumberInput
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import CardSet, CatalogCard
from apps.core.models import ExchangeRate
from apps.products.models import TCG, Product, ProductCategory

from .admin_performance import _speed_up_widget


class AdminQueryCountTests(TestCase):
    """Las páginas no pueden volver a hacer una consulta por fila."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@test.com", password="x"
        )
        tcg = TCG.objects.create(name="Pokémon")
        category = ProductCategory.objects.create(name="Single")
        for i in range(30):
            Product.objects.create(tcg=tcg, category=category, name=f"Carta {i}", price_usd=1, stock_quantity=1)
        for i in range(20):
            card_set = CardSet.objects.create(tcg=tcg, external_id=i, name=f"Set {i}", language="en")
            CatalogCard.objects.create(card_set=card_set, external_id=1000 + i, name=f"C{i}")

    def setUp(self):
        self.client.force_login(self.user)

    def queries_for(self, url):
        self.client.get(url)   # calienta las cachés de proceso
        with CaptureQueriesContext(connection) as ctx:
            res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        return len(ctx.captured_queries)

    def test_product_list_does_not_query_per_row(self):
        self.assertLess(self.queries_for("/admin/products/product/"), 15)

    def test_card_set_list_counts_cards_in_one_query(self):
        self.assertLess(self.queries_for("/admin/catalog/cardset/"), 12)

    def test_store_product_list_does_not_read_the_rate_per_product(self):
        self.assertLess(self.queries_for("/api/v1/products/?in_stock=true"), 8)


class ExchangeRateCacheTests(TestCase):
    def setUp(self):
        ExchangeRate._cached = None

    def test_saving_the_rate_refreshes_prices_at_once(self):
        ExchangeRate.objects.create(usd_to_ars=Decimal("1000"))
        category = ProductCategory.objects.create(name="Single")
        product = Product.objects.create(category=category, name="X", price_usd=2)
        self.assertEqual(product.price_ars, Decimal("2000"))

        rate = ExchangeRate.get()
        rate.usd_to_ars = Decimal("1500")
        rate.save()
        self.assertEqual(product.price_ars, Decimal("3000"))

    def test_rate_is_read_once_while_cached(self):
        ExchangeRate.get()
        with CaptureQueriesContext(connection) as ctx:
            for _ in range(10):
                ExchangeRate.get()
        self.assertEqual(len(ctx.captured_queries), 0)


class FastWidgetTests(TestCase):
    """El render rápido de las filas editables da el mismo HTML que el normal."""

    def assert_same_html(self, widget_class, name, value, attrs):
        normal = widget_class().render(name, value, attrs=attrs)
        fast_widget = widget_class()
        _speed_up_widget(fast_widget)
        # Dos veces: la primera arma la plantilla, la segunda la reusa.
        fast_widget.render("otro-0-campo", value, attrs={"id": "id_otro"})
        self.assertHTMLEqual(fast_widget.render(name, value, attrs=attrs), normal)

    def test_number_input(self):
        self.assert_same_html(NumberInput, "form-3-stock_quantity", 7, {"id": "id_form-3-stock_quantity"})

    def test_checkbox_checked_and_unchecked(self):
        self.assert_same_html(CheckboxInput, "form-1-in_stock", True, {"id": "id_form-1-in_stock"})
        self.assert_same_html(CheckboxInput, "form-2-in_stock", False, {"id": "id_form-2-in_stock"})

    def test_hidden_pk_escapes_the_value(self):
        self.assert_same_html(HiddenInput, "form-0-id", '5"><script>', {"id": "id_form-0-id"})
