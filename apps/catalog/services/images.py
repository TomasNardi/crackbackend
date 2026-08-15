"""
Pipeline de imágenes del catálogo
=================================
Por cada carta: se descarga el JPG del CDN de TCGplayer, se generan tres WebP de
distinto ancho y se suben a R2. El nombre del archivo es el MD5 del original, así
que la misma imagen nunca se sube dos veces y se puede cachear para siempre.

    tcg/pkm/singles/<md5>_thumb.webp    200px  → grillas y buscador del admin
    tcg/pkm/singles/<md5>_medium.webp   600px  → cards de la tienda
    tcg/pkm/singles/<md5>.webp          660px  → detalle del producto

Los tres se sirven juntos con srcset, que es lo que hace que el front cargue
rápido en celular: el navegador baja solo el que necesita.
"""

import hashlib
import io
import logging

import requests
from PIL import Image

from apps.catalog.models import CatalogCard
from apps.catalog.services import r2

logger = logging.getLogger(__name__)

# (sufijo del archivo, ancho máximo en px)
RENDITIONS = (
    ("_thumb", 200),
    ("_medium", 600),
    ("", 660),
)

WEBP_QUALITY = 82
KEY_PREFIX = "tcg/pkm/singles"
DOWNLOAD_TIMEOUT = 30

# Identificarse es lo correcto al pegarle a un CDN ajeno de forma masiva.
USER_AGENT = "CrackTCG-CatalogBot/1.0 (+https://cracktcg.com)"


class ImagePipelineError(Exception):
    pass


def download_source(url: str) -> bytes:
    try:
        response = requests.get(
            url, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ImagePipelineError(f"No se pudo descargar {url}: {exc}") from exc

    if not response.content:
        raise ImagePipelineError(f"{url} devolvió un cuerpo vacío")

    return response.content


def build_renditions(source: bytes) -> dict[str, bytes]:
    """Convierte el original a WebP en los tres anchos. Nunca agranda la imagen."""
    try:
        original = Image.open(io.BytesIO(source))
        original.load()
    except Exception as exc:  # noqa: BLE001 — Pillow tira de todo con archivos rotos
        raise ImagePipelineError(f"No se pudo abrir la imagen: {exc}") from exc

    if original.mode not in ("RGB", "RGBA"):
        original = original.convert("RGB")

    out = {}
    for suffix, max_width in RENDITIONS:
        frame = original
        if original.width > max_width:
            height = round(original.height * max_width / original.width)
            frame = original.resize((max_width, height), Image.LANCZOS)

        buffer = io.BytesIO()
        frame.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=6)
        out[suffix] = buffer.getvalue()

    return out


def prepare_card_images(source_image_url: str, *, force: bool = False) -> dict[str, str]:
    """
    Hace todo el trabajo pesado —descargar, convertir, subir— SIN tocar la base.

    Está separado a propósito: así el comando de sincronización puede correrlo en
    varios hilos a la vez y guardar los resultados desde el hilo principal, sin
    pelear por conexiones ni lockear SQLite.

    Devuelve las URLs indexadas por sufijo ("", "_medium", "_thumb").
    """
    if not source_image_url:
        raise ImagePipelineError("La carta no tiene URL de imagen de origen.")

    source = download_source(source_image_url)
    digest = hashlib.md5(source).hexdigest()
    renditions = build_renditions(source)

    urls = {}
    for suffix, data in renditions.items():
        key = f"{KEY_PREFIX}/{digest}{suffix}.webp"
        if force or not r2.object_exists(key):
            urls[suffix] = r2.upload_bytes(key, data)
        else:
            urls[suffix] = r2.public_url(key)

    return urls


def apply_urls(card: CatalogCard, urls: dict[str, str]) -> CatalogCard:
    """Guarda en la carta el resultado de `prepare_card_images`."""
    card.image_url_thumb = urls["_thumb"]
    card.image_url_medium = urls["_medium"]
    card.image_url = urls[""]
    card.image_status = CatalogCard.IMAGE_READY
    card.image_error = ""
    card.save(update_fields=[
        "image_url_thumb", "image_url_medium", "image_url",
        "image_status", "image_error", "updated_at",
    ])
    return card


def mark_failed(card: CatalogCard, error: str) -> CatalogCard:
    card.image_status = CatalogCard.IMAGE_FAILED
    card.image_error = str(error)[:2000]
    card.save(update_fields=["image_status", "image_error", "updated_at"])
    return card


def process_card(card: CatalogCard, *, force: bool = False) -> CatalogCard:
    """
    Versión de un solo paso: descarga, convierte, sube y guarda.

    Se usa cuando hace falta la imagen de una carta puntual y ya —por ejemplo al
    cargar stock desde el admin de una carta cuya imagen todavía no se bajó.
    Es idempotente: si el objeto ya está en R2 no lo vuelve a subir.
    """
    if card.has_image and not force:
        return card

    try:
        urls = prepare_card_images(card.source_image_url, force=force)
    except (ImagePipelineError, r2.R2UploadError, r2.R2ConfigurationError) as exc:
        logger.warning("Imagen fallida para la carta %s: %s", card.external_id, exc)
        return mark_failed(card, exc)

    return apply_urls(card, urls)
