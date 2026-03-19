"""
Users Views
============
"""

import os
from rest_framework import generics, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import User

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


class CreateSuperuserView(APIView):
    """
    Crea el superusuario inicial. Protegido por ADMIN_SECRET en el header.
    Solo funciona si no existe ningún superusuario todavía.
    DELETE este endpoint una vez creado el admin.
    """

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        secret = request.headers.get("X-Admin-Secret")
        if not secret or secret != os.environ.get("ADMIN_SECRET"):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        if User.objects.filter(is_superuser=True).exists():
            return Response({"detail": "Superuser already exists."}, status=status.HTTP_400_BAD_REQUEST)

        email = request.data.get("email")
        username = request.data.get("username")
        password = request.data.get("password")

        if not all([email, username, password]):
            return Response({"detail": "email, username and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        User.objects.create_superuser(username=username, email=email, password=password)
        return Response({"detail": "Superuser created."}, status=status.HTTP_201_CREATED)
