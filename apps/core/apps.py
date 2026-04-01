from django.apps import AppConfig, apps


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        # Ocultar modelos internos de JWT del panel admin
        from django.contrib import admin

        try:
            from rest_framework_simplejwt.token_blacklist.models import (
                BlacklistedToken,
                OutstandingToken,
            )

            admin.site.unregister(BlacklistedToken)
            admin.site.unregister(OutstandingToken)
        except Exception:
            pass

        admin.site.site_header = "Administración de Crack"
        admin.site.site_title = "Panel de administración"
        admin.site.index_title = "Gestión del sitio"

        # Ajustar etiquetas de Django Q al español para el panel de administración.
        try:
            from django_q.models import Failure, OrmQ, Schedule, Success

            django_q_app = apps.get_app_config("django_q")
            django_q_app.verbose_name = "Cola de tareas"

            Failure._meta.verbose_name = "Tarea fallida"
            Failure._meta.verbose_name_plural = "Tareas fallidas"

            OrmQ._meta.verbose_name = "Tarea en cola"
            OrmQ._meta.verbose_name_plural = "Tareas en cola"

            Schedule._meta.verbose_name = "Tarea programada"
            Schedule._meta.verbose_name_plural = "Tareas programadas"

            Success._meta.verbose_name = "Tarea exitosa"
            Success._meta.verbose_name_plural = "Tareas exitosas"
        except Exception:
            pass
