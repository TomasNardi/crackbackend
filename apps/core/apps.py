from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        # Ocultar modelos internos de JWT del panel admin
        from django.contrib import admin
        try:
            from rest_framework_simplejwt.token_blacklist.models import (
                BlacklistedToken, OutstandingToken,
            )
            admin.site.unregister(BlacklistedToken)
            admin.site.unregister(OutstandingToken)
        except Exception:
            pass
