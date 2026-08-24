import json
import uuid

from django import forms
from django.core.exceptions import ValidationError

from .models import Product, ProductImage
from .services.cloudinary_service import MAX_PRODUCT_IMAGES


class ProductAdminForm(forms.ModelForm):
    cloudinary_draft_token = forms.CharField(required=False, widget=forms.HiddenInput())
    images_payload = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Product
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # El nombre se autocompleta desde la carta del catálogo, así que dejarlo
        # vacío es válido. Si escribís uno propio, gana el tuyo.
        self.fields["name"].required = False
        self.fields["name"].help_text = (
            "Dejalo vacío para tomarlo de la carta del catálogo."
        )

        draft_token = self.initial.get("cloudinary_draft_token") or str(uuid.uuid4())

        self.fields["cloudinary_draft_token"].initial = draft_token
        self.fields["images_payload"].initial = self.initial_payload()

    def initial_payload(self):
        """
        Con qué imágenes arranca la galería del uploader.

        Van las filas de `ProductImage` y, atrás, las URLs que el producto ya
        muestra en `image_url*` y que todavía no son filas: la que copió
        `apply_catalog_image_fallback` desde la carta, o una cargada a mano
        antes de que existiera la galería.

        Esas entran sin `id` —`sync_product_gallery` las materializa al
        guardar— y son la clave del asunto: sin ellas la galería arrancaba
        vacía aunque el producto tuviera imagen, y la primera foto que subías
        no se sumaba, la reemplazaba.
        """
        payload = []

        if not (self.instance and self.instance.pk):
            return json.dumps(payload)

        seen_urls = set()

        for image in self.instance.images.order_by("order_index", "id")[:MAX_PRODUCT_IMAGES]:
            seen_urls.add(image.secure_url)
            payload.append({
                "id": image.id,
                "secure_url": image.secure_url,
                "public_id": image.public_id,
                "source": image.source,
                "order_index": image.order_index,
                "status": image.status,
            })

        for url in self.instance.legacy_image_urls():
            if len(payload) >= MAX_PRODUCT_IMAGES:
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            payload.append({
                "id": None,
                "secure_url": url,
                "public_id": "",
                "source": ProductImage.SOURCE_URL,
                "order_index": len(payload),
                "status": ProductImage.STATUS_UPLOADED,
            })

        return json.dumps(payload)

    def clean(self):
        cleaned = super().clean()
        card = cleaned.get("catalog_card")

        if not cleaned.get("name"):
            if not card:
                self.add_error(
                    "name",
                    "Poné un nombre, o elegí una carta del catálogo para tomarlo de ahí.",
                )
            else:
                # El número va sí o sí: sin él, dos versiones de la misma carta
                # en el mismo set quedarían con nombre y slug idénticos.
                label = card.name
                if card.number and card.number not in label:
                    label = f"{label} {card.number}"
                cleaned["name"] = f"{label} — {card.card_set.name}"[:255]

        # El TCG sale de la expansión, no hace falta elegirlo a mano.
        if card and not cleaned.get("tcg"):
            cleaned["tcg"] = card.card_set.tcg

        return cleaned

    def clean_images_payload(self):
        raw = self.cleaned_data.get("images_payload") or "[]"

        try:
            items = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError("Payload de imágenes inválido.") from exc

        if not isinstance(items, list):
            raise ValidationError("Payload de imágenes inválido.")

        if len(items) > MAX_PRODUCT_IMAGES:
            raise ValidationError(f"Máximo {MAX_PRODUCT_IMAGES} imágenes por producto.")

        normalized = []
        for item in items:
            if not isinstance(item, dict):
                raise ValidationError("Payload de imágenes inválido.")

            raw_id = item.get("id")
            if raw_id in (None, "", 0):
                image_id = None
            else:
                try:
                    image_id = int(raw_id)
                except (TypeError, ValueError):
                    raise ValidationError("Payload de imágenes inválido.")

            url = (item.get("secure_url") or "").strip()

            # Sin id, la URL es lo único que la identifica: es una imagen que
            # todavía no tiene fila propia y hay que poder crearla al guardar.
            if image_id is None and not url:
                raise ValidationError("Hay imágenes sin URL en la galería.")

            if url:
                if not url.lower().startswith(("http://", "https://")):
                    raise ValidationError("Las imágenes tienen que ser URLs http o https.")
                if len(url) > 800:
                    raise ValidationError("La URL de una imagen es demasiado larga (máx. 800).")

            normalized.append({
                "id": image_id,
                "secure_url": url,
                "public_id": (item.get("public_id") or "")[:255],
                "source": item.get("source") or "",
            })

        return json.dumps(normalized)
