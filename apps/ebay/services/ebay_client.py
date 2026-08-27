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
from urllib.parse import parse_qs, urlparse

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

# eBay devuelve este errorId cuando el link apunta a una publicación con
# variantes (item group) y le pedimos el item pelado por su legacy id.
ITEM_GROUP_ERROR_ID = 11006
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


class EbayItemHasVariations(EbayError):
    """
    El link apunta a una publicación con variantes sin elegir ninguna.

    Son las típicas "pick a card": un solo aviso con muchas cartas adentro. La
    Browse API no las devuelve por legacy id — hace falta la variante concreta,
    y cuál quiere el cliente no se puede adivinar.
    """

    def __init__(self, message: str = (
        "Esa publicación tiene varias opciones para elegir. Entrá a eBay, "
        "elegí la que querés comprar y pegá el link de esa opción."
    )):
        super().__init__(message, code="item_has_variations")


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


def _extract_variation_id(url: str) -> str | None:
    """
    Variante elegida, si el link la trae (`?var=123456789012`).

    Se lee de la query parseada y no con una regex sobre la URL entera: los
    links de eBay arrastran un blob `itmprp` largo donde un `var=` suelto
    aparecería por casualidad.
    """
    for value in parse_qs(urlparse(url).query).get("var", []):
        if value.isdigit() and 6 <= len(value) <= 20:
            return value
    return None


def extract_item_ref(raw_url: str) -> tuple[str, str | None]:
    """URL de eBay (larga, corta o id pelado) → (legacy item id, variante | None)."""
    url = normalize_url(raw_url)

    host = (urlparse(url).hostname or "").lower()
    if host in SHORTLINK_HOSTS:
        url = _follow_shortlink(url)

    match = _ITM_PATH_RE.search(url) or _QUERY_ID_RE.search(url)
    if not match:
        raise EbayInvalidUrl("No pudimos identificar la publicación en ese link.")

    return match.group(1), _extract_variation_id(url)


def extract_item_id(raw_url: str) -> str:
    """URL de eBay (larga, corta o id pelado) → legacy item id."""
    return extract_item_ref(raw_url)[0]


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

