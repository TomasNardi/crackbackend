"""
Cliente de tcgcsv.com
=====================
tcgcsv.com publica el catálogo de TCGplayer (sets, cartas, imágenes) como JSON
plano, sin API key ni registro. Es la fuente del catálogo de referencia.

Estructura de la fuente:
    /tcgplayer/{category}/groups              → expansiones
    /tcgplayer/{category}/{group}/products    → cartas de esa expansión

Categorías que usamos:
    3  → Pokémon inglés   (~217 sets)
    85 → Pokémon japonés  (~455 sets)
"""

import logging

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://tcgcsv.com/tcgplayer"

CATEGORY_POKEMON_EN = 3
CATEGORY_POKEMON_JA = 85

# Mapeo de categoría de TCGplayer al idioma que guardamos en CardSet.
CATEGORY_LANGUAGES = {
    CATEGORY_POKEMON_EN: "en",
    CATEGORY_POKEMON_JA: "ja",
}

# El CDN sirve varios tamaños. El de 1000x1000 es el más grande disponible y es
# el que descargamos para generar nuestras tres versiones WebP.
CDN_IMAGE_TEMPLATE = "https://tcgplayer-cdn.tcgplayer.com/product/{product_id}_in_1000x1000.jpg"

REQUEST_TIMEOUT = 30

# tcgcsv rechaza con 401 el User-Agent por defecto de `requests`, así que hay que
# identificarse. De paso es lo correcto: el servicio es gratis y mantenido por una
# sola persona, conviene ser reconocible.
HEADERS = {
    "User-Agent": "CrackTCG-CatalogBot/1.0 (+https://cracktcg.com)",
    "Accept": "application/json",
}


class TcgCsvError(Exception):
    pass


def _get(path: str) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise TcgCsvError(f"Error consultando {url}: {exc}") from exc
    except ValueError as exc:
        raise TcgCsvError(f"Respuesta no es JSON válido en {url}: {exc}") from exc

    if not payload.get("success", True):
        raise TcgCsvError(f"tcgcsv devolvió success=false en {url}: {payload.get('errors')}")

    return payload


def fetch_groups(category_id: int) -> list[dict]:
    """Devuelve las expansiones (groups) de una categoría."""
    payload = _get(f"{category_id}/groups")
    results = payload.get("results", [])
    logger.info("tcgcsv: %s expansiones en la categoría %s", len(results), category_id)
    return results


def fetch_products(category_id: int, group_id: int) -> list[dict]:
    """Devuelve las cartas (products) de una expansión."""
    payload = _get(f"{category_id}/{group_id}/products")
    return payload.get("results", [])


def extended_value(product: dict, field_name: str) -> str:
    """
    Extrae un campo de `extendedData`, que viene como lista de diccionarios:
        [{"name": "Number", "displayName": "Number", "value": "182/217"}, ...]
    """
    for entry in product.get("extendedData") or []:
        if entry.get("name") == field_name:
            return (entry.get("value") or "").strip()
    return ""


def flatten_extended_data(product: dict) -> dict:
    """Convierte `extendedData` en un diccionario plano para guardar en JSON."""
    out = {}
    for entry in product.get("extendedData") or []:
        name = entry.get("name")
        if name:
            out[name] = entry.get("value")
    return out


def high_res_image_url(product_id: int) -> str:
    return CDN_IMAGE_TEMPLATE.format(product_id=product_id)
