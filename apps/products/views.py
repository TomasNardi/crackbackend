"""
Products Views
===============
"""

from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import TCG, Expansion, ProductType, CardCondition, Product
from .serializers import (
    TCGSerializer,
    ExpansionSerializer,
    ProductTypeSerializer,
    CardConditionSerializer,
    ProductListSerializer,
    ProductDetailSerializer,
    ProductWriteSerializer,
)
from .filters import ProductFilter


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """TCGs disponibles."""

    queryset = TCG.objects.all()
    serializer_class = TCGSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"


class ExpansionViewSet(viewsets.ReadOnlyModelViewSet):
    """Expansiones, filtrables por TCG."""

    serializer_class = ExpansionSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"

    def get_queryset(self):
        qs = Expansion.objects.select_related("tcg")
        tcg_slug = self.request.query_params.get("tcg")
        if tcg_slug:
            qs = qs.filter(tcg__slug=tcg_slug)
        return qs


class ProductTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductType.objects.all()
    serializer_class = ProductTypeSerializer
    permission_classes = [permissions.AllowAny]


class CardConditionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CardCondition.objects.all()
    serializer_class = CardConditionSerializer
    permission_classes = [permissions.AllowAny]


class ProductViewSet(viewsets.ModelViewSet):
    """
    Catálogo de productos.

    - GET /products/          → listado paginado (público)
    - GET /products/{slug}/   → detalle (público)
    - POST/PUT/PATCH/DELETE   → solo admin

    Filtros disponibles (query params):
      tcg, expansion, product_type, condition,
      min_price, max_price, in_stock, is_single, has_discount

    Búsqueda: ?search=pikachu
    Orden:    ?ordering=-price | ?ordering=created_at
    """

    lookup_field = "slug"
    filterset_class = ProductFilter
    search_fields = ["name", "description", "expansion__name"]
    ordering_fields = ["price", "created_at", "name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return (
            Product.objects.select_related("tcg", "expansion", "product_type", "condition")
            .filter(in_stock=True)
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProductDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return ProductWriteSerializer
        return ProductListSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    @method_decorator(ratelimit(key="ip", rate="200/h", method="GET", block=True))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="featured")
    def featured(self, request):
        """GET /products/featured/ — productos con descuento activo."""
        qs = self.get_queryset().filter(discount_percent__gt=0).order_by("-created_at")[:12]
        serializer = ProductListSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="new-arrivals")
    def new_arrivals(self, request):
        """GET /products/new-arrivals/ — últimos 8 productos."""
        qs = self.get_queryset().order_by("-created_at")[:8]
        serializer = ProductListSerializer(qs, many=True)
        return Response(serializer.data)
