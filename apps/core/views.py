"""
Core Views
===========
"""

import logging
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SiteConfig, ExchangeRate, ContactMessage, EmailSubscription
from .serializers import (
    SiteConfigSerializer, EmailSubscribeSerializer, ExchangeRateSerializer,
    ContactMessageSerializer, SolicitudVentaSerializer
)
from .emails import send_new_sale_request_notification

logger = logging.getLogger(__name__)


class ExchangeRateView(APIView):
    """GET /exchange-rate/ — tipo de cambio USD→ARS actual."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response(ExchangeRateSerializer(ExchangeRate.get()).data)


class SiteConfigView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        config = SiteConfig.get()
        return Response(SiteConfigSerializer(config).data)


class EmailSubscribeView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def post(self, request):
        serializer = EmailSubscribeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "¡Suscripción exitosa!"}, status=status.HTTP_201_CREATED)
        # Si el email ya existe, responder amigablemente
        email_errors = serializer.errors.get("email", [])
        if any("unique" in str(e).lower() or "already" in str(e).lower() or "existe" in str(e).lower() for e in email_errors):
            return Response({"message": "¡Ya estás suscripto!"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PingView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "ok"})


class ContactView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/h", method="POST", block=True))
    def post(self, request):
        serializer = ContactMessageSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "Mensaje recibido. Te respondemos pronto."}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SolicitudVentaCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/h", method="POST", block=True))
    def post(self, request):
        serializer = SolicitudVentaSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        solicitud = serializer.save()

        try:
            send_new_sale_request_notification(solicitud.id)
        except Exception:
            logger.exception("Error enviando notificación para la solicitud de venta %s", solicitud.id)

        return Response(
            {
                "message": "Recibimos tu solicitud. Te vamos a contactar pronto.",
                "id": solicitud.id,
            },
            status=status.HTTP_201_CREATED,
        )
