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
