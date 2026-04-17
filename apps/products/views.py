"""
Products Views
===============
"""

from django.db import models
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
        if self.action in ("list", "retrieve", "featured", "new_arrivals", "sitemap_index", "seo_facets"):
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

    @action(detail=False, methods=["get"], url_path="seo-facets", permission_classes=[permissions.AllowAny])
    def seo_facets(self, request):
        """
        GET /products/seo-facets/
        Retorna combinaciones de filtros con productos en stock — solo incluye
        combinaciones con count > 0 para evitar thin content en el sitemap.

        Estructura:
          {
            "page_size": 12,  # debe matchear el frontend /tienda
            "tienda_total": int,
            "tienda_pages": int,
            "has_discount_count": int,
            "categories":                    [{slug, name, count, pages, max_updated_at}],
            "tcgs":                          [{slug, name, count, pages, max_updated_at}],
            "certification_entities":        [{cert, count, pages, max_updated_at}],
            "category_tcg":                  [{category_slug, tcg_slug, count, pages, max_updated_at}],
            "singles_condition":             [{category_slug, tcg_slug, condition, count, pages, max_updated_at}],
            "singles_condition_all_tcgs":    [{category_slug, condition, count, pages, max_updated_at}],
            "slabs_cert":                    [{category_slug, tcg_slug, cert, count, pages, max_updated_at}],
            "slabs_cert_all_tcgs":           [{category_slug, cert, count, pages, max_updated_at}],
            "generated_at":                  ISO8601,
          }
        """
        from math import ceil
        from django.db.models import Count, Max
        from django.utils import timezone

        # Debe matchear `PAGE_SIZE` en src/app/tienda/page.js
        PAGE_SIZE = 12

        base_qs = Product.objects.filter(in_stock=True)

        def _pages(count):
            return max(1, ceil(count / PAGE_SIZE)) if count else 0

        def _iso(value):
            return value.isoformat() if value else None

        # Totales de /tienda (para paginar la landing base)
        tienda_total = base_qs.count()
        tienda_pages = _pages(tienda_total)
        has_discount_count = base_qs.filter(discount_percent__gt=0).count()

        categories = [
            {
                "slug": row["cat_slug"],
                "name": row["cat_name"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .exclude(category__isnull=True)
            .values(cat_slug=models.F("category__slug"), cat_name=models.F("category__name"))
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        tcgs = [
            {
                "slug": row["tcg_slug"],
                "name": row["tcg_name"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .exclude(tcg__isnull=True)
            .values(tcg_slug=models.F("tcg__slug"), tcg_name=models.F("tcg__name"))
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        # Certificadoras solas (cross-TCG) — ej: "PSA Argentina", "BGS Argentina"
        certification_entities = [
            {
                "cert": row["cert"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .exclude(certification_entity__isnull=True)
            .values(cert=models.F("certification_entity__abbreviation"))
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        category_tcg = [
            {
                "category_slug": row["category_slug"],
                "tcg_slug": row["tcg_slug"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .exclude(category__isnull=True)
            .exclude(tcg__isnull=True)
            .values(
                category_slug=models.F("category__slug"),
                tcg_slug=models.F("tcg__slug"),
            )
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        singles_condition = [
            {
                "category_slug": row["category_slug"],
                "tcg_slug": row["tcg_slug"],
                "condition": row["condition_abbr"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .filter(category__slug__in=["singles", "single"])
            .exclude(condition__isnull=True)
            .exclude(tcg__isnull=True)
            .values(
                category_slug=models.F("category__slug"),
                tcg_slug=models.F("tcg__slug"),
                condition_abbr=models.F("condition__abbreviation"),
            )
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        # Singles × condición sin TCG — ej: "Singles Near Mint"
        singles_condition_all_tcgs = [
            {
                "category_slug": row["category_slug"],
                "condition": row["condition_abbr"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .filter(category__slug__in=["singles", "single"])
            .exclude(condition__isnull=True)
            .values(
                category_slug=models.F("category__slug"),
                condition_abbr=models.F("condition__abbreviation"),
            )
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        slabs_cert = [
            {
                "category_slug": row["category_slug"],
                "tcg_slug": row["tcg_slug"],
                "cert": row["cert"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .filter(category__slug__in=["slabs", "slab"])
            .exclude(certification_entity__isnull=True)
            .exclude(tcg__isnull=True)
            .values(
                category_slug=models.F("category__slug"),
                tcg_slug=models.F("tcg__slug"),
                cert=models.F("certification_entity__abbreviation"),
            )
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        # Slabs × certificadora sin TCG — ej: "Slabs PSA"
        slabs_cert_all_tcgs = [
            {
                "category_slug": row["category_slug"],
                "cert": row["cert"],
                "count": row["count"],
                "pages": _pages(row["count"]),
                "max_updated_at": _iso(row["max_updated_at"]),
            }
            for row in base_qs
            .filter(category__slug__in=["slabs", "slab"])
            .exclude(certification_entity__isnull=True)
            .values(
                category_slug=models.F("category__slug"),
                cert=models.F("certification_entity__abbreviation"),
            )
            .annotate(count=Count("id"), max_updated_at=Max("updated_at"))
            .filter(count__gt=0)
            .order_by("-count")
        ]

        return Response({
            "page_size": PAGE_SIZE,
            "tienda_total": tienda_total,
            "tienda_pages": tienda_pages,
            "has_discount_count": has_discount_count,
            "categories": categories,
            "tcgs": tcgs,
            "certification_entities": certification_entities,
            "category_tcg": category_tcg,
            "singles_condition": singles_condition,
            "singles_condition_all_tcgs": singles_condition_all_tcgs,
            "slabs_cert": slabs_cert,
            "slabs_cert_all_tcgs": slabs_cert_all_tcgs,
            "generated_at": timezone.now().isoformat(),
        })

    @action(detail=False, methods=["get"], url_path="sitemap-index", permission_classes=[permissions.AllowAny])
    def sitemap_index(self, request):
        """
        GET /products/sitemap-index/
        Payload minimal optimizado para sitemap (slug + updated_at + nombre + imágenes).
        Solo productos en stock — sin paginar, ordenado por updated_at.
        `images` es un array con hasta 3 URLs (principal + 2 extras).
        `name` se usa como alt text en el sitemap de imágenes.
        """
        qs = (
            Product.objects
            .filter(in_stock=True)
            .only("slug", "updated_at", "image_url", "image_url_2", "image_url_3", "name")
            .order_by("-updated_at")
        )
        data = [
            {
                "slug": p.slug,
                "name": p.name or "",
                "updated_at": p.updated_at.isoformat(),
                "images": [url for url in (p.image_url, p.image_url_2, p.image_url_3) if url],
            }
            for p in qs.iterator(chunk_size=1000)
        ]
        return Response(data)

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
