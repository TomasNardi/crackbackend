"""
Cliente de Cloudflare R2
========================
R2 es S3-compatible, así que se maneja con boto3 apuntando al endpoint de la
cuenta. La razón de usarlo en vez de S3 es que R2 no cobra egress: servir el
catálogo entero de imágenes sale prácticamente cero.

Variables de entorno (ver .env.example):
    R2_ACCOUNT_ID
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET
    R2_PUBLIC_BASE_URL   → dominio público del bucket, ej: https://s3.cracktcg.com
"""

import logging
import threading

from django.conf import settings

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client = None

# Tope de conexiones HTTP reutilizables hacia R2. Tiene que quedar por encima de
# los hilos de `sync_catalog_images --workers`, si no el pool se llena y se
# pierde la conexión persistente.
MAX_POOL_CONNECTIONS = 64


class R2ConfigurationError(Exception):
    pass


class R2UploadError(Exception):
    pass


def _require(name: str) -> str:
    value = getattr(settings, name, "")
    if not value:
        raise R2ConfigurationError(
            f"Falta {name} en el entorno. Configurá las credenciales de R2 en .env "
            f"(ver .env.example)."
        )
    return value


def get_client():
    """Cliente boto3 cacheado. Se crea una sola vez por proceso."""
    global _client
    if _client is not None:
        return _client

    with _client_lock:
        if _client is not None:
            return _client

        try:
            import boto3
            from botocore.config import Config
        except ImportError as exc:  # pragma: no cover
            raise R2ConfigurationError(
                "boto3 no está instalado. Corré: pip install -r requirements.txt"
            ) from exc

        account_id = _require("R2_ACCOUNT_ID")

        _client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=_require("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=_require("R2_SECRET_ACCESS_KEY"),
            region_name="auto",
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                s3={"addressing_style": "path"},
                # El pool por defecto es de 10. La sincronización de imágenes
                # corre con más hilos que eso, y cuando el pool se llena boto3
                # descarta la conexión: la próxima request paga un handshake TLS
                # nuevo, que es justo lo que más tarda. Con holgura no pasa.
                max_pool_connections=MAX_POOL_CONNECTIONS,
            ),
        )
        return _client


def public_url(key: str) -> str:
    base = _require("R2_PUBLIC_BASE_URL").rstrip("/")
    return f"{base}/{key.lstrip('/')}"


def upload_bytes(key: str, data: bytes, content_type: str = "image/webp") -> str:
    """Sube un objeto y devuelve su URL pública."""
    client = get_client()
    bucket = _require("R2_BUCKET")

    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            # El nombre del objeto es un hash del contenido, así que nunca cambia
            # para el mismo archivo: se puede cachear para siempre.
            CacheControl="public, max-age=31536000, immutable",
        )
    except Exception as exc:  # noqa: BLE001 — boto3 tira muchas excepciones distintas
        raise R2UploadError(f"No se pudo subir {key} a R2: {exc}") from exc

    return public_url(key)


def object_exists(key: str) -> bool:
    """True si el objeto ya está en el bucket (para no re-subir en reintentos)."""
    client = get_client()
    bucket = _require("R2_BUCKET")
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception:  # noqa: BLE001 — un 404 también llega como excepción
        return False


def is_configured() -> bool:
    """True si están todas las credenciales. Útil para saltear pasos en tests/dev."""
    try:
        for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
                     "R2_BUCKET", "R2_PUBLIC_BASE_URL"):
            _require(name)
        return True
    except R2ConfigurationError:
        return False
