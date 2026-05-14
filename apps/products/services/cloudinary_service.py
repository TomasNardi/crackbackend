import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone
from django.db.models import Q

from apps.products.models import ProductImage


MAX_PRODUCT_IMAGES = 3
ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "avif"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class CloudinaryConfig:
    cloud_name: str
    api_key: str
    api_secret: str
    upload_preset: str

    @property
    def upload_url(self):
        return f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/upload"

    @property
    def destroy_url(self):
        return f"https://api.cloudinary.com/v1_1/{self.cloud_name}/image/destroy"


class CloudinaryServiceError(Exception):
    pass


class CloudinaryConfigurationError(CloudinaryServiceError):
    pass


class CloudinaryValidationError(CloudinaryServiceError):
    pass


def get_config() -> CloudinaryConfig:
    cloud_name = getattr(settings, "CLOUDINARY_CLOUD_NAME", "")
    api_key = getattr(settings, "CLOUDINARY_API_KEY", "")
    api_secret = getattr(settings, "CLOUDINARY_API_SECRET", "")
    upload_preset = getattr(settings, "CLOUDINARY_ADMIN_UPLOAD_PRESET", "admin_upload")

    if not all([cloud_name, api_key, api_secret, upload_preset]):
        raise CloudinaryConfigurationError("Cloudinary no está configurado completamente en settings/env.")

    return CloudinaryConfig(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        upload_preset=upload_preset,
    )


def _sign_payload(params: dict, secret: str) -> str:
    serializable = {k: v for k, v in params.items() if v not in (None, "")}
    to_sign = "&".join(f"{key}={serializable[key]}" for key in sorted(serializable.keys()))
    return hashlib.sha1(f"{to_sign}{secret}".encode("utf-8")).hexdigest()


def _admin_webhook_url() -> str:
    base_url = getattr(settings, "BACKEND_PUBLIC_URL", "http://localhost:8000").rstrip("/")
    return f"{base_url}/api/v1/products/admin/cloudinary/webhook/"


def generate_signed_upload_payload(*, draft_token: str, slot: int, user_id: int | None = None) -> dict:
    config = get_config()

    timestamp = int(time.time())
    context_pairs = [f"draft_token={draft_token}", f"slot={slot}"]
    if user_id:
        context_pairs.append(f"admin_user={user_id}")

    payload = {
        "timestamp": timestamp,
        "upload_preset": config.upload_preset,
        "context": "|".join(context_pairs),
        "notification_url": _admin_webhook_url(),
    }
    signature = _sign_payload(payload, config.api_secret)

    return {
        "cloud_name": config.cloud_name,
        "api_key": config.api_key,
        "upload_url": config.upload_url,
        "timestamp": timestamp,
        "upload_preset": config.upload_preset,
        "context": payload["context"],
        "notification_url": payload["notification_url"],
        "signature": signature,
        "max_images": MAX_PRODUCT_IMAGES,
        "max_size_bytes": MAX_IMAGE_SIZE_BYTES,
        "allowed_extensions": sorted(ALLOWED_IMAGE_EXTENSIONS),
    }


