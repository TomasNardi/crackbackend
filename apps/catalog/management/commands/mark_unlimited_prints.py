"""
Marca como "(Unlimited)" las cartas de los sets WOTC cuyo escaneo es 1st Edition.

La lógica vive en `apps.catalog.services.unlimited`, que también usa el endpoint
POST /api/v1/catalog/mark-unlimited/. Acá está solo la interfaz de consola.

`import_catalog` lo vuelve a correr al terminar, porque el import rebaja el
nombre desde la fuente y borraría el sufijo.

Uso:
    python manage.py mark_unlimited_prints
    python manage.py mark_unlimited_prints --sets FO N1   # solo algunos sets
    python manage.py mark_unlimited_prints --dry-run
    python manage.py mark_unlimited_prints --revert
"""

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.services import unlimited


class Command(BaseCommand):
    help = 'Agrega "(Unlimited)" al nombre de los singles de los sets WOTC'

    def add_arguments(self, parser):
        parser.add_argument(
            "--sets", nargs="+", metavar="ABBR", default=None,
            help=f"Abreviaturas a procesar. Por defecto: "
                 f"{' '.join(unlimited.DEFAULT_SETS)}. "
                 f"Disponibles: {' '.join(sorted(unlimited.AFFECTED_SETS))}.",
        )
        parser.add_argument(
            "--revert", action="store_true",
            help="Saca el sufijo en vez de agregarlo.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="No escribe en la base; solo informa.",
        )

    def handle(self, *args, **options):
        try:
            report = unlimited.mark_unlimited(
                abbreviations=options["sets"],
                revert=options["revert"],
                dry_run=options["dry_run"],
            )
        except unlimited.UnknownSetError as exc:
            raise CommandError(str(exc)) from exc

        for result in report["sets"]:
            label = result["set_name"] or "(sin cartas)"
            self.stdout.write(
                f"  {result['abbr']:<3} {label} — "
                f"{result['changed']}/{result['total']} singles"
            )

        total = report["total"]
        if options["dry_run"]:
            verb = "sacaría" if options["revert"] else "agregaría"
            self.stdout.write(self.style.WARNING(
                f"(dry-run) Se {verb} el sufijo en {total} cartas."
            ))
        elif options["revert"]:
            self.stdout.write(self.style.SUCCESS(f"Se sacó el sufijo de {total} cartas."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Se marcaron {total} cartas."))
