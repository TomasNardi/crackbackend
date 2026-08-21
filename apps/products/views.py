"""
Products Views
===============
"""

import json
import logging

from django.views.decorators.csrf import csrf_exempt
from django.db import models
from django.utils import timezone
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions, status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.response import Response

from .models import TCG, ProductCategory, CardCondition, CertificationEntity, CertificationGrade, Product, ProductImage, ProductImageWebhookEvent
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
from .services.cloudinary_service import (
    DELIVERY_TRANSFORM_DETAIL,
    CloudinaryConfigurationError,
    CloudinaryValidationError,
    create_pending_image,
    generate_signed_upload_payload,
    optimize_cloudinary_url,
    remove_cloudinary_asset,
    verify_notification_signature,
)


logger = logging.getLogger(__name__)


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
      ?min_price=10000&max_price=500000  (en ARS, precio final con descuento)
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
            # El bloque `catalog` del serializer llega hasta la expansión.
            "catalog_card", "catalog_card__card_set",
        ).prefetch_related("images")

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
        """GET /products/featured/ — productos más caros (solo Singles o certificadas; excluye Sellados)."""
        LIMIT = 8
        qs = (
            self.get_queryset()
            .filter(
                models.Q(category__slug__in=["single", "singles"])
                | models.Q(category__name__iexact="Single")
                | models.Q(category__name__iexact="Singles")
                | models.Q(certification_entity__isnull=False)
            )
            .exclude(category__slug__in=["sellado", "sellados", "sealed"])
            .exclude(category__name__iexact="Sellado")
            .exclude(category__name__iexact="Sellados")
            .order_by("-price_usd", "-created_at")[:LIMIT]
        )
        return Response(ProductListSerializer(qs, many=True).data)

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
        def _dedup_images(*urls):
            # Preserva orden y descarta vacías/duplicadas (mismos URLs en image_url y image_url_2, etc).
            seen = set()
            out = []
            for url in urls:
                if url and url not in seen:
                    seen.add(url)
                    out.append(optimize_cloudinary_url(url, DELIVERY_TRANSFORM_DETAIL))
            return out

        data = [
            {
                "slug": p.slug,
                "name": p.name or "",
                "updated_at": p.updated_at.isoformat(),
                "images": _dedup_images(p.image_url, p.image_url_2, p.image_url_3),
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


class _AdminProductImageAPIView(APIView):
    authentication_classes = [SessionAuthentication, JWTAuthentication]
    permission_classes = [permissions.IsAdminUser]


class CloudinarySignedUploadSignatureView(_AdminProductImageAPIView):
    def post(self, request):
        draft_token = (request.data.get("draft_token") or "").strip()
        slot = request.data.get("slot")

        if not draft_token:
            return Response({"detail": "draft_token es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            slot = int(slot)
        except (TypeError, ValueError):
            return Response({"detail": "slot inválido."}, status=status.HTTP_400_BAD_REQUEST)

        if slot < 0 or slot > 2:
            return Response({"detail": "slot inválido."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = generate_signed_upload_payload(
                draft_token=draft_token,
                slot=slot,
                user_id=request.user.id if request.user.is_authenticated else None,
            )
            return Response(payload)
        except CloudinaryConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ProductImageRegisterUploadView(_AdminProductImageAPIView):
    def post(self, request):
        draft_token = (request.data.get("draft_token") or "").strip()
        secure_url = (request.data.get("secure_url") or "").strip()
        public_id = (request.data.get("public_id") or "").strip()
        source = (request.data.get("source") or ProductImage.SOURCE_CLOUDINARY).strip()
        order_index = request.data.get("order_index", 0)
        metadata = request.data.get("metadata") or {}

        if not draft_token:
            return Response({"detail": "draft_token es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)
        if not secure_url:
            return Response({"detail": "secure_url es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order_index = int(order_index)
            image = create_pending_image(
                draft_token=draft_token,
                secure_url=secure_url,
                order_index=order_index,
                source=source,
                public_id=public_id,
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        except (ValueError, CloudinaryValidationError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "id": image.id,
                "secure_url": image.secure_url,
                "public_id": image.public_id,
                "order_index": image.order_index,
                "status": image.status,
                "source": image.source,
            },
            status=status.HTTP_201_CREATED,
        )


class ProductImageDeleteView(_AdminProductImageAPIView):
    def post(self, request):
        image_id = request.data.get("image_id")
        if not image_id:
            return Response({"detail": "image_id es obligatorio."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            image = ProductImage.objects.get(id=image_id)
        except ProductImage.DoesNotExist:
            return Response({"detail": "Imagen no encontrada."}, status=status.HTTP_404_NOT_FOUND)

        product = image.product
        cloudinary_result = None
        if image.source == ProductImage.SOURCE_CLOUDINARY and image.public_id:
            try:
                cloudinary_result = remove_cloudinary_asset(image.public_id, invalidate=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error eliminando imagen Cloudinary %s: %s", image.public_id, exc)
                return Response({"detail": "No se pudo eliminar la imagen en Cloudinary."}, status=status.HTTP_502_BAD_GATEWAY)

        image.delete()
        if product:
            product.sync_legacy_images_from_gallery(save=True)

        return Response({"ok": True, "cloudinary": cloudinary_result})


@method_decorator(csrf_exempt, name="dispatch")
class CloudinaryUploadWebhookView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        raw_body = request.body or b""
        timestamp = request.headers.get("X-Cld-Timestamp", "")
        signature = request.headers.get("X-Cld-Signature", "")

        is_valid_signature = False
        try:
            is_valid_signature = verify_notification_signature(raw_body, timestamp, signature)
        except CloudinaryConfigurationError:
            return Response({"detail": "Cloudinary no configurado."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        payload = {}
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}

        notification_type = (payload.get("notification_type") or "").strip() or ProductImageWebhookEvent.EVENT_OTHER
        normalized_type = notification_type if notification_type in {
            ProductImageWebhookEvent.EVENT_UPLOAD,
            ProductImageWebhookEvent.EVENT_DELETE,
            ProductImageWebhookEvent.EVENT_EAGER,
        } else ProductImageWebhookEvent.EVENT_OTHER

        public_id = (payload.get("public_id") or "").strip()
        event = ProductImageWebhookEvent.objects.create(
            event_type=normalized_type,
            public_id=public_id,
            payload=payload,
            is_valid_signature=is_valid_signature,
        )

        if not is_valid_signature:
            event.error = "Firma inválida"
            event.save(update_fields=["error"])
            return Response({"detail": "invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

        try:
            if normalized_type == ProductImageWebhookEvent.EVENT_UPLOAD and public_id:
                image = ProductImage.objects.filter(public_id=public_id).order_by("-id").first()
                if image:
                    image.status = ProductImage.STATUS_CONFIRMED
                    image.confirmed_at = timezone.now()
                    image.width = payload.get("width") or image.width
                    image.height = payload.get("height") or image.height
                    image.bytes = payload.get("bytes") or image.bytes
                    image.format = payload.get("format") or image.format
                    secure_url = payload.get("secure_url") or image.secure_url
                    thumbnail_url = ""
                    if secure_url and "/upload/" in secure_url:
                        thumbnail_url = secure_url.replace(
                            "/upload/",
                            "/upload/c_fill,w_320,h_320,f_auto,q_auto/",
                            1,
                        )
                    image.metadata = {
                        **(image.metadata or {}),
                        "thumbnail_url": thumbnail_url,
                        "webhook": payload,
                    }
                    image.save(
                        update_fields=[
                            "status",
                            "confirmed_at",
                            "width",
                            "height",
                            "bytes",
                            "format",
                            "metadata",
                        ]
                    )
            event.processed = True
            event.processed_at = timezone.now()
            event.save(update_fields=["processed", "processed_at"])
        except Exception as exc:  # noqa: BLE001
            event.error = str(exc)
            event.save(update_fields=["error"])
            logger.exception("Error procesando webhook de Cloudinary")
            return Response({"detail": "processing error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"ok": True}, status=status.HTTP_200_OK)
