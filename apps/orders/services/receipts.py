"""
Comprobantes de transferencia
==============================
El comprador sube el comprobante en el checkout y la orden nace recién con ese
archivo encima: sin comprobante no hay orden, así que no hay nada que vencer.

Dónde vive el archivo
---------------------
En un bucket de R2 **privado**, separado del bucket público del catálogo. Un
comprobante es un documento bancario con nombre, CBU y saldo del comprador: no
puede quedar servido en un dominio público donde cualquiera con la URL lo abre
para siempre. El admin lo mira con un link firmado que caduca en 15 minutos.

Es también lo que resuelve el PDF: R2 devuelve el archivo tal cual se subió, sin
las restricciones de entrega de PDF que tiene Cloudinary ni transformaciones que
se facturen.

El token que viaja al frontend
------------------------------
La subida ocurre *antes* de que exista la orden, así que el front tiene que
devolvernos después a qué archivo se refiere. En vez de la clave pelada (que
dejaría a cualquiera apuntar una orden a un objeto arbitrario del bucket) se
devuelve la clave firmada y con vencimiento: `store_receipt` la firma,
`resolve_receipt_token` la abre al crear la orden.
"""

import io
import logging
import os
import uuid
from datetime import datetime

from django.conf import settings
from django.core import signing

from apps.catalog.services.r2 import R2ConfigurationError, get_client

logger = logging.getLogger(__name__)

FOLDER = "comprobantes"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB, antes de comprimir
IMAGE_MAX_SIDE = 1800
JPEG_QUALITY = 80

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "heic", "heif", "pdf"}
PDF_CONTENT_TYPE = "application/pdf"

# Cuánto vale el token entre que se sube el archivo y se crea la orden. Es el
# tiempo que puede tardar el comprador en apretar "Confirmar" después de elegir
# el comprobante; de sobra con una hora.
TOKEN_MAX_AGE_SECONDS = 60 * 60
SIGNING_SALT = "orders.receipt"

# Vigencia del link que abre el admin. Corto a propósito: si el link se filtra
# (historial, captura, reenvío), deja de servir enseguida.
VIEW_URL_TTL_SECONDS = 15 * 60


class ReceiptError(Exception):
    """Base para los problemas de comprobante."""


class ReceiptValidationError(ReceiptError):
    """El archivo que mandó el comprador no sirve. El mensaje se le muestra."""


class ReceiptStorageError(ReceiptError):
    """Falló R2. El comprador ve un mensaje genérico y puede reintentar."""


def _bucket() -> str:
    bucket = getattr(settings, "R2_RECEIPTS_BUCKET", "")
    if not bucket:
        raise R2ConfigurationError(
            "Falta R2_RECEIPTS_BUCKET en el entorno. Es el bucket privado donde "
            "se guardan los comprobantes (ver .env.example)."
        )
    return bucket


def is_configured() -> bool:
    """True si se puede subir un comprobante ahora mismo."""
    try:
        _bucket()
        get_client()
        return True
    except R2ConfigurationError:
        return False


