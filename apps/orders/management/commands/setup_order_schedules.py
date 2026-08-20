"""
Registra en Django Q las tareas periódicas de órdenes.

Hoy hay una sola: vencer las órdenes de pago manual que pasaron el plazo y
devolver al stock lo que tenían apartado. Sin esto, la promesa del email
("pasado ese tiempo la orden vence") no se cumple sola y la mercadería queda
reservada para siempre.

Es idempotente: se puede correr en cada deploy (build.sh lo hace).
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

TASK = "apps.orders.tasks.expire_stale_cash_orders"
SCHEDULE_NAME = "expire_stale_cash_orders"


class Command(BaseCommand):
    help = "Crea o actualiza las tareas programadas de órdenes en Django Q."

    def handle(self, *args, **options):
        from django_q.models import Schedule

        schedule, created = Schedule.objects.update_or_create(
            name=SCHEDULE_NAME,
            defaults={
                "func": TASK,
                "schedule_type": Schedule.HOURLY,
                # Chequear cada hora alcanza: el plazo se mide en horas y una
                # reserva de más no le hace daño a nadie.
                "repeats": -1,
                "next_run": timezone.now(),
            },
        )

        verbo = "creada" if created else "actualizada"
        self.stdout.write(
            self.style.SUCCESS(f"Tarea '{schedule.name}' {verbo} (cada hora).")
        )
