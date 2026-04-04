"""
CrackBackend - URL Configuration
==================================
Todas las rutas de la API bajo /api/v1/.
"""

from django.contrib import admin
from django.urls import path, include

admin.site.index_title = "Panel de administración"
admin.site.site_title = "CRACK TCG"
admin.site.site_header = "CRACK TCG"

urlpatterns = [
    path("admin/", admin.site.urls),

    # API v1
    path("api/v1/", include("crackbackend.api_router")),
]
