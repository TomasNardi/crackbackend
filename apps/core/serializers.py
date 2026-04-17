"""
Core Serializers
=================
"""

from rest_framework import serializers
from .models import (
    SiteConfig,
    EmailSubscription,
    ExchangeRate,
    ContactMessage,
    SolicitudVenta,
)


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ("usd_to_ars", "updated_at")


class SiteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteConfig
        fields = ("is_active", "maintenance_message", "cash_discount_enabled", "cash_discount_percent")


class EmailSubscribeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailSubscription
        fields = ("email",)

    def validate_email(self, value):
        return value.lower()


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "message")


class SolicitudVentaSerializer(serializers.ModelSerializer):
    class Meta:
        model = SolicitudVenta
        fields = (
            "id",
            "nombre_completo",
            "email",
            "celular",
            "tipo_coleccion",
            "imagenes",
            "estado",
            "fecha_creacion",
        )
        read_only_fields = ("id", "estado", "fecha_creacion")

    def validate_nombre_completo(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError("Ingresá un nombre válido.")
        return value

    def validate_celular(self, value):
        value = value.strip()
        if len(value) < 7:
            raise serializers.ValidationError("Ingresá un celular válido.")
        return value

    def validate_imagenes(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError("Debés subir al menos una imagen.")

        normalized_images = []
        for image in value:
            if not isinstance(image, dict):
                raise serializers.ValidationError("Cada imagen debe incluir secure_url y public_id.")

            secure_url = str(image.get("secure_url", "")).strip()
            public_id = str(image.get("public_id", "")).strip()

            if not secure_url:
                raise serializers.ValidationError("Cada imagen debe incluir secure_url.")
            if not secure_url.startswith("https://"):
                raise serializers.ValidationError("Las imágenes deben usar una URL segura.")

            normalized_images.append({
                "secure_url": secure_url,
                "public_id": public_id,
            })

        return normalized_images
