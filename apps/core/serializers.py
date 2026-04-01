"""
Core Serializers
=================
"""

from rest_framework import serializers
from .models import SiteConfig, EmailSubscription, ExchangeRate, ContactMessage


class ExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeRate
        fields = ("usd_to_ars", "updated_at")


class SiteConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteConfig
        fields = ("is_active", "maintenance_message")


class EmailSubscribeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailSubscription
        fields = ("email",)

    def validate_email(self, value):
        if EmailSubscription.objects.filter(email=value, is_active=True).exists():
            raise serializers.ValidationError("Este email ya está suscripto.")
        return value.lower()


class ContactMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ("name", "email", "message")