def verify_notification_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    config = get_config()
    if not (timestamp and signature):
        return False

    signed_payload = raw_body.decode("utf-8") + timestamp
    expected_sha1 = hashlib.sha1(f"{signed_payload}{config.api_secret}".encode("utf-8")).hexdigest()
    expected_sha256 = hashlib.sha256(f"{signed_payload}{config.api_secret}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(signature, expected_sha1) or hmac.compare_digest(signature, expected_sha256)


def parse_context_map(context_value: str | dict | None) -> dict:
    if isinstance(context_value, dict):
        return context_value

    if not context_value:
        return {}

    out = {}
    chunks = str(context_value).split("|")
    for chunk in chunks:
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def validate_local_file(filename: str, size_bytes: int) -> None:
    if "." not in filename:
        raise CloudinaryValidationError("Formato inválido.")

    extension = filename.rsplit(".", 1)[-1].lower()
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise CloudinaryValidationError("Formato no permitido.")

    if size_bytes > MAX_IMAGE_SIZE_BYTES:
        raise CloudinaryValidationError("El archivo supera el tamaño máximo permitido.")


def create_pending_image(*, draft_token: str, secure_url: str, order_index: int, source: str, public_id: str = "", metadata: dict | None = None) -> ProductImage:
    if source not in {ProductImage.SOURCE_CLOUDINARY, ProductImage.SOURCE_URL}:
        raise CloudinaryValidationError("Origen de imagen inválido.")

    if order_index < 0 or order_index >= MAX_PRODUCT_IMAGES:
        raise CloudinaryValidationError("Orden de imagen inválido.")

    pending_count = ProductImage.objects.filter(product__isnull=True, draft_token=draft_token).count()
    if pending_count >= MAX_PRODUCT_IMAGES:
        raise CloudinaryValidationError("Máximo 3 imágenes por producto.")

    return ProductImage.objects.create(
        draft_token=draft_token,
        secure_url=secure_url,
        public_id=public_id,
        source=source,
        status=ProductImage.STATUS_UPLOADED,
        order_index=order_index,
        metadata=metadata or {},
    )


def attach_images_to_product(*, product, draft_token: str, ordered_image_ids: list[int]) -> list[ProductImage]:
    # Protección: Solo permitir ejecución desde el admin
    import inspect
    stack = inspect.stack()
    allowed_callers = ["save_model", "ProductAdmin"]
    if not any(caller.function in allowed_callers for caller in stack):
        raise CloudinaryValidationError("Las imágenes solo pueden modificarse desde el panel admin.")

    if len(ordered_image_ids) > MAX_PRODUCT_IMAGES:
        raise CloudinaryValidationError("Máximo 3 imágenes por producto.")

    selected_images = list(
        ProductImage.objects.filter(id__in=ordered_image_ids).filter(
            Q(product=product) | Q(product__isnull=True, draft_token=draft_token)
        )
    )
    selected_by_id = {img.id: img for img in selected_images}

    if len(selected_by_id) != len(ordered_image_ids):
        raise CloudinaryValidationError("Hay imágenes inválidas en el payload.")

    attached = []
    for index, image_id in enumerate(ordered_image_ids):
        image = selected_by_id[image_id]
        image.product = product
        image.draft_token = ""
        image.order_index = index
        if image.status == ProductImage.STATUS_PENDING:
            image.status = ProductImage.STATUS_UPLOADED
        image.save(update_fields=["product", "draft_token", "order_index", "status"])
        attached.append(image)

    ProductImage.objects.filter(product=product).exclude(id__in=ordered_image_ids).delete()
    product.sync_legacy_images_from_gallery(save=True)
    return attached


def remove_cloudinary_asset(public_id: str, invalidate: bool = True) -> dict:
    if not public_id:
        return {"result": "not_found"}

    config = get_config()
    timestamp = int(time.time())
    payload = {
        "public_id": public_id,
        "timestamp": timestamp,
        "invalidate": "true" if invalidate else "false",
    }
    signature = _sign_payload(payload, config.api_secret)

    response = requests.post(
        config.destroy_url,
        data={
            **payload,
            "api_key": config.api_key,
            "signature": signature,
        },
        timeout=15,
    )

    response.raise_for_status()
    return response.json()


def purge_orphan_images(*, older_than_hours: int = 24) -> dict:
    threshold = timezone.now() - timedelta(hours=older_than_hours)
    queryset = ProductImage.objects.filter(product__isnull=True, uploaded_at__lt=threshold)
    orphan_candidates = queryset.count()

    deleted_assets = 0
    errors = []
    for image in queryset.iterator(chunk_size=50):
        try:
            if image.source == ProductImage.SOURCE_CLOUDINARY and image.public_id:
                remove_cloudinary_asset(image.public_id, invalidate=True)
                deleted_assets += 1
            image.delete()
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

    return {
        "orphan_candidates": orphan_candidates,
        "deleted_assets": deleted_assets,
        "errors": errors,
    }
