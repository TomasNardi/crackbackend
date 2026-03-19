"""
Users Views
============
"""

from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    UserTokenObtainPairSerializer,
    RegisterSerializer,
    UserProfileSerializer,
)


class UserTokenObtainPairView(TokenObtainPairView):
    """Login — devuelve access + refresh token con datos del usuario."""

    serializer_class = UserTokenObtainPairSerializer


class RegisterView(generics.CreateAPIView):
    """Registro público de nuevos usuarios."""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class UserProfileView(generics.RetrieveUpdateAPIView):
    """Perfil del usuario autenticado (GET y PATCH)."""

    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user
