from django.core.management.base import BaseCommand

from apps.orders.tasks import expire_stale_mercadopago_checkouts


class Command(BaseCommand):
    help = "Marca como vencidos checkouts de Mercado Pago pendientes y expirados."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=300,
            help="Cantidad maxima de registros a procesar por corrida.",
        )

    def handle(self, *args, **options):
        batch_size = max(1, int(options["batch_size"]))
        result = expire_stale_mercadopago_checkouts(batch_size=batch_size)
        self.stdout.write(
            self.style.SUCCESS(
                f"Sweep completado. procesados={result['processed']} expirados={result['expired']}"
            )
        )
