"""
Cliente de la eBay Browse API
==============================
Resuelve un link de publicación a los datos que necesita la calculadora:
título, imagen, precio, moneda, costo de envío y si sigue disponible.

Autenticación: OAuth client credentials (application token). No hace falta que
el usuario tenga cuenta de eBay — el token es de la aplicación y se cachea
hasta que vence.

Detalle que no es obvio: el costo de envío depende del destino. Sin el header
`X-EBAY-C-ENDUSERCTX` con el ZIP del courier, eBay devuelve la publicación pero
sin `shippingOptions`, y la cotización sale mal. Por eso el ZIP es configurable
en el admin y viaja en cada request.

Mientras no haya credenciales cargadas, `EBAY_MOCK=True` responde desde
fixtures para poder desarrollar y probar el flujo completo sin pegarle a eBay.
"""

import json
import logging
import re
from base64 import b64encode
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

PRODUCTION_HOSTS = {
    "api": "https://api.ebay.com",
    "auth": "https://api.ebay.com/identity/v1/oauth2/token",
}
SANDBOX_HOSTS = {
    "api": "https://api.sandbox.ebay.com",
    "auth": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
}

OAUTH_SCOPE = "https://api.ebay.com/oauth/api_scope"
TOKEN_CACHE_KEY = "ebay:oauth_token"
ITEM_CACHE_PREFIX = "ebay:item:"

REQUEST_TIMEOUT = 15

# Hosts de eBay que aceptamos. Cualquier otro dominio se rechaza antes de salir
# a la red — no queremos que el endpoint sirva de proxy para URLs arbitrarias.
ALLOWED_HOSTS = {
    "ebay.com", "www.ebay.com", "m.ebay.com",
    "ebay.us", "www.ebay.us",
    "ebay.ca", "www.ebay.ca",
    "ebay.co.uk", "www.ebay.co.uk",
    "ebay.com.au", "www.ebay.com.au",
    "sandbox.ebay.com", "www.sandbox.ebay.com",
}

# Hosts que devuelven un redirect al item real en vez del item.
SHORTLINK_HOSTS = {"ebay.us", "www.ebay.us"}


