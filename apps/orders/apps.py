from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    verbose_name = "Órdenes"

    def ready(self):
        post_migrate.connect(_ensure_mp_expiration_schedule, sender=self)


def _ensure_mp_expiration_schedule(**kwargs):
    try:
        from django_q.models import Schedule

        minutes = getattr(settings, "MERCADOPAGO_EXPIRATION_SWEEP_MINUTES", 10)
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            minutes = 10
        minutes = max(1, min(minutes, 120))

        Schedule.objects.update_or_create(
            name="MP checkout expiration sweep",
            defaults={
                "func": "apps.orders.tasks.expire_stale_mercadopago_checkouts",
                "schedule_type": Schedule.MINUTES,
                "minutes": minutes,
                "repeats": -1,
            },
        )
    except Exception:
        pass
