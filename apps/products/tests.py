from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase

from apps.products.admin import ProductAdmin
from apps.products.models import Product, ProductCategory, ProductImage


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
