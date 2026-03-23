"""
Core Views
===========
"""

from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SiteConfig, Banner, ExchangeRate
from .serializers import SiteConfigSerializer, BannerSerializer, EmailSubscribeSerializer, ExchangeRateSerializer


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


class BannerViewSet(viewsets.ModelViewSet):
    queryset = Banner.objects.filter(is_active=True)
    serializer_class = BannerSerializer

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permissions.AllowAny()]
        return [permissions.IsAdminUser()]


class EmailSubscribeView(APIView):
    permission_classes = [permissions.AllowAny]

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=True))
    def post(self, request):
        serializer = EmailSubscribeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "¡Suscripción exitosa!"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PingView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "ok"})
