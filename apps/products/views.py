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
    ProductSearchSerializer,
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

    def get_base_queryset(self):
        return Product.objects.select_related(
            "tcg", "category", "condition",
            "certification_entity", "certification_grade",
        )

    def get_queryset(self):
        return self.get_base_queryset().filter(in_stock=True)

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

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        """
        GET /products/search/?q=pikachu
        Autocomplete rápido — máx 8 resultados.
        Solo devuelve campos esenciales para el dropdown.
        """
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response([])

        qs = (
            self.get_queryset()
            .filter(name__icontains=q)
            .order_by("-created_at")[:8]
        )
        return Response(ProductSearchSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="featured")
    def featured(self, request):
        """GET /products/featured/ — productos con descuento activo, completados con los más recientes si faltan."""
        LIMIT = 8
        discounted = list(
            self.get_queryset()
            .filter(discount_percent__gt=0)
            .order_by("-created_at")[:LIMIT]
        )
        if len(discounted) < LIMIT:
            exclude_ids = [p.id for p in discounted]
            remaining = list(
                self.get_queryset()
                .exclude(id__in=exclude_ids)
                .order_by("-created_at")[: LIMIT - len(discounted)]
            )
            discounted += remaining
        return Response(ProductListSerializer(discounted, many=True).data)

    @action(detail=False, methods=["get"], url_path="new-arrivals")
    def new_arrivals(self, request):
        """GET /products/new-arrivals/ — últimos 8 productos."""
        qs = self.get_queryset().order_by("-created_at")[:8]
        return Response(ProductListSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="by-ids")
    def by_ids(self, request):
        """GET /products/by-ids/?ids=1,2,3 — devuelve disponibilidad actual para sincronizar el carrito. Solo retorna productos en stock."""
        raw_ids = (request.query_params.get("ids") or "").split(",")
        ids = []

        for raw_id in raw_ids:
            raw_id = raw_id.strip()
            if not raw_id:
                continue
            try:
                product_id = int(raw_id)
            except ValueError:
                continue
            if product_id > 0 and product_id not in ids:
                ids.append(product_id)

        if not ids:
            return Response([])

        products = {
            product.id: product
            for product in self.get_queryset().filter(id__in=ids)
        }
        ordered_products = [products[product_id] for product_id in ids if product_id in products]
        return Response(ProductListSerializer(ordered_products, many=True).data)