def _compress_image(content: bytes, name: str):
    """Reencoda la imagen a JPEG acotado. Devuelve (bytes, nombre, tipo).

    Una captura de pantalla de 4 MB no aporta nada sobre una de 300 KB para
    leer un comprobante. Si Pillow no puede abrirla (HEIC de iPhone, por
    ejemplo) se guarda tal cual: perder la venta por un formato raro sería peor.
    """
    from PIL import Image, ImageOps

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
        image = ImageOps.exif_transpose(image)

        if image.mode not in ("RGB", "L"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode in ("RGBA", "LA", "P"):
                image = image.convert("RGBA")
                background.paste(image, mask=image.split()[-1])
            else:
                background.paste(image.convert("RGB"))
            image = background

        image.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        base = os.path.splitext(name)[0] or "comprobante"
        return buffer.getvalue(), f"{base}.jpg", "image/jpeg"
    except Exception:
        logger.warning("Comprobante %s no se pudo comprimir; se guarda original", name)
        return None


def store_receipt(uploaded_file) -> dict:
    """Valida y sube el comprobante. Devuelve lo que el front manda al crear la orden.

    Retorna {"token", "name", "content_type", "size"}; `token` es la clave del
    objeto firmada, que `resolve_receipt_token` traduce de vuelta.
    """
    if uploaded_file is None:
        raise ReceiptValidationError("Adjuntá el comprobante de la transferencia.")

    name = os.path.basename(getattr(uploaded_file, "name", "") or "comprobante")[:200]
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ReceiptValidationError(
            "El comprobante tiene que ser una imagen (jpg, png, webp, heic) o un PDF."
        )

    size = getattr(uploaded_file, "size", 0) or 0
    if size > MAX_BYTES:
        raise ReceiptValidationError(
            "El comprobante no puede pesar más de 10 MB. Probá con una captura de pantalla."
        )

    content = uploaded_file.read()
    if not content:
        raise ReceiptValidationError("El archivo está vacío.")
    if len(content) > MAX_BYTES:
        raise ReceiptValidationError("El comprobante no puede pesar más de 10 MB.")

    is_pdf = extension == "pdf" or content[:5] == b"%PDF-"
    if is_pdf:
        # La extensión sola la elige quien sube: un .pdf que no empieza con la
        # firma del formato no es un PDF, y no queremos guardar cualquier cosa.
        if content[:5] != b"%PDF-":
            raise ReceiptValidationError("El PDF del comprobante no es válido.")
        content_type = PDF_CONTENT_TYPE
    else:
        compressed = _compress_image(content, name)
        if compressed:
            content, name, content_type = compressed
            extension = "jpg"
        else:
            content_type = (
                getattr(uploaded_file, "content_type", "") or "application/octet-stream"
            ).lower()

    today = datetime.now()
    key = f"{FOLDER}/{today:%Y/%m}/{uuid.uuid4().hex}.{extension}"

    try:
        get_client().put_object(
            Bucket=_bucket(),
            Key=key,
            Body=content,
            ContentType=content_type,
            # Nombre original del archivo, para que el link firmado lo descargue
            # con un nombre reconocible en vez del uuid.
            ContentDisposition=f'inline; filename="{name}"',
            CacheControl="private, max-age=0, no-store",
        )
    except R2ConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 — boto3 tira muchas excepciones distintas
        raise ReceiptStorageError(f"No se pudo guardar el comprobante: {exc}") from exc

    return {
        "token": signing.dumps(key, salt=SIGNING_SALT),
        "name": name,
        "content_type": content_type,
        "size": len(content),
    }


def resolve_receipt_token(token: str) -> str:
    """Devuelve la clave del objeto que representa el token. Valida firma y edad."""
    try:
        return signing.loads(
            str(token or ""), salt=SIGNING_SALT, max_age=TOKEN_MAX_AGE_SECONDS
        )
    except signing.SignatureExpired as exc:
        raise ReceiptValidationError(
            "El comprobante que subiste caducó. Volvé a adjuntarlo."
        ) from exc
    except signing.BadSignature as exc:
        raise ReceiptValidationError("El comprobante no es válido. Volvé a adjuntarlo.") from exc


def view_url(key: str, expires_in: int = VIEW_URL_TTL_SECONDS) -> str:
    """Link firmado y temporal para ver el comprobante desde el admin.

    Devuelve "" si no hay clave o si R2 no está configurado: el admin muestra
    "sin comprobante" en vez de reventar la lista de órdenes.
    """
    if not key:
        return ""
    try:
        return get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": key},
            ExpiresIn=int(expires_in),
        )
    except Exception:  # noqa: BLE001 — nunca puede tumbar una vista del admin
        logger.exception("No se pudo firmar el link del comprobante %s", key)
        return ""


def delete_receipt(key: str) -> bool:
    """Borra el objeto del bucket. True si se pudo."""
    if not key:
        return False
    try:
        get_client().delete_object(Bucket=_bucket(), Key=key)
        return True
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo borrar el comprobante %s", key)
        return False
