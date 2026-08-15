"""
Tareas de productos (django-q).
"""

import logging

from django.db.models import Q

from .models import Product

logger = logging.getLogger(__name__)


def backfill_product_images(card_ids=None):
    """
    Copia la imagen del catálogo a los productos que quedaron sin foto.

    Hace falta porque `Product.apply_catalog_image_fallback` solo corre al
    guardar: si cargás stock de una carta cuya imagen todavía no se bajó, el
    producto queda sin imagen y nadie lo vuelve a tocar. Esto lo repara.

    Con `card_ids` arregla solo esas cartas (lo usa la carga de stock al terminar
    un lote). Sin argumentos barre todo, que es como lo llama el refresco del
    catálogo.
    """
    from apps.catalog.models import CatalogCard

    products = Product.objects.filter(
        Q(image_url="") | Q(image_url__isnull=True),
        catalog_card__isnull=False,
        catalog_card__image_status=CatalogCard.IMAGE_READY,
    ).exclude(catalog_card__image_url="").select_related("catalog_card")

    if card_ids:
        products = products.filter(catalog_card_id__in=card_ids)

    fixed = 0
    for product in products.iterator(chunk_size=200):
        product.image_url = product.catalog_card.image_url
        product.save(update_fields=["image_url", "updated_at"])
        fixed += 1

    if fixed:
        logger.info("Imágenes de producto rellenadas desde el catálogo: %s", fixed)

    return fixed


def fetch_images_for_cards(card_ids):
    """
    Baja ya las imágenes de las cartas de un lote recién cargado y las propaga.

    La carga de stock encola esto para no hacer esperar al que está cargando
    stock: si la carta es de un set recién importado, la imagen aparece en
    minutos en vez de en la próxima corrida del catálogo.
    """
    from apps.catalog.models import CatalogCard
    from apps.catalog.services import images as catalog_images
    from apps.catalog.services import r2

    if not r2.is_configured():
        logger.warning("Lote cargado sin R2 configurado: las imágenes quedan pendientes.")
        return 0

    cards = CatalogCard.objects.filter(
        id__in=card_ids, image_status=CatalogCard.IMAGE_PENDING
    )

    done = 0
    for card in cards:
        try:
            catalog_images.process_card(card)
            done += 1
        except Exception as exc:  # noqa: BLE001 — una imagen rota no frena el resto
            logger.warning("No se pudo bajar la imagen de la carta %s: %s", card.pk, exc)

    backfill_product_images(card_ids)
    return done
