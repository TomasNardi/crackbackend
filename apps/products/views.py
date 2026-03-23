"""
Products Views
===============
"""

from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import viewsets, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import TCG, ProductCategory, CardCondition, CertificationEntity, CertificationGrade, Product
from .serializers import (
    TCGSerializer,
    ProductCategorySerializer,
    CardConditionSerializer,
    CertificationEntitySerializer,
    CertificationGradeSerializer,
    ProductListSerializer,
    ProductDetailSerializer,
    ProductWriteSerializer,
)
from .filters import ProductFilter


class TCGViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TCG.objects.all()
    serializer_class = TCGSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"


class ProductCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = "slug"


class CardConditionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CardCondition.objects.all()
    serializer_class = CardConditionSerializer
    permission_classes = [permissions.AllowAny]


class CertificationEntityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CertificationEntity.objects.all()
    serializer_class = CertificationEntitySerializer
    permission_classes = [permissions.AllowAny]


class CertificationGradeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CertificationGrade.objects.all()
    serializer_class = CertificationGradeSerializer
    permission_classes = [permissions.AllowAny]


class ProductViewSet(viewsets.ModelViewSet):
    """
    Catálogo de productos.

    Filtros disponibles:
      ?tcg=pokemon
      ?category=slab
      ?condition=NM
      ?certification_entity=PSA
      ?min_price=10&max_price=500
      ?in_stock=true
      ?has_discount=true

    Búsqueda: ?search=pikachu
    Orden:    ?ordering=-price | ?ordering=created_at
    """

    lookup_field = "slug"
    filterset_class = ProductFilter
    search_fields = ["name", "description"]
    ordering_fields = ["price_usd", "created_at", "name"]
    ordering = ["-created_at"]

    def get_queryset(self):
        return Product.objects.select_related(
            "tcg", "category", "condition",
            "certification_entity", "certification_grade",
        ).filter(in_stock=True)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ProductDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return ProductWriteSerializer
        return ProductListSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve", "featured", "new_arrivals"):
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]

    @method_decorator(ratelimit(key="ip", rate="200/h", method="GET", block=True))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="featured")
    def featured(self, request):
        """GET /products/featured/ — productos con descuento activo."""
        qs = self.get_queryset().filter(discount_percent__gt=0).order_by("-created_at")[:12]
        return Response(ProductListSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="new-arrivals")
    def new_arrivals(self, request):
        """GET /products/new-arrivals/ — últimos 8 productos."""
        qs = self.get_queryset().order_by("-created_at")[:8]
        return Response(ProductListSerializer(qs, many=True).data)
