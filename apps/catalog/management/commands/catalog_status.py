"""
Radiografía de la ingesta de imágenes del catálogo.

Contesta la única pregunta que importa: ¿esto está avanzando o está trabado?
El tamaño del bucket en R2 es un indicador lento y engañoso; la verdad está en
`image_status` y en el historial de django-q.

Uso:
    python manage.py catalog_status
    python manage.py catalog_status --errors 20    # más detalle de fallas
"""

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from apps.catalog.models import CatalogCard

# Peso medido de las tres versiones WebP de una carta (thumb + medium + full).
# Sale de dividir lo que pesa el bucket por las cartas ya subidas.
AVG_KB_PER_CARD = 205


class Command(BaseCommand):
    help = "Muestra el avance de la descarga de imágenes y el estado del qcluster"

    def add_arguments(self, parser):
        parser.add_argument("--errors", type=int, default=5, help="Errores distintos a listar.")

    def handle(self, *args, **options):
        self._progress()
        self._errors(options["errors"])
        self._schedule()
        self._history()

    # ------------------------------------------------------------------ #

    def _progress(self):
        counts = dict(
            CatalogCard.objects.values_list("image_status")
            .annotate(n=Count("id"))
            .values_list("image_status", "n")
        )
        ready = counts.get(CatalogCard.IMAGE_READY, 0)
        pending = counts.get(CatalogCard.IMAGE_PENDING, 0)
        failed = counts.get(CatalogCard.IMAGE_FAILED, 0)
        total = ready + pending + failed

        self.stdout.write(self.style.MIGRATE_HEADING("\nIMÁGENES"))
        if not total:
            self.stdout.write("  El catálogo está vacío.")
            return

        pct = 100 * ready / total
        self.stdout.write(f"  Listas     {ready:>7}  ({pct:.1f}%)")
        self.stdout.write(f"  Pendientes {pending:>7}")
        self.stdout.write(f"  Fallidas   {failed:>7}")
        self.stdout.write(f"  Total      {total:>7}")

        done_gb = ready * AVG_KB_PER_CARD / 1024 / 1024
        full_gb = total * AVG_KB_PER_CARD / 1024 / 1024
        self.stdout.write(
            f"\n  R2 esperado: ~{done_gb:.2f} GB subidos de ~{full_gb:.2f} GB totales."
        )
        self.stdout.write(
            "  Si el bucket pesa mucho menos que eso, el problema es la subida a R2.\n"
            "  Si coincide, el problema es que la tarea no llega a procesar más cartas."
        )

    def _errors(self, limit):
        rows = (
            CatalogCard.objects.filter(image_status=CatalogCard.IMAGE_FAILED)
            .exclude(image_error="")
            .values_list("image_error")
            .annotate(n=Count("id"))
            .order_by("-n")[:limit]
        )
        if not rows:
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\nERRORES MÁS FRECUENTES"))
        for error, n in rows:
            self.stdout.write(f"  {n:>6}x  {error[:150]}")

    def _schedule(self):
        from django_q.models import Schedule

        self.stdout.write(self.style.MIGRATE_HEADING("\nTAREA PROGRAMADA"))
        schedule = Schedule.objects.filter(name="catalog-refresh").first()
        if not schedule:
            self.stdout.write(self.style.ERROR(
                "  NO está programada. Nada va a correr solo.\n"
                "  Programala con: python manage.py schedule_catalog_refresh --hourly"
            ))
            return

        now = timezone.localtime()
        next_run = timezone.localtime(schedule.next_run) if schedule.next_run else None
        self.stdout.write(f"  Cadencia:       {schedule.get_schedule_type_display()}")
        self.stdout.write(f"  Próxima corrida: {next_run:%d/%m %H:%M}" if next_run else "  Sin próxima corrida")
        self.stdout.write(f"  Ahora:           {now:%d/%m %H:%M}")

        if next_run and next_run < now - timezone.timedelta(minutes=10):
            self.stdout.write(self.style.ERROR(
                "  next_run quedó en el pasado: el qcluster no la está levantando."
            ))

    def _history(self):
        from django_q.models import Failure, Success

        self.stdout.write(self.style.MIGRATE_HEADING("\nÚLTIMAS CORRIDAS DEL CATÁLOGO"))

        rows = []
        for model, label in ((Success, "OK"), (Failure, "FALLÓ")):
            for task in model.objects.filter(func="apps.catalog.tasks.refresh_catalog").order_by("-started")[:10]:
                rows.append((task.started, label, task, task.stopped))

        if not rows:
            self.stdout.write(self.style.ERROR(
                "  Nunca terminó una sola corrida.\n"
                "  Si en los logs ves 'processing ... refresh_catalog' pero nunca\n"
                "  'Processed', la tarea se está muriendo a mitad de camino\n"
                "  (timeout del cluster o reinicio del contenedor en Render)."
            ))
            return

        for started, label, task, stopped in sorted(rows, reverse=True)[:10]:
            dur = (stopped - started).total_seconds() if stopped else 0
            style = self.style.SUCCESS if label == "OK" else self.style.ERROR
            self.stdout.write(
                f"  {timezone.localtime(started):%d/%m %H:%M}  "
                + style(f"{label:<6}")
                + f"{dur:>6.0f}s  {str(task.result)[:110]}"
            )
