from django.core.management.base import BaseCommand

from apps.orders.tasks import expire_stale_cash_orders


class Command(BaseCommand):
    help = (
        "Vence órdenes de pago manual (efectivo, transferencia, crypto) que pasaron "
        "el plazo sin pagarse y devuelve la mercadería reservada al stock."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=300,
            help="Cantidad máxima de órdenes a procesar por corrida.",
        )

    def handle(self, *args, **options):
        batch_size = max(1, int(options["batch_size"]))
        result = expire_stale_cash_orders(batch_size=batch_size)
        self.stdout.write(
            self.style.SUCCESS(
                f"Sweep completado. procesados={result['processed']} "
                f"vencidos={result['expired']}"
            )
        )
