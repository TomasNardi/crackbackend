"""
CrackBackend - URL Configuration
==================================
Todas las rutas de la API bajo /api/v1/.
"""

from django.contrib import admin
from django.urls import path, include


urlpatterns = [
    path("admin/", admin.site.urls),

    # API v1
    path("api/v1/", include("crackbackend.api_router")),
]
