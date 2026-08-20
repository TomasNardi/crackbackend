from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.core.management import call_command
from django.test import RequestFactory, TestCase

from apps.orders.models import Order, OrderItem
from apps.products.admin import ProductAdmin
from apps.products.models import CardCondition, Product, ProductCategory, ProductImage


class ProductAdminImagePayloadTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().post("/admin/products/product/1/change/")
        self.admin = ProductAdmin(Product, AdminSite())
        self.category = ProductCategory.objects.create(name="Single")
        self.product = Product.objects.create(
            category=self.category,
            name="Producto Test",
            price_usd="10.00",
            in_stock=True,
            stock_quantity=1,
            image_url="https://cdn.example.com/main.jpg",
            image_url_2="https://cdn.example.com/second.jpg",
            image_url_3="https://cdn.example.com/third.jpg",
        )
        self.image = ProductImage.objects.create(
            product=self.product,
            secure_url="https://cdn.example.com/gallery.jpg",
            source=ProductImage.SOURCE_URL,
            order_index=0,
            status=ProductImage.STATUS_CONFIRMED,
            draft_token="seed",
        )

    @patch("apps.products.admin.attach_images_to_product")
    def test_save_model_skips_sync_when_payload_field_absent(self, mock_attach):
        form = SimpleNamespace(cleaned_data={"in_stock": False})

        self.product.in_stock = False
        self.admin.save_model(self.request, self.product, form, change=True)

        self.product.refresh_from_db()
        self.assertEqual(self.product.image_url, "https://cdn.example.com/main.jpg")
        self.assertTrue(ProductImage.objects.filter(pk=self.image.pk).exists())
        mock_attach.assert_not_called()

    @patch("apps.products.admin.attach_images_to_product")
    def test_save_model_skips_sync_when_payload_empty(self, mock_attach):
        form = SimpleNamespace(cleaned_data={"images_payload": "[]", "cloudinary_draft_token": ""})

        self.admin.save_model(self.request, self.product, form, change=True)

        self.product.refresh_from_db()
        self.assertEqual(self.product.image_url, "https://cdn.example.com/main.jpg")
        self.assertTrue(ProductImage.objects.filter(pk=self.image.pk).exists())
        mock_attach.assert_not_called()

    @patch("apps.products.admin.attach_images_to_product")
    def test_save_model_syncs_when_payload_has_ids(self, mock_attach):
        form = SimpleNamespace(
            cleaned_data={
                "images_payload": f"[{{\"id\": {self.image.id}}}]",
                "cloudinary_draft_token": "draft-123",
            }
        )

        self.admin.save_model(self.request, self.product, form, change=True)

        mock_attach.assert_called_once_with(
            product=self.product,
            draft_token="draft-123",
            ordered_image_ids=[self.image.id],
        )


class MergeDuplicateProductsCommandTests(TestCase):
    """
    Lo ya cargado con el criterio viejo (una publicación por copia) tiene que
    poder juntarse sin perder ni stock ni el historial de compras.
    """

    def setUp(self):
        self.category = ProductCategory.objects.create(name="Single")
        self.condition_nm = CardCondition.objects.create(name="Near Mint", abbreviation="NM")
        self.condition_lp = CardCondition.objects.create(name="Lightly Played", abbreviation="LP")

    def _create(self, condition, price="10.00", name="Ampharos 090/086"):
        return Product.objects.create(
            category=self.category,
            name=name,
            price_usd=price,
            condition=condition,
            in_stock=True,
        )

    def _run(self, *args):
        out = StringIO()
        call_command("merge_duplicate_products", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_does_not_touch_anything(self):
        for _ in range(3):
            self._create(self.condition_nm)

        output = self._run()

        self.assertEqual(Product.objects.count(), 3)
        self.assertIn("stock 3", output)

    def test_merges_copies_into_one_listing_with_stock(self):
        keepers = [self._create(self.condition_nm) for _ in range(4)]

        self._run("--apply")

        product = Product.objects.get()
        self.assertEqual(product.pk, keepers[0].pk)
        self.assertEqual(product.stock_quantity, 4)
        self.assertTrue(product.in_stock)

    def test_different_condition_stays_a_separate_listing(self):
        self._create(self.condition_nm)
        self._create(self.condition_nm)
        self._create(self.condition_lp)

        self._run("--apply")

        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(
            sorted(Product.objects.values_list("stock_quantity", flat=True)), [1, 2]
        )

    def test_different_price_stays_a_separate_listing(self):
        self._create(self.condition_nm, price="10.00")
        self._create(self.condition_nm, price="18.00")

        self._run("--apply")

        self.assertEqual(Product.objects.count(), 2)

    def test_purchase_history_follows_the_surviving_listing(self):
        keeper = self._create(self.condition_nm)
        loser = self._create(self.condition_nm)
        order = Order.objects.create(
            customer_name="Cliente",
            customer_email="cliente@test.com",
            subtotal=Decimal("10.00"),
            total=Decimal("10.00"),
        )
        item = OrderItem.objects.create(
            order=order,
            product=loser,
            product_name=loser.name,
            unit_price=Decimal("10.00"),
            quantity=1,
        )

        self._run("--apply")

        item.refresh_from_db()
        self.assertEqual(item.product_id, keeper.pk)

    def test_skips_group_when_two_copies_have_their_own_photos(self):
        first = self._create(self.condition_nm)
        second = self._create(self.condition_nm)
        for product in (first, second):
            ProductImage.objects.create(
                product=product,
                secure_url=f"https://cdn.example.com/{product.pk}.jpg",
                source=ProductImage.SOURCE_URL,
                order_index=0,
                status=ProductImage.STATUS_CONFIRMED,
            )

        output = self._run("--apply")

        self.assertEqual(Product.objects.count(), 2)
        self.assertIn("fotos propias", output)
