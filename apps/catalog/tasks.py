"""
Tareas de mantenimiento del catálogo (django-q).
================================================
Se programa una vez con `python manage.py schedule_catalog_refresh` y a partir de
ahí corre sola en el qcluster, igual que las campañas de mail.

Qué hace cada semana:
  1. Relee la lista de expansiones y baja solo las que cambiaron.
  2. Baja las imágenes de las cartas nuevas.

Cuando sale un set nuevo, aparece solo. No hay que tocar nada a mano.
"""

import logging

from django.core.management import call_command

from apps.catalog.models import CatalogCard
from apps.catalog.services import r2

logger = logging.getLogger(__name__)

# Tope de imágenes por corrida. Un set nuevo trae ~250 cartas; 2000 deja margen
# de sobra sin que la tarea quede colgada horas si algo se descontroló.
MAX_IMAGES_PER_RUN = 2000


def refresh_catalog():
    """Actualiza el catálogo y baja las imágenes que falten. Corre semanalmente."""
    before = CatalogCard.objects.count()

    call_command("import_catalog", verbosity=0)

    after = CatalogCard.objects.count()
    new_cards = after - before

    if new_cards:
        logger.info("Catálogo: %s cartas nuevas (%s en total).", new_cards, after)
    else:
        logger.info("Catálogo: sin novedades (%s cartas).", after)

    pending = CatalogCard.objects.filter(image_status=CatalogCard.IMAGE_PENDING).count()
    if not pending:
        return f"Catálogo al día: {after} cartas, sin imágenes pendientes."

    if not r2.is_configured():
        logger.warning("Hay %s imágenes pendientes pero R2 no está configurado.", pending)
        return f"{new_cards} cartas nuevas. Faltan {pending} imágenes: R2 sin configurar."

    call_command("sync_catalog_images", limit=MAX_IMAGES_PER_RUN, verbosity=0)

    still_pending = CatalogCard.objects.filter(image_status=CatalogCard.IMAGE_PENDING).count()
    return (
        f"{new_cards} cartas nuevas, {pending - still_pending} imágenes bajadas"
        + (f", quedan {still_pending} para la próxima." if still_pending else ".")
    )
