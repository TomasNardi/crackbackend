"""
API Router - v1
================
Centraliza el registro de todos los routers y endpoints de la API.
Agregar nuevas apps acá a medida que crecen.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.users.views import UserTokenObtainPairView, RegisterView, UserProfileView, CreateSuperuserView
from apps.products.views import (
    ProductViewSet,
    CategoryViewSet,
    ExpansionViewSet,
    ProductTypeViewSet,
    CardConditionViewSet,
)
from apps.orders.views import OrderViewSet, MercadoPagoWebhookView, ValidateDiscountView
from apps.core.views import BannerViewSet, SiteConfigView, EmailSubscribeView, PingView

router = DefaultRouter()

# Products
router.register(r"products", ProductViewSet, basename="product")
router.register(r"categories", CategoryViewSet, basename="category")
router.register(r"expansions", ExpansionViewSet, basename="expansion")
router.register(r"product-types", ProductTypeViewSet, basename="product-type")
router.register(r"card-conditions", CardConditionViewSet, basename="card-condition")

# Orders
router.register(r"orders", OrderViewSet, basename="order")

# Core
router.register(r"banners", BannerViewSet, basename="banner")

urlpatterns = [
    # Auth
    path("auth/login/", UserTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/me/", UserProfileView.as_view(), name="user_profile"),
    path("auth/create-superuser/", CreateSuperuserView.as_view(), name="create_superuser"),

    # Payments
    path("payments/webhook/", MercadoPagoWebhookView.as_view(), name="mp_webhook"),
    path("payments/validate-discount/", ValidateDiscountView.as_view(), name="validate_discount"),

    # Core
    path("site-config/", SiteConfigView.as_view(), name="site_config"),
    path("subscribe/", EmailSubscribeView.as_view(), name="email_subscribe"),
    path("ping/", PingView.as_view(), name="ping"),

    # Router URLs
    path("", include(router.urls)),
]
