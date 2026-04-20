"""
CrackBackend - URL Configuration
==================================
Todas las rutas de la API bajo /api/v1/.
"""

from django.contrib import admin
from django.conf import settings
from django.urls import path, include

admin.site.index_title = "Panel de administración"
admin.site.site_title = "CRACK TCG"
admin.site.site_header = "CRACK TCG"
admin.site.site_url = settings.SITE_URL

urlpatterns = [
    path("admin/", admin.site.urls),

    # API v1
    path("api/v1/", include("crackbackend.api_router")),
]
