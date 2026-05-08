from django.core.management.base import BaseCommand

from apps.products.services.cloudinary_service import purge_orphan_images


class Command(BaseCommand):
    help = "Elimina imágenes huérfanas de productos (DB y Cloudinary)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Cantidad de horas mínimas para considerar una imagen como huérfana.",
        )

    def handle(self, *args, **options):
        hours = max(1, int(options.get("hours", 24)))
        result = purge_orphan_images(older_than_hours=hours)

        self.stdout.write(
            self.style.SUCCESS(
                f"Cleanup completado. Candidatas: {result['orphan_candidates']} · "
                f"Borradas en Cloudinary: {result['deleted_assets']} · "
                f"Errores: {len(result['errors'])}"
            )
        )

        if result["errors"]:
            for err in result["errors"]:
                self.stdout.write(self.style.WARNING(f"- {err}"))