class EbayError(Exception):
    """Error de la integración con eBay, con mensaje apto para el cliente."""

    def __init__(self, message: str, code: str = "ebay_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class EbayItemUnavailable(EbayError):
    """La publicación existe pero ya no se puede comprar."""

    def __init__(self, message: str = "La publicación ya no está disponible en eBay."):
        super().__init__(message, code="item_unavailable")


class EbayItemNotFound(EbayError):
    def __init__(self, message: str = "No encontramos esa publicación en eBay."):
        super().__init__(message, code="item_not_found")


class EbayInvalidUrl(EbayError):
    def __init__(self, message: str = "El link no parece ser de una publicación de eBay."):
        super().__init__(message, code="invalid_url")


class EbayNotConfigured(EbayError):
    def __init__(self, message: str = "La cotización no está disponible en este momento."):
        super().__init__(message, code="not_configured")


# ─── Resolución del link ──────────────────────────────────────────────────────

# /itm/1888365418190 y /itm/algun-titulo/1888365418190 son las dos formas que
# usa eBay; el id es el último bloque largo de dígitos.
_ITM_PATH_RE = re.compile(r"/itm/(?:[^/]+/)?(\d{9,15})")
_QUERY_ID_RE = re.compile(r"[?&](?:item|itemId|legacyItemId)=(\d{9,15})")
_BARE_ID_RE = re.compile(r"^\d{9,15}$")


def _hosts() -> dict:
    env = str(getattr(settings, "EBAY_ENV", "production") or "production").lower()
    return SANDBOX_HOSTS if env == "sandbox" else PRODUCTION_HOSTS


def is_mock_mode() -> bool:
    """True cuando no hay credenciales o se pidió explícitamente el modo demo."""
    if getattr(settings, "EBAY_MOCK", False):
        return True
    return not (getattr(settings, "EBAY_CLIENT_ID", "") and getattr(settings, "EBAY_CLIENT_SECRET", ""))


def normalize_url(raw_url: str) -> str:
    """Limpia el input del usuario y valida que sea un link de eBay."""
    url = (raw_url or "").strip()
    if not url:
        raise EbayInvalidUrl("Pegá el link de la publicación.")

    # Un id pelado también sirve: mucha gente copia solo el número.
    if _BARE_ID_RE.match(url):
        return f"https://www.ebay.com/itm/{url}"

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    host = (urlparse(url).hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise EbayInvalidUrl()

    return url


def _follow_shortlink(url: str) -> str:
    """Los links ebay.us redirigen al item real; hay que seguirlos para ver el id."""
    try:
        response = requests.get(
            url,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (compatible; CrackTCG/1.0)"},
        )
        return response.url or url
    except requests.RequestException as exc:
        logger.warning("No se pudo resolver el link corto %s: %s", url, exc)
        raise EbayInvalidUrl("No pudimos abrir ese link. Probá con el link completo de la publicación.")


def extract_item_id(raw_url: str) -> str:
    """URL de eBay (larga, corta o id pelado) → legacy item id."""
    url = normalize_url(raw_url)

    host = (urlparse(url).hostname or "").lower()
    if host in SHORTLINK_HOSTS:
        url = _follow_shortlink(url)

    match = _ITM_PATH_RE.search(url) or _QUERY_ID_RE.search(url)
    if not match:
        raise EbayInvalidUrl("No pudimos identificar la publicación en ese link.")

    return match.group(1)


# ─── OAuth ────────────────────────────────────────────────────────────────────

def _fetch_token() -> str:
    client_id = getattr(settings, "EBAY_CLIENT_ID", "")
    client_secret = getattr(settings, "EBAY_CLIENT_SECRET", "")
    if not (client_id and client_secret):
        raise EbayNotConfigured()

    basic = b64encode(f"{client_id}:{client_secret}".encode()).decode()
    try:
        response = requests.post(
            _hosts()["auth"],
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": OAUTH_SCOPE},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.exception("Error de red pidiendo token a eBay: %s", exc)
        raise EbayError("No pudimos conectarnos con eBay. Probá de nuevo en unos minutos.")

    if response.status_code != 200:
        logger.error("eBay rechazó las credenciales (%s): %s", response.status_code, response.text[:500])
        raise EbayNotConfigured()

    payload = response.json()
    token = payload.get("access_token", "")
    # Renovamos un minuto antes de que venza para no cortar una request en curso.
    expires_in = max(int(payload.get("expires_in", 7200)) - 60, 60)
    cache.set(TOKEN_CACHE_KEY, token, expires_in)
    return token


def get_access_token() -> str:
    token = cache.get(TOKEN_CACHE_KEY)
    if token:
        return token
    return _fetch_token()


# ─── Modo demo ────────────────────────────────────────────────────────────────

def _mock_item(item_id: str) -> dict:
    """
    Respuesta de ejemplo para desarrollar sin credenciales.

    Deriva los valores del id para que distintos links den distintos precios y
    se pueda probar un pedido con varios ítems.
    """
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "sample_item.json"
    base = {}
    if fixture_path.exists():
        base = json.loads(fixture_path.read_text(encoding="utf-8"))

    seed = int(item_id[-4:]) if item_id[-4:].isdigit() else 1234
    price = Decimal(seed % 900 + 20) + Decimal("0.99")

    return {
        "item_id": item_id,
        "title": base.get("title") or f"Publicación de demostración #{item_id}",
        "image_url": base.get("image_url") or "https://i.ebayimg.com/images/g/placeholder/s-l500.jpg",
        "price": price,
        "currency": "USD",
        "shipping": Decimal("6.99"),
        "has_shipping_info": True,
        "item_web_url": f"https://www.ebay.com/itm/{item_id}",
        "buying_option": "FIXED_PRICE",
        "available": True,
        "seller": base.get("seller") or "demo_seller",
        "condition": base.get("condition") or "New",
        "is_mock": True,
    }


# ─── Item ─────────────────────────────────────────────────────────────────────

def _parse_price(node: dict | None) -> tuple[Decimal, str]:
    if not node:
        return Decimal("0"), ""
    try:
        return Decimal(str(node.get("value", "0"))), str(node.get("currency", "") or "")
    except (InvalidOperation, TypeError):
        return Decimal("0"), str(node.get("currency", "") or "")


def _parse_shipping(payload: dict) -> tuple[Decimal, bool]:
    """
    Costo de envío de la primera opción disponible.

    `shippingCost` ausente significa que eBay no pudo calcularlo para ese
    destino; `0.00` significa envío gratis. Son casos distintos y el segundo
    no debe caer al valor por defecto de la config.
    """
    options = payload.get("shippingOptions") or []
    for option in options:
        cost_node = option.get("shippingCost")
        if cost_node is None:
            continue
        cost, _ = _parse_price(cost_node)
        return cost, True
    return Decimal("0"), False


def _is_available(payload: dict) -> bool:
    availability = (payload.get("estimatedAvailabilities") or [{}])[0]
    status = str(availability.get("estimatedAvailabilityStatus", "") or "").upper()
    if status == "OUT_OF_STOCK":
        return False

    remaining = availability.get("estimatedAvailableQuantity")
    if isinstance(remaining, int) and remaining <= 0:
        return False

    return True


def get_item(item_id: str, *, use_cache: bool = True) -> dict:
    """
    Trae una publicación por su legacy id y la normaliza.

    Levanta EbayItemNotFound / EbayItemUnavailable / EbayError según el caso,
    todos con mensajes que se le pueden mostrar al cliente tal cual.
    """
    if is_mock_mode():
        return _mock_item(item_id)

    cache_key = f"{ITEM_CACHE_PREFIX}{item_id}"
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached

    from apps.ebay.models import EbayConfig

    config = EbayConfig.get()
    token = get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": config.marketplace_id or "EBAY_US",
        # Sin esto eBay no devuelve shippingOptions y perdemos el costo de envío.
        "X-EBAY-C-ENDUSERCTX": (
            f"contextualLocation=country%3D{config.us_country}%2Czip%3D{config.us_zip}"
        ),
        "Accept": "application/json",
    }

    url = f"{_hosts()['api']}/buy/browse/v1/item/get_item_by_legacy_id"
    try:
        response = requests.get(
            url, headers=headers, params={"legacy_item_id": item_id}, timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.exception("Error de red consultando el item %s: %s", item_id, exc)
        raise EbayError("No pudimos conectarnos con eBay. Probá de nuevo en unos minutos.")

    if response.status_code == 404:
        raise EbayItemNotFound()

    if response.status_code == 401:
        # El token pudo haber sido revocado antes de vencer: lo tiramos y reintentamos una vez.
        cache.delete(TOKEN_CACHE_KEY)
        logger.warning("eBay devolvió 401 para el item %s; reintentando con token nuevo.", item_id)
        headers["Authorization"] = f"Bearer {_fetch_token()}"
        try:
            response = requests.get(
                url, headers=headers, params={"legacy_item_id": item_id}, timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.exception("Error de red en el reintento del item %s: %s", item_id, exc)
            raise EbayError("No pudimos conectarnos con eBay. Probá de nuevo en unos minutos.")

    if response.status_code != 200:
        logger.error("eBay devolvió %s para el item %s: %s", response.status_code, item_id, response.text[:500])
        raise EbayError("eBay no respondió correctamente. Probá de nuevo en unos minutos.")

    payload = response.json()
    price, currency = _parse_price(payload.get("price"))
    shipping, has_shipping_info = _parse_shipping(payload)

    if not has_shipping_info:
        shipping = Decimal(config.default_ebay_shipping)

    image_url = (payload.get("image") or {}).get("imageUrl", "")
    if not image_url:
        thumbnails = payload.get("thumbnailImages") or []
        image_url = thumbnails[0].get("imageUrl", "") if thumbnails else ""

    buying_options = payload.get("buyingOptions") or []

    item = {
        "item_id": item_id,
        "title": payload.get("title", "") or "Publicación sin título",
        "image_url": image_url,
        "price": price,
        "currency": currency or "USD",
        "shipping": shipping,
        "has_shipping_info": has_shipping_info,
        "item_web_url": payload.get("itemWebUrl", "") or f"https://www.ebay.com/itm/{item_id}",
        "buying_option": "FIXED_PRICE" if "FIXED_PRICE" in buying_options else (
            buying_options[0] if buying_options else ""
        ),
        "buying_options": buying_options,
        "available": _is_available(payload),
        "seller": (payload.get("seller") or {}).get("username", ""),
        "condition": payload.get("condition", "") or "",
        "is_mock": False,
    }

    if use_cache:
        ttl = max(int(config.quote_ttl_minutes) * 60, 60)
        cache.set(cache_key, item, ttl)

    return item


def get_item_by_url(raw_url: str, *, use_cache: bool = True) -> dict:
    """Atajo: link → publicación normalizada."""
    return get_item(extract_item_id(raw_url), use_cache=use_cache)


def invalidate_item(item_id: str) -> None:
    """Fuerza que la próxima consulta vaya a eBay. Se usa al confirmar un pedido."""
    cache.delete(f"{ITEM_CACHE_PREFIX}{item_id}")
