"""
Junta publicaciones duplicadas de la misma carta en una sola con stock sumado.

Por defecto solo informa. Para escribir en la base:

    python manage.py merge_duplicate_products --apply
"""

from django.core.management.base import BaseCommand

from apps.products.services.merge_duplicates import merge_duplicate_products


class Command(BaseCommand):
    help = "Junta publicaciones duplicadas de la misma carta en una sola con stock sumado."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Escribe los cambios. Sin este flag solo muestra qué haría.",
        )

    def handle(self, *args, **options):
        apply_changes = options["apply"]
        report = merge_duplicate_products(apply=apply_changes)

        if not report["lines"] and not report["skipped"]:
            self.stdout.write(self.style.SUCCESS("No hay publicaciones duplicadas."))
            return

        for line in report["lines"]:
            self.stdout.write(line)

        verbo = "Consolidadas" if apply_changes else "Se consolidarían"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verbo} {report['merged']} publicaciones · "
                f"{report['removed']} duplicados eliminados."
            )
        )

        for warning in report["skipped"]:
            self.stdout.write(self.style.WARNING(f"- {warning}"))

        if not apply_changes:
            self.stdout.write("Nada se escribió. Volvé a correrlo con --apply.")
