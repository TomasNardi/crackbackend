"""
API Router - v1
================
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.views import UserTokenObtainPairView, RegisterView, UserProfileView, CreateSuperuserView
from apps.products.views import (
    TCGViewSet,
    ProductCategoryViewSet,
    CardConditionViewSet,
    CertificationEntityViewSet,
    CertificationGradeViewSet,
    ProductViewSet,
    CloudinarySignedUploadSignatureView,
    ProductImageRegisterUploadView,
    ProductImageDeleteView,
    CloudinaryUploadWebhookView,
)
from apps.orders.views import (
    OrderViewSet,
    MercadoPagoWebhookView,
    MercadoPagoVerifyView,
    PaymentConfigView,
    ValidateDiscountView,
)
from apps.ebay.views import (
    EbayConfigView,
    EbayOrderCreateView,
    EbayOrderDetailView,
    EbayQuoteView,
)
from apps.catalog.views import MarkUnlimitedPrintsView  # TEMPORAL: borrar junto con apps/catalog/views.py
from apps.core.views import (
    SiteConfigView,
    EmailSubscribeView,
    EmailUnsubscribeView,
    PingView,
    ExchangeRateView,
    ContactView,
    ContactMarkReadView,
    ContactMarkReadConfirmView,
    SolicitudVentaCreateView,
    ResendWebhookView,
)

router = DefaultRouter()

# Products
router.register(r"products", ProductViewSet, basename="product")
router.register(r"tcgs", TCGViewSet, basename="tcg")
router.register(r"categories", ProductCategoryViewSet, basename="category")
router.register(r"conditions", CardConditionViewSet, basename="condition")
router.register(r"certification-entities", CertificationEntityViewSet, basename="certification-entity")
router.register(r"certification-grades", CertificationGradeViewSet, basename="certification-grade")

# Orders
router.register(r"orders", OrderViewSet, basename="order")

urlpatterns = [
    # Auth
    path("auth/login/", UserTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/me/", UserProfileView.as_view(), name="user_profile"),
    path("auth/create-superuser/", CreateSuperuserView.as_view(), name="create_superuser"),

    # Payments
    path("payments/webhook/", MercadoPagoWebhookView.as_view(), name="mp_webhook"),
    path("payments/verify/", MercadoPagoVerifyView.as_view(), name="mp_verify"),
    path("payments/config/", PaymentConfigView.as_view(), name="payments_config"),
    path("payments/validate-discount/", ValidateDiscountView.as_view(), name="validate_discount"),

    # Importación eBay
    path("ebay/config/", EbayConfigView.as_view(), name="ebay_config"),
    path("ebay/quote/", EbayQuoteView.as_view(), name="ebay_quote"),
    path("ebay/orders/", EbayOrderCreateView.as_view(), name="ebay_order_create"),
    path("ebay/orders/<str:order_code>/", EbayOrderDetailView.as_view(), name="ebay_order_detail"),

    # Core
    path("site-config/", SiteConfigView.as_view(), name="site_config"),
    path("exchange-rate/", ExchangeRateView.as_view(), name="exchange_rate"),
    path("subscribe/", EmailSubscribeView.as_view(), name="email_subscribe"),
    path("unsubscribe/", EmailUnsubscribeView.as_view(), name="email_unsubscribe"),
    path("contact/", ContactView.as_view(), name="contact"),
    path("contact/mark-read/", ContactMarkReadView.as_view(), name="contact_mark_read"),
    path("contact/mark-read/confirm/", ContactMarkReadConfirmView.as_view(), name="contact_mark_read_confirm"),
    path("sale-requests/", SolicitudVentaCreateView.as_view(), name="sale_requests"),
    path("ping/", PingView.as_view(), name="ping"),

    # TEMPORAL: para correr el marcado de Unlimited contra prod sin entrar al
    # Shell de Render. Borrar esta ruta y apps/catalog/views.py después de usarla.
    path("catalog/mark-unlimited/", MarkUnlimitedPrintsView.as_view(), name="mark_unlimited_prints"),

    # Webhooks
    path("webhooks/resend/", ResendWebhookView.as_view(), name="resend_webhook"),

    # Cloudinary (admin product uploads)
    path("products/admin/cloudinary/signature/", CloudinarySignedUploadSignatureView.as_view(), name="cloudinary_upload_signature"),
    path("products/admin/cloudinary/register-upload/", ProductImageRegisterUploadView.as_view(), name="cloudinary_register_upload"),
    path("products/admin/cloudinary/delete/", ProductImageDeleteView.as_view(), name="cloudinary_delete_upload"),
    path("products/admin/cloudinary/webhook/", CloudinaryUploadWebhookView.as_view(), name="cloudinary_upload_webhook"),

    # Router URLs
    path("", include(router.urls)),
]
