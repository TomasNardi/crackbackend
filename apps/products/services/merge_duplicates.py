"""
Consolida publicaciones duplicadas de la misma carta en una sola con stock.

Antes, cargar 3 copias de la misma carta creaba 3 productos: la tienda mostraba
el mismo Ampharos NM cuatro veces seguidas. Ahora es una publicación con stock 3,
pero lo que ya se cargó con el criterio viejo sigue duplicado en la base.

Qué se considera "la misma publicación": misma carta del catálogo (o mismo
nombre si no tiene carta), misma categoría, misma condición, misma
certificación, mismo precio y mismo descuento. La condición y el precio quedan
adentro de la clave a propósito: dos Ampharos, uno NM y uno LP, son dos
publicaciones distintas y tienen que seguir separadas.

Lo usa el comando `merge_duplicate_products`.
"""

from collections import defaultdict

from django.db import transaction
from django.utils import timezone


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


def _merge_group(items):
    """Junta un grupo de duplicados. Devuelve (keeper, stock_total)."""
    from apps.orders.models import OrderItem

    with_photos = [p for p in items if p.images.all()]
    keeper = with_photos[0] if with_photos else items[0]
    losers = [p for p in items if p.pk != keeper.pk]
    total = sum(units(p) for p in items)
    loser_ids = [p.pk for p in losers]

    with transaction.atomic():
        # Las compras viejas apuntan al duplicado que se va. Se repuntan al que
        # queda para no perder el historial (el FK es SET_NULL).
        OrderItem.objects.filter(product_id__in=loser_ids).update(product=keeper)

        # Sugeridos: si alguien recomendaba el duplicado, pasa a recomendar el
        # que queda.
        for loser in losers:
            for parent in loser.suggested_in.all():
                parent.suggested_products.remove(loser)
                parent.suggested_products.add(keeper)
            for carousel in loser.carousel_suggested_in.all():
                carousel.suggested_products.remove(loser)
                carousel.suggested_products.add(keeper)
            for suggested in loser.suggested_products.all():
                keeper.suggested_products.add(suggested)

        keeper.__class__.objects.filter(pk__in=loser_ids).delete()

        # `update()` y no `save()`: save() recalcula el slug y la imagen del
        # catálogo, que son consultas de más por cada grupo. Acá solo cambia el
        # stock.
        keeper.__class__.objects.filter(pk=keeper.pk).update(
            stock_quantity=total,
            in_stock=total > 0,
            updated_at=timezone.now(),
        )
        keeper.stock_quantity = total
        keeper.in_stock = total > 0

    return keeper, total


def merge_duplicate_products(queryset=None, apply=False, on_progress=None):
    """
    Busca duplicados y (si `apply`) los consolida.

    Con `queryset` acotás a un subconjunto; sin él barre todo el catálogo
    publicado. Devuelve un reporte para mostrar.

    `on_progress` recibe cada línea apenas se resuelve el grupo: consolidar
    contra una base remota tarda, y una consola muda parece colgada.
    """
    from apps.products.models import Product

    if queryset is None:
        queryset = Product.objects.all()

    # Solo se juntan publicaciones vivas: una que ya se vendió quedó en 0 y
    # sumarla resucitaría stock que no existe.
    queryset = (
        queryset.filter(in_stock=True)
        .select_related("category")
        .prefetch_related("images")
        .order_by("id")
    )

    groups = defaultdict(list)
    for product in queryset:
        groups[identity(product)].append(product)

    report = {"merged": 0, "removed": 0, "lines": [], "skipped": []}

    for items in groups.values():
        if len(items) < 2:
            continue

        # Las fotos propias son de una unidad concreta. Si dos duplicados tienen
        # fotos distintas, juntarlos perdería una: se avisa y se deja.
        if len([p for p in items if p.images.all()]) > 1:
            report["skipped"].append(
                f"{items[0].name} ({len(items)} publicaciones): "
                "más de una tiene fotos propias, hay que unirlas a mano."
            )
            continue

        if apply:
            keeper, total = _merge_group(items)
        else:
            with_photos = [p for p in items if p.images.all()]
            keeper = with_photos[0] if with_photos else items[0]
            total = sum(units(p) for p in items)

        category = keeper.category.name if keeper.category else "—"
        removed = len(items) - 1
        line = (
            f"{keeper.name} · {category} → 1 publicación con stock {total} "
            f"(se eliminan {removed})"
        )
        report["lines"].append(line)
        report["merged"] += 1
        report["removed"] += removed

        if on_progress:
            on_progress(line)

    return report
