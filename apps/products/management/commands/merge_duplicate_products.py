"""
Consolida publicaciones duplicadas en una sola con stock.

Antes, cargar 3 copias de la misma carta creaba 3 productos: la tienda mostraba
el mismo Ampharos NM cuatro veces seguidas. Ahora es una publicación con stock 3,
pero lo que ya se cargó con el criterio viejo sigue duplicado en la base. Este
comando junta esos duplicados sumando el stock.

Qué se considera "la misma publicación": misma carta del catálogo (o mismo
nombre si no tiene carta), misma categoría, misma condición, misma
certificación, mismo precio y mismo descuento. La condición y el precio quedan
adentro de la clave a propósito: dos Ampharos, uno NM y uno LP, son dos
publicaciones distintas y tienen que seguir separadas.

Por defecto solo informa. Para escribir en la base:

    python manage.py merge_duplicate_products --apply
"""

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.orders.models import OrderItem
from apps.products.models import Product


def identity(product):
    """Clave de agrupación: dos productos con la misma clave son el mismo aviso."""
    card_key = (
        ("card", product.catalog_card_id)
        if product.catalog_card_id
        else ("name", (product.name or "").strip().lower())
    )
    return (
        card_key,
        product.category_id,
        product.tcg_id,
        product.condition_id,
        product.certification_entity_id,
        product.certification_grade_id,
        str(product.price_usd),
        product.discount_percent,
    )


def units(product):
    """Unidades que aporta un producto viejo al stock consolidado."""
    if product.stock_quantity is None:
        # Criterio viejo: un single sin cantidad era exactamente una unidad.
        return 1 if product.in_stock else 0
    return product.stock_quantity


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

        # Solo se juntan publicaciones vivas: una que ya se vendió quedó en 0 y
        # sumarla resucitaría stock que no existe.
        groups = defaultdict(list)
        queryset = (
            Product.objects.filter(in_stock=True)
            .select_related("category")
            .prefetch_related("images")
            .order_by("id")
        )
        for product in queryset:
            groups[identity(product)].append(product)

        duplicated = {key: items for key, items in groups.items() if len(items) > 1}

        if not duplicated:
            self.stdout.write(self.style.SUCCESS("No hay publicaciones duplicadas."))
            return

        merged_groups = 0
        removed = 0
        skipped = []

        for items in duplicated.values():
            with_photos = [p for p in items if p.images.all()]

            # Las fotos propias son de una unidad concreta. Si dos duplicados
            # tienen fotos distintas, juntarlos perdería una: se avisa y se deja.
            if len(with_photos) > 1:
                skipped.append(
                    f"{items[0].name} ({len(items)} publicaciones): "
                    "más de una tiene fotos propias, hay que unirlas a mano."
                )
                continue

            keeper = with_photos[0] if with_photos else items[0]
            losers = [p for p in items if p.pk != keeper.pk]
            total = sum(units(p) for p in items)

            self.stdout.write(
                f"{keeper.name} · {keeper.category.name} → 1 publicación con stock {total} "
                f"(se eliminan {len(losers)}: {[p.pk for p in losers]})"
            )

            if not apply_changes:
                merged_groups += 1
                removed += len(losers)
                continue

            with transaction.atomic():
                loser_ids = [p.pk for p in losers]

                # Las compras viejas apuntan al duplicado que se va. Se repuntan
                # al que queda para no perder el historial (el FK es SET_NULL).
                OrderItem.objects.filter(product_id__in=loser_ids).update(product=keeper)

                # Sugeridos: si alguien recomendaba el duplicado, pasa a
                # recomendar el que queda.
                for loser in losers:
                    for parent in loser.suggested_in.all():
                        parent.suggested_products.remove(loser)
                        parent.suggested_products.add(keeper)
                    for carousel in loser.carousel_suggested_in.all():
                        carousel.suggested_products.remove(loser)
                        carousel.suggested_products.add(keeper)
                    for suggested in loser.suggested_products.all():
                        keeper.suggested_products.add(suggested)

                Product.objects.filter(pk__in=loser_ids).delete()

                keeper.stock_quantity = total
                keeper.in_stock = total > 0
                keeper.save(update_fields=["stock_quantity", "in_stock", "updated_at"])

            merged_groups += 1
            removed += len(losers)

        verbo = "Consolidadas" if apply_changes else "Se consolidarían"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verbo} {merged_groups} publicaciones · {removed} duplicados eliminados."
            )
        )

        for warning in skipped:
            self.stdout.write(self.style.WARNING(f"- {warning}"))

        if not apply_changes:
            self.stdout.write("Nada se escribió. Volvé a correrlo con --apply.")
