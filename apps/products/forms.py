import json
import uuid

from django import forms
from django.core.exceptions import ValidationError

from .models import Product


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
        payload = []

        if self.instance and self.instance.pk:
            for image in self.instance.images.order_by("order_index", "id")[:3]:
                payload.append({
                    "id": image.id,
                    "secure_url": image.secure_url,
                    "public_id": image.public_id,
                    "source": image.source,
                    "order_index": image.order_index,
                    "status": image.status,
                })

        self.fields["cloudinary_draft_token"].initial = draft_token
        self.fields["images_payload"].initial = json.dumps(payload)

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

        if len(items) > 3:
            raise ValidationError("Máximo 3 imágenes por producto.")

        return json.dumps(items)
