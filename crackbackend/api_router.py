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
)
from apps.orders.views import (
    OrderViewSet,
    MercadoPagoWebhookView,
    MercadoPagoVerifyView,
    PaymentConfigView,
    ValidateDiscountView,
)
from apps.core.views import (
    SiteConfigView,
    EmailSubscribeView,
    EmailUnsubscribeView,
    PingView,
    ExchangeRateView,
    ContactView,
    SolicitudVentaCreateView,
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

    # Core
    path("site-config/", SiteConfigView.as_view(), name="site_config"),
    path("exchange-rate/", ExchangeRateView.as_view(), name="exchange_rate"),
    path("subscribe/", EmailSubscribeView.as_view(), name="email_subscribe"),
    path("unsubscribe/", EmailUnsubscribeView.as_view(), name="email_unsubscribe"),
    path("contact/", ContactView.as_view(), name="contact"),
    path("sale-requests/", SolicitudVentaCreateView.as_view(), name="sale_requests"),
    path("ping/", PingView.as_view(), name="ping"),

    # Router URLs
    path("", include(router.urls)),
]
