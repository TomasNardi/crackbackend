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
from .newsletter_tokens import read_unsubscribe_token

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
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        email = serializer.validated_data["email"]
        subscription, created = EmailSubscription.objects.get_or_create(
            email=email,
            defaults={"is_active": True},
        )

        if created:
            return Response(
                {"message": "Ya estás adentro. Pronto vas a recibir novedades, ingresos y promos de CRACK."},
                status=status.HTTP_201_CREATED,
            )

        if subscription.is_active:
            return Response(
                {"message": "Ya formas parte de la newsletter. Cuando haya novedades, te avisamos por email."},
                status=status.HTTP_200_OK,
            )

        subscription.is_active = True
        subscription.save(update_fields=["is_active"])
        return Response(
            {"message": "Tu suscripción volvió a quedar activa. Vas a recibir nuestras próximas novedades."},
            status=status.HTTP_200_OK,
        )


class EmailUnsubscribeView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=True))
    def post(self, request):
        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response({"detail": "Token requerido."}, status=status.HTTP_400_BAD_REQUEST)

        email = read_unsubscribe_token(token)
        if not email:
            return Response(
                {"detail": "El enlace de desuscripción es inválido o expiró."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription = EmailSubscription.objects.filter(email=email).first()
        if not subscription or not subscription.is_active:
            return Response({"message": "Tu email ya estaba desuscripto."}, status=status.HTTP_200_OK)

        subscription.is_active = False
        subscription.save(update_fields=["is_active"])
        return Response({"message": "Ya no recibirás novedades por email."}, status=status.HTTP_200_OK)


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
