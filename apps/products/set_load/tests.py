import json
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.catalog.models import CardSet, CatalogCard
from apps.products.models import TCG, BulkLoadReceipt, CardCondition, Product, ProductCategory

from .domain import (
    ATTRIBUTES,
    BatchInvalid,
    Existing,
    References,
    Row,
    fill_default_finishes,
    make_plan,
    validate_batch,
)

CARD = {"CardType": "Pokemon"}


class DomainTests(TestCase):
    refs = References(
        cards=frozenset({1, 2}),
        conditions=frozenset({10, 11}),
        finishes={1: ("Holofoil", "Reverse Holofoil"), 2: ()},
        set_languages={1: "en", 2: "ja"},
    )

    def row(self, **extra):
        return {"key": "r1", "card_id": 1, "kind": "single", "quantity": 2,
                "price_usd": "3.5", "condition_id": 10, **extra}

    def test_collects_every_bad_row_before_failing(self):
        with self.assertRaises(BatchInvalid) as ctx:
            validate_batch([
                self.row(key="a", condition_id=None),
                self.row(key="b", price_usd="0"),
                self.row(key="c", quantity="2.5"),
                self.row(key="d"),
            ], self.refs)
        self.assertEqual(set(ctx.exception.errors), {"a", "b", "c"})

    def test_sealed_does_not_need_condition_and_drops_it(self):
        rows = validate_batch([self.row(kind="sealed", condition_id=None, quantity=30)], self.refs)
        self.assertIsNone(rows[0].condition_id)
        self.assertEqual(rows[0].price_usd, Decimal("3.50"))

    def test_same_card_and_condition_twice_is_ambiguous(self):
        rows = validate_batch([self.row(key="a"), self.row(key="b")], self.refs)
        with self.assertRaises(BatchInvalid) as ctx:
            make_plan(rows, {})
        self.assertIn("b", ctx.exception.errors)

    def test_single_without_finish_takes_the_default_of_the_card(self):
        rows = fill_default_finishes(validate_batch([self.row()], self.refs), self.refs)
        self.assertEqual(rows[0].finish, "Holofoil")

    def test_reverse_and_first_edition_are_always_allowed(self):
        rows = validate_batch([
            self.row(key="a", card_id=2, finish="Reverse Holofoil"),
            self.row(key="b", card_id=2, finish="1st Edition"),
        ], self.refs)
        self.assertEqual([r.finish for r in rows], ["Reverse Holofoil", "1st Edition"])

    def test_finish_the_card_does_not_have_is_rejected(self):
        with self.assertRaises(BatchInvalid) as ctx:
            validate_batch([self.row(finish="Cold Foil")], self.refs)
        self.assertIn("r1", ctx.exception.errors)

    def test_attributes_must_be_real_booleans(self):
        with self.assertRaises(BatchInvalid):
            validate_batch([self.row(signed="false")], self.refs)

    def test_other_finish_or_attribute_is_another_listing(self):
        rows = fill_default_finishes(validate_batch([
            self.row(key="a"),
            self.row(key="b", finish="Reverse Holofoil"),
            self.row(key="c", signed=True),
        ], self.refs), self.refs)
        self.assertEqual(len(make_plan(rows, {}).creates), 3)

    def test_sealed_drops_finish_and_attributes(self):
        rows = validate_batch([self.row(kind="sealed", finish="Reverse Holofoil", signed=True)], self.refs)
        self.assertEqual((rows[0].finish, rows[0].attributes_dict["signed"]), ("", False))

    def test_language_defaults_to_the_set_and_japanese_is_forced(self):
        rows = validate_batch([
            self.row(key="a"),
            self.row(key="b", language="es"),
            self.row(key="c", card_id=2, language="es"),
        ], self.refs)
        self.assertEqual([r.language for r in rows], ["en", "es", "ja"])

    def test_japanese_cannot_be_chosen(self):
        with self.assertRaises(BatchInvalid):
            validate_batch([self.row(language="ja")], self.refs)

    def test_other_language_is_another_listing(self):
        rows = fill_default_finishes(validate_batch([
            self.row(key="a"), self.row(key="b", language="pt"),
        ], self.refs), self.refs)
        self.assertEqual(len(make_plan(rows, {}).creates), 2)

    def test_selectable_languages_match_the_product_model(self):
        from .domain import SELECTABLE_LANGUAGES
        self.assertEqual(SELECTABLE_LANGUAGES, Product.SELECTABLE_LANGUAGES)

    def test_attributes_match_the_product_model(self):
        self.assertEqual(ATTRIBUTES, tuple(f for f, _, _ in Product.ATTRIBUTES))

    def test_other_condition_is_another_listing(self):
        rows = validate_batch([self.row(key="a"), self.row(key="b", condition_id=11)], self.refs)
        self.assertEqual(len(make_plan(rows, {}).creates), 2)

    def test_existing_listing_gets_the_units_added(self):
        rows = fill_default_finishes(validate_batch([self.row()], self.refs), self.refs)
        plan = make_plan(rows, {rows[0].identity: Existing(product_id=99, stock=1)})
        self.assertEqual(plan.creates, [])
        self.assertEqual(plan.adds[0][1].product_id, 99)

    def test_own_copy_always_creates(self):
        rows = validate_batch([self.row(name="Charizard firmado")], self.refs)
        plan = make_plan(rows, {rows[0].identity: Existing(product_id=99, stock=1)})
        self.assertEqual(len(plan.creates), 1)
        self.assertIsInstance(plan.creates[0], Row)


class SetLoadApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username="admin", email="admin@test.com", password="x"
        )
        tcg = TCG.objects.create(name="Pokémon")
        cls.single = ProductCategory.objects.create(name="Single")
        cls.sealed = ProductCategory.objects.create(name="Sellado")
        cls.nm = CardCondition.objects.create(name="Near Mint", abbreviation="NM")
        cls.lp = CardCondition.objects.create(name="Lightly Played", abbreviation="LP")
        cls.card_set = CardSet.objects.create(tcg=tcg, external_id=1, name="Base Set", language="en")
        cls.charizard = CatalogCard.objects.create(
            card_set=cls.card_set, external_id=10, name="Charizard", number="4/102",
            rarity="Holo Rare", extended_data=CARD, printings=["Holofoil", "Reverse Holofoil"],
        )
        cls.blastoise = CatalogCard.objects.create(
            card_set=cls.card_set, external_id=11, name="Blastoise", number="2/102",
            rarity="Holo Rare", extended_data=CARD,
        )
        cls.booster = CatalogCard.objects.create(
            card_set=cls.card_set, external_id=12, name="Base Set Booster Pack", extended_data={},
        )

    def setUp(self):
        self.client.force_login(self.user)

    def save(self, items, request_id=None):
        return self.client.post(
            reverse("admin:products_product_set_load_save"),
            data=json.dumps({"request_id": request_id or str(uuid.uuid4()), "items": items}),
            content_type="application/json",
        )

    def item(self, card, **extra):
        return {"key": f"r{card.id}", "card_id": card.id, "kind": "single", "quantity": 1,
                "price_usd": 10, "condition_id": self.nm.id, **extra}

    def test_set_comes_whole_with_cards_sealed_and_stock(self):
        Product.objects.create(
            catalog_card=self.charizard, category=self.single, name="x", price_usd=5,
            condition=self.nm, stock_quantity=2,
        )
        res = self.client.get(reverse("admin:products_product_set_load", args=[self.card_set.id]))
        data = res.json()
        self.assertEqual(res.status_code, 200)
        by_id = {c["id"]: c for c in data["cards"]}
        self.assertTrue(by_id[self.charizard.id]["is_card"])
        self.assertFalse(by_id[self.booster.id]["is_card"])
        stock = data["stock"][str(self.charizard.id)]
        self.assertEqual(stock["units"], 2)
        self.assertEqual(stock["by_condition"], {str(self.nm.id): 2})

    def test_unknown_set_is_404(self):
        res = self.client.get(reverse("admin:products_product_set_load", args=[9999]))
        self.assertEqual(res.status_code, 404)

    def test_creates_one_listing_per_card_with_stock(self):
        res = self.save([
            self.item(self.charizard, quantity=3),
            self.item(self.blastoise),
            self.item(self.booster, kind="sealed", condition_id=None, quantity=12),
        ])
        data = res.json()
        self.assertEqual(res.status_code, 200, data)
        self.assertEqual((data["created"], data["updated"], data["units"]), (3, 0, 16))

        charizard = Product.objects.get(catalog_card=self.charizard)
        self.assertEqual(charizard.name, "Charizard 4/102 — Base Set")
        self.assertEqual(charizard.stock_quantity, 3)
        self.assertEqual(charizard.category, self.single)
        self.assertTrue(charizard.slug)
        self.assertEqual(Product.objects.get(catalog_card=self.booster).category, self.sealed)
        self.assertEqual(data["stock"][str(self.charizard.id)]["units"], 3)

    def test_same_card_and_condition_adds_to_the_listing(self):
        self.save([self.item(self.charizard, quantity=2, price_usd=10)])
        data = self.save([self.item(self.charizard, quantity=3, price_usd=12)]).json()
        self.assertEqual((data["created"], data["updated"]), (0, 1))
        product = Product.objects.get(catalog_card=self.charizard)
        self.assertEqual(product.stock_quantity, 5)
        self.assertEqual(product.price_usd, Decimal("12.00"))

    def test_finish_and_attributes_go_in_the_name_and_split_listings(self):
        data = self.save([
            self.item(self.charizard, key="a"),
            self.item(self.charizard, key="b", finish="Reverse Holofoil"),
            self.item(self.charizard, key="c", signed=True),
        ]).json()
        self.assertEqual(data["created"], 3, data)
        names = set(Product.objects.values_list("name", flat=True))
        self.assertEqual(names, {
            "Charizard 4/102 — Base Set",
            "Charizard 4/102 (Reverse Holo) — Base Set",
            "Charizard 4/102 (Firmada) — Base Set",
        })
        reverse = Product.objects.get(finish="Reverse Holofoil")
        self.assertFalse(reverse.signed)
        self.assertEqual(Product.objects.get(signed=True).finish, "Holofoil")
        # La segunda vez cada una suma a la suya.
        again = self.save([self.item(self.charizard, key="b", finish="Reverse Holofoil", quantity=2)]).json()
        self.assertEqual((again["created"], again["updated"]), (0, 1))
        reverse.refresh_from_db()
        self.assertEqual(reverse.stock_quantity, 3)
        self.assertEqual(again["stock"][str(self.charizard.id)]["by_finish"]["Reverse Holofoil"], 3)

    def test_language_is_saved_and_splits_listings(self):
        self.save([self.item(self.charizard, key="a"), self.item(self.charizard, key="b", language="es")])
        self.assertEqual(
            sorted(Product.objects.values_list("language", flat=True)), ["en", "es"]
        )
        data = self.save([self.item(self.charizard, key="b", language="es", quantity=2)]).json()
        self.assertEqual((data["created"], data["updated"]), (0, 1))
        self.assertEqual(data["stock"][str(self.charizard.id)]["by_language"], {"en": 1, "es": 3})

    def test_store_filters_by_language_finish_and_attribute(self):
        self.save([
            self.item(self.charizard, key="a"),
            self.item(self.charizard, key="b", language="es", finish="Reverse Holofoil"),
            self.item(self.blastoise, key="c", signed=True),
        ])
        def names(qs):
            res = self.client.get("/api/v1/products/?" + qs)
            return sorted(p["name"] for p in res.json()["results"])
        self.assertEqual(names("language=es"), ["Charizard 4/102 (Reverse Holo) — Base Set"])
        self.assertEqual(names("finish=reverse"), ["Charizard 4/102 (Reverse Holo) — Base Set"])
        self.assertEqual(names("attribute=signed"), ["Blastoise 2/102 (Firmada) — Base Set"])
        detail = self.client.get("/api/v1/products/?attribute=signed").json()["results"][0]
        self.assertEqual((detail["language"], detail["signed"], detail["finish"]), ("en", True, ""))

    def test_old_listing_without_finish_counts_as_the_default(self):
        Product.objects.create(
            catalog_card=self.charizard, category=self.single, name="Charizard 4/102 — Base Set",
            price_usd=5, condition=self.nm, stock_quantity=1,
        )
        data = self.save([self.item(self.charizard)]).json()
        self.assertEqual((data["created"], data["updated"]), (0, 1))

    def test_sold_out_listing_comes_back(self):
        self.save([self.item(self.charizard)])
        Product.objects.filter(catalog_card=self.charizard).update(stock_quantity=0, in_stock=False)
        self.save([self.item(self.charizard, quantity=2)])
        product = Product.objects.get(catalog_card=self.charizard)
        self.assertEqual((product.stock_quantity, product.in_stock), (2, True))

    def test_other_condition_is_a_new_listing(self):
        self.save([self.item(self.charizard)])
        self.save([self.item(self.charizard, condition_id=self.lp.id)])
        self.assertEqual(Product.objects.filter(catalog_card=self.charizard).count(), 2)

    def test_listing_with_own_photo_is_not_merged(self):
        Product.objects.create(
            catalog_card=self.charizard, category=self.single, name="Charizard 4/102 — Base Set",
            price_usd=50, condition=self.nm, stock_quantity=1, image_url="https://res.cloudinary.com/x/foto.jpg",
        )
        data = self.save([self.item(self.charizard)]).json()
        self.assertEqual((data["created"], data["updated"]), (1, 0))

    def test_same_request_id_never_saves_twice(self):
        request_id = str(uuid.uuid4())
        first = self.save([self.item(self.charizard, quantity=2)], request_id).json()
        second = self.save([self.item(self.charizard, quantity=2)], request_id).json()
        self.assertFalse(first["repeated"])
        self.assertTrue(second["repeated"])
        self.assertEqual(Product.objects.get(catalog_card=self.charizard).stock_quantity, 2)
        self.assertEqual(BulkLoadReceipt.objects.count(), 1)

    def test_invalid_rows_save_nothing_and_say_which(self):
        res = self.save([self.item(self.charizard), self.item(self.blastoise, condition_id=None)])
        self.assertEqual(res.status_code, 400)
        self.assertIn(f"r{self.blastoise.id}", res.json()["errors"])
        self.assertFalse(Product.objects.exists())

    def test_big_set_is_saved_in_a_handful_of_queries(self):
        cards = [
            CatalogCard.objects.create(
                card_set=self.card_set, external_id=1000 + i, name=f"Carta {i}",
                number=f"{i}/300", extended_data=CARD,
            )
            for i in range(300)
        ]
        with CaptureQueriesContext(connection) as ctx:
            res = self.save([self.item(c) for c in cards])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Product.objects.count(), 300)
        # Antes era un INSERT (y una o más consultas de slug) por producto.
        self.assertLess(len(ctx.captured_queries), 40)

    def test_page_renders_both_modes_with_config(self):
        res = self.client.get(reverse("admin:products_product_bulk_load"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn('id="cm-modes"', html)
        self.assertIn('id="cm-config"', html)
        self.assertIn("carga_masiva.js", html)
        config = json.loads(html.split('id="cm-config" type="application/json">', 1)[1].split("</script>", 1)[0])
        self.assertTrue(config["setUrl"].endswith("/carga-stock/set/0/"))
        self.assertEqual(config["maxRows"], 500)

    def test_needs_add_permission(self):
        staff = get_user_model().objects.create_user(
            username="mirón", email="miron@test.com", password="x", is_staff=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.save([self.item(self.charizard)]).status_code, 403)


class BulkLoadFastCreateTests(TestCase):
    """La carga individual también crea el lote con un solo bulk_create."""

    def test_individual_batch_creates_listings_with_slug_and_unique_names(self):
        user = get_user_model().objects.create_superuser(username="a", email="a@a.com", password="x")
        self.client.force_login(user)
        tcg = TCG.objects.create(name="Pokémon")
        single = ProductCategory.objects.create(name="Single")
        nm = CardCondition.objects.create(name="Near Mint", abbreviation="NM")
        card_set = CardSet.objects.create(tcg=tcg, external_id=1, name="Jungle", language="en")
        card = CatalogCard.objects.create(card_set=card_set, external_id=5, name="Pikachu", number="60/64")
        Product.objects.create(category=single, name="Pikachu 60/64 — Jungle", price_usd=1)

        item = {"card_id": card.id, "category_id": single.id, "price_usd": 2, "quantity": 1,
                "condition_id": nm.id}
        res = self.client.post(
            reverse("admin:products_product_bulk_save"),
            data=json.dumps({"items": [item, {**item, "condition_id": nm.id, "quantity": 2}]}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        slugs = sorted(Product.objects.values_list("slug", flat=True))
        self.assertEqual(slugs, ["pikachu-6064-jungle", "pikachu-6064-jungle-1", "pikachu-6064-jungle-2"])
        self.assertEqual(res.json()["units"], 3)
