"""
Sincroniza en Django Q las tareas periódicas de órdenes.

Hoy no hay ninguna. La que había —vencer las órdenes de pago manual y devolver
su stock— dejó de tener sentido cuando la orden pasó a nacer con el comprobante
de transferencia adjunto: si existe la orden, la plata ya se envió, y no hay
plazo que se pueda incumplir.

El comando sigue existiendo (build.sh lo corre en cada deploy) para dar de baja
la tarea vieja en los entornos donde ya estaba registrada: borrarla del código
no la saca de la base de django_q.
"""

from django.core.management.base import BaseCommand

# Tareas que alguna vez estuvieron programadas y hay que desregistrar.
OBSOLETE_SCHEDULE_NAMES = ["expire_stale_cash_orders"]


class Command(BaseCommand):
    help = "Sincroniza las tareas programadas de órdenes en Django Q."

    def handle(self, *args, **options):
        from django_q.models import Schedule

        deleted, _ = Schedule.objects.filter(name__in=OBSOLETE_SCHEDULE_NAMES).delete()
        if deleted:
            self.stdout.write(
                self.style.SUCCESS(f"Tareas obsoletas dadas de baja: {deleted}.")
            )
        else:
            self.stdout.write("No hay tareas programadas de órdenes que sincronizar.")
