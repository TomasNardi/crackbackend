"""
Descarga las imágenes del catálogo y las sube a Cloudflare R2.

Este es el paso lento. Se puede cortar con Ctrl+C y retomar cuando quieras: lleva
la cuenta de lo que ya bajó en `image_status`, así que nunca repite trabajo.

Uso:
    python manage.py sync_catalog_images                    # todo lo pendiente
    python manage.py sync_catalog_images --limit 200        # una tanda corta
    python manage.py sync_catalog_images --set 24541        # una expansión
    python manage.py sync_catalog_images --retry-failed     # reintenta las fallidas
    python manage.py sync_catalog_images --workers 8        # más paralelo
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import CatalogCard
from apps.catalog.services import images, r2

# El trabajo es de red, no de CPU, así que conviene paralelizar. 6 en paralelo es
# rápido sin castigar al CDN de TCGplayer, que nos está haciendo un favor.
DEFAULT_WORKERS = 6
CHUNK_SIZE = 200


class Command(BaseCommand):
    help = "Baja las imágenes del catálogo del CDN de TCGplayer y las sube a R2"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0, help="Máximo de cartas a procesar.")
        parser.add_argument("--set", type=int, default=0, help="Solo esta expansión (ID externo).")
        parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
        parser.add_argument("--retry-failed", action="store_true", help="Reintenta las fallidas.")
        parser.add_argument("--force", action="store_true", help="Rehace las que ya están listas.")

    def handle(self, *args, **options):
        if not r2.is_configured():
            raise CommandError(
                "R2 no está configurado. Cargá R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, R2_BUCKET y R2_PUBLIC_BASE_URL en .env "
                "(ver .env.example)."
            )

        queryset = self._build_queryset(options)
        total = queryset.count()

        if not total:
            self.stdout.write(self.style.SUCCESS("No hay imágenes pendientes."))
            return

        workers = max(1, options["workers"])
        self.stdout.write(f"Procesando {total} imágenes con {workers} hilos...\n")

        started = time.monotonic()
        done = failed = 0

        # Se procesa de a tandas para no traer 70.000 objetos a memoria de una.
        for chunk in self._chunks(queryset, CHUNK_SIZE):
            results = self._process_chunk(chunk, workers, options["force"])

            for card, urls, error in results:
                if error:
                    images.mark_failed(card, error)
                    failed += 1
                else:
                    images.apply_urls(card, urls)
                    done += 1

            elapsed = time.monotonic() - started
            rate = (done + failed) / elapsed if elapsed else 0
            remaining = total - done - failed
            eta = remaining / rate if rate else 0
            self.stdout.write(
                f"  {done + failed}/{total} — {done} ok, {failed} fallidas "
                f"— {rate:.1f}/s — faltan ~{eta / 60:.0f} min"
            )

        self.stdout.write(self.style.SUCCESS(f"\nListo: {done} imágenes, {failed} fallidas."))
        if failed:
            self.stdout.write(
                "Para reintentar las fallidas: "
                "python manage.py sync_catalog_images --retry-failed"
            )

    # ------------------------------------------------------------------ #

    def _build_queryset(self, options):
        queryset = CatalogCard.objects.all()

        if options["set"]:
            queryset = queryset.filter(card_set__external_id=options["set"])

        if options["force"]:
            pass  # todas
        elif options["retry_failed"]:
            queryset = queryset.filter(image_status=CatalogCard.IMAGE_FAILED)
        else:
            queryset = queryset.filter(image_status=CatalogCard.IMAGE_PENDING)

        queryset = queryset.order_by("card_set_id", "id")

        if options["limit"]:
            queryset = queryset[:options["limit"]]

        return queryset

    @staticmethod
    def _chunks(queryset, size):
        buffer = []
        for card in queryset.iterator(chunk_size=size):
            buffer.append(card)
            if len(buffer) >= size:
                yield buffer
                buffer = []
        if buffer:
            yield buffer

    @staticmethod
    def _process_chunk(cards, workers, force):
        """Devuelve [(card, urls, error), ...]. Ningún hilo toca la base."""
        results = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(images.prepare_card_images, card.source_image_url, force=force): card
                for card in cards
            }
            for future in as_completed(futures):
                card = futures[future]
                try:
                    results.append((card, future.result(), None))
                except Exception as exc:  # noqa: BLE001 — se registra por carta y sigue
                    results.append((card, None, str(exc)))
        return results
