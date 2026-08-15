"""
Programa el refresco automático del catálogo en django-q.

Se corre UNA sola vez. A partir de ahí el qcluster se encarga: cada semana relee
las expansiones, importa las que cambiaron y baja las imágenes nuevas.

Uso:
    python manage.py schedule_catalog_refresh              # todos los lunes 4am
    python manage.py schedule_catalog_refresh --daily      # todos los días 4am
    python manage.py schedule_catalog_refresh --hourly     # cada hora (carga inicial)
    python manage.py schedule_catalog_refresh --remove     # lo desprograma
    python manage.py schedule_catalog_refresh --run-now    # lo ejecuta ya, sin programar

Para la primera carga del catálogo entero, `--hourly` deja que el worker vaya
bajando las imágenes de a tandas sin pasarse del timeout del cluster. Cuando ya
no queden pendientes, volvé a dejarlo semanal.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from django_q.models import Schedule

TASK_NAME = "catalog-refresh"
TASK_FUNC = "apps.catalog.tasks.refresh_catalog"


class Command(BaseCommand):
    help = "Programa (o quita) el refresco semanal del catálogo de cartas"

    def add_arguments(self, parser):
        parser.add_argument("--daily", action="store_true", help="Diario en vez de semanal.")
        parser.add_argument(
            "--hourly", action="store_true",
            help="Cada hora. Para la carga inicial; después volvé a semanal.",
        )
        parser.add_argument("--hour", type=int, default=4, help="Hora de corrida (0-23).")
        parser.add_argument("--remove", action="store_true", help="Desprograma la tarea.")
        parser.add_argument("--run-now", action="store_true", help="Ejecuta ahora y sale.")

    def handle(self, *args, **options):
        if options["run_now"]:
            from apps.catalog.tasks import refresh_catalog

            self.stdout.write("Actualizando el catálogo...\n")
            self.stdout.write(self.style.SUCCESS(refresh_catalog()))
            return

        if options["remove"]:
            deleted, _ = Schedule.objects.filter(name=TASK_NAME).delete()
            if deleted:
                self.stdout.write(self.style.SUCCESS("Refresco automático desprogramado."))
            else:
                self.stdout.write("No había ninguna tarea programada.")
            return

        now = timezone.localtime()

        if options["hourly"]:
            schedule_type = Schedule.HOURLY
            next_run = now + timezone.timedelta(minutes=1)
        else:
            schedule_type = Schedule.DAILY if options["daily"] else Schedule.WEEKLY
            # Próxima corrida: hoy a la hora pedida, o mañana si ya pasó.
            next_run = now.replace(hour=options["hour"], minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timezone.timedelta(days=1)

        schedule, created = Schedule.objects.update_or_create(
            name=TASK_NAME,
            defaults={
                "func": TASK_FUNC,
                "schedule_type": schedule_type,
                "next_run": next_run,
                "repeats": -1,  # para siempre
            },
        )

        if options["hourly"]:
            cadence = "cada hora"
        elif options["daily"]:
            cadence = "todos los días"
        else:
            cadence = "una vez por semana"

        verb = "Programado" if created else "Actualizado"
        self.stdout.write(self.style.SUCCESS(
            f"{verb}: el catálogo se refresca {cadence}.\n"
            f"Próxima corrida: {timezone.localtime(schedule.next_run):%d/%m/%Y %H:%M}"
        ))

        if options["hourly"]:
            from apps.catalog.models import CatalogCard

            pending = CatalogCard.objects.filter(image_status=CatalogCard.IMAGE_PENDING).count()
            if pending:
                from apps.catalog.tasks import MAX_IMAGES_PER_RUN

                hours = -(-pending // MAX_IMAGES_PER_RUN)  # división para arriba
                self.stdout.write(
                    f"\nQuedan {pending} imágenes: unas {hours} horas para terminar.\n"
                    "Cuando no queden pendientes, volvé a dejarlo semanal con:\n"
                    "  python manage.py schedule_catalog_refresh"
                )

        self.stdout.write(
            "\nRecordá que el worker tiene que estar levantado: python manage.py qcluster"
        )