def _mock_item(item_id: str, variation_id: str | None = None) -> dict:
    """
    Respuesta de ejemplo para desarrollar sin credenciales.

    Deriva los valores del id para que distintos links den distintos precios y
    se pueda probar un pedido con varios ítems.
    """
    fixture_path = Path(__file__).resolve().parent.parent / "fixtures" / "sample_item.json"
    base = {}
    if fixture_path.exists():
        base = json.loads(fixture_path.read_text(encoding="utf-8"))

    ref = variation_id or item_id
    seed = int(ref[-4:]) if ref[-4:].isdigit() else 1234
    price = Decimal(seed % 900 + 20) + Decimal("0.99")

    return {
        "item_id": item_id,
        "variation_id": variation_id,
        "title": base.get("title") or f"Publicación de demostración #{item_id}",
        "image_url": base.get("image_url") or "https://i.ebayimg.com/images/g/placeholder/s-l500.jpg",
        "price": price,
        "currency": "USD",
        "shipping": Decimal("6.99"),
        "has_shipping_info": True,
        "item_web_url": f"https://www.ebay.com/itm/{item_id}",
        "buying_option": "FIXED_PRICE",
        "available": True,
        "available_quantity": None,
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
    destino; `0.00` significa envío gratis. Son casos distintos: el primero
    viaja como "a confirmar" y el segundo como envío gratis de verdad.

    Cuando no se sabe, el costo queda en 0 y `has_shipping_info` en False. No
    inventamos un valor por defecto: un número puesto por nosotros se le cobra
    al cliente como si fuera de eBay, y si erramos la diferencia la come la
    tienda. El owner lo carga a mano al aprobar el pedido.
    """
    options = payload.get("shippingOptions") or []
    for option in options:
        cost_node = option.get("shippingCost")
        if cost_node is None:
            continue
        cost, _ = _parse_price(cost_node)
        return cost, True
    return Decimal("0"), False


def _parse_available_quantity(payload: dict) -> int | None:
    """
    Unidades que eBay dice que quedan, o None si no se puede saber.

    Importa para no dejar que el cliente pida 3 de una publicación que tiene una
    sola: el pedido se frenaría recién al confirmarlo, después de que armó todo.

    eBay lo informa de tres formas y no siempre manda la misma. Cuando usa
    `availabilityThresholdType: MORE_THAN` está diciendo "hay más de N" sin dar
    el número exacto: ahí no hay tope real que aplicar y devolvemos None.
    """
    availability = (payload.get("estimatedAvailabilities") or [{}])[0]

    for field in ("estimatedAvailableQuantity", "estimatedRemainingQuantity"):
        value = availability.get(field)
        if isinstance(value, int) and value > 0:
            return value

    return None


def _is_available(payload: dict) -> bool:
    availability = (payload.get("estimatedAvailabilities") or [{}])[0]
    status = str(availability.get("estimatedAvailabilityStatus", "") or "").upper()
    if status == "OUT_OF_STOCK":
        return False

    remaining = availability.get("estimatedAvailableQuantity")
    if isinstance(remaining, int) and remaining <= 0:
        return False

    return True


def _error_ids(response: requests.Response) -> set[int]:
    """errorIds que vienen en el cuerpo de un error de la Browse API."""
    try:
        payload = response.json()
    except ValueError:
        return set()

    ids = set()
    for error in payload.get("errors") or []:
        try:
            ids.add(int(error.get("errorId")))
        except (TypeError, ValueError):
            continue
    return ids


def _browse_get(url: str, params: dict, headers: dict, *, what: str) -> requests.Response:
    """
    GET a la Browse API con reintento único ante un 401.

    El token puede ser revocado antes de vencer: en ese caso lo tiramos, pedimos
    uno nuevo y repetimos la request una sola vez.
    """
    try:
        response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.exception("Error de red consultando %s: %s", what, exc)
        raise EbayError("No pudimos conectarnos con eBay. Probá de nuevo en unos minutos.")

    if response.status_code != 401:
        return response

    cache.delete(TOKEN_CACHE_KEY)
    logger.warning("eBay devolvió 401 para %s; reintentando con token nuevo.", what)
    retry_headers = {**headers, "Authorization": f"Bearer {_fetch_token()}"}
    try:
        return requests.get(url, headers=retry_headers, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        logger.exception("Error de red en el reintento de %s: %s", what, exc)
        raise EbayError("No pudimos conectarnos con eBay. Probá de nuevo en unos minutos.")


def get_item(item_id: str, *, variation_id: str | None = None, use_cache: bool = True) -> dict:
    """
    Trae una publicación por su legacy id y la normaliza.

    `variation_id` es la variante elegida dentro de una publicación con opciones
    (el `?var=` del link). Sin ella, eBay rechaza esas publicaciones con el
    errorId 11006 y devolvemos EbayItemHasVariations, que le pide al cliente que
    elija la opción en eBay — reintentar no lo arregla nunca.

    Levanta EbayItemNotFound / EbayItemUnavailable / EbayItemHasVariations /
    EbayError según el caso, todos con mensajes que se le pueden mostrar al
    cliente tal cual.
    """
    if is_mock_mode():
        return _mock_item(item_id, variation_id)

    cache_key = f"{ITEM_CACHE_PREFIX}{item_id}"
    if variation_id:
        cache_key = f"{cache_key}:{variation_id}"
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

    params = {"legacy_item_id": item_id}
    if variation_id:
        params["legacy_variation_id"] = variation_id

    url = f"{_hosts()['api']}/buy/browse/v1/item/get_item_by_legacy_id"
    response = _browse_get(url, params, headers, what=f"el item {item_id}")

    if response.status_code == 404:
        raise EbayItemNotFound()

    if response.status_code == 400 and ITEM_GROUP_ERROR_ID in _error_ids(response):
        logger.info("El item %s es una publicación con variantes.", item_id)
        raise EbayItemHasVariations()

    if response.status_code != 200:
        logger.error("eBay devolvió %s para el item %s: %s", response.status_code, item_id, response.text[:500])
        raise EbayError("eBay no respondió correctamente. Probá de nuevo en unos minutos.")

    payload = response.json()
    price, currency = _parse_price(payload.get("price"))
    shipping, has_shipping_info = _parse_shipping(payload)

    image_url = (payload.get("image") or {}).get("imageUrl", "")
    if not image_url:
        thumbnails = payload.get("thumbnailImages") or []
        image_url = thumbnails[0].get("imageUrl", "") if thumbnails else ""

    buying_options = payload.get("buyingOptions") or []

    item = {
        "item_id": item_id,
        "variation_id": variation_id,
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
        "available_quantity": _parse_available_quantity(payload),
        "seller": (payload.get("seller") or {}).get("username", ""),
        "condition": payload.get("condition", "") or "",
        "is_mock": False,
    }

    if use_cache:
        ttl = max(int(config.quote_ttl_minutes) * 60, 60)
        cache.set(cache_key, item, ttl)

    return item


def get_item_by_url(raw_url: str, *, use_cache: bool = True) -> dict:
    """Atajo: link → publicación normalizada, respetando la variante del link."""
    legacy_id, variation_id = extract_item_ref(raw_url)
    return get_item(legacy_id, variation_id=variation_id, use_cache=use_cache)


def invalidate_item(item_id: str, variation_id: str | None = None) -> None:
    """Fuerza que la próxima consulta vaya a eBay. Se usa al confirmar un pedido."""
    cache_key = f"{ITEM_CACHE_PREFIX}{item_id}"
    if variation_id:
        cache_key = f"{cache_key}:{variation_id}"
    cache.delete(cache_key)
