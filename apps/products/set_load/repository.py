"""
Adaptador de Django para la carga masiva: todo lo que toca la base está acá.

Las altas reutilizan `bulk_load.create_products` (el mismo bulk_create de la
carga individual), así que un producto cargado en masa es indistinguible de
uno cargado a mano: mismo nombre, slug, imagen del catálogo y stock.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import BooleanField, ExpressionWrapper, Max, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.catalog import finishes
from apps.catalog.models import CardSet, CatalogCard

from .. import bulk_load
from ..models import BulkLoadReceipt, CardCondition, Product, ProductCategory
from .domain import ATTRIBUTES, KIND_SEALED, KIND_SINGLE, Existing, References

# Los recibos solo sirven para frenar reintentos: pasado un tiempo ya no llega
# ninguno y se borran para que la tabla no crezca sin fin.
RECEIPT_LIFETIME = timedelta(days=30)


class MissingCategory(Exception):
    """No existe la categoría a la que va un tipo de producto (Single o Sellado)."""


# ------------------------------------------------------------------ lectura
def card_set(set_id):
    return CardSet.objects.only("id", "name", "abbreviation", "language").filter(pk=set_id).first()


def set_cards(set_id):
    """Todas las cartas del set, ordenadas por número, con solo lo que dibuja la grilla.

    `is_card` separa cartas de sellados con el mismo criterio que el buscador
    (`IS_PLAYABLE_CARD`), calculado en la base: así no viaja `extended_data`.
    """
    cards = (
        CatalogCard.objects.filter(card_set_id=set_id)
        .annotate(is_card=ExpressionWrapper(bulk_load.IS_PLAYABLE_CARD, output_field=BooleanField()))
        .values("id", "name", "number", "rarity", "image_url_thumb", "is_card", "printings")
        .order_by("number", "name")
    )
    return [
        {
            "id": c["id"],
            "name": c["name"],
            "number": c["number"],
            "rarity": c["rarity"],
            "thumb": c["image_url_thumb"],
            "is_card": bool(c["is_card"]),
            # Acabados que existen de la carta; el primero es el por defecto.
            "printings": c["printings"] or [],
        }
        for c in cards
    ]


def stock_of(card_ids):
    """
    Lo que ya hay en stock de esas cartas, en una sola consulta agregada:
    {card_id: {"units": n, "price_usd": "x", "by_condition": {cond_id: n},
               "by_finish": {acabado: n}, "by_language": {idioma: n}}}.
    """
    if not card_ids:
        return {}
    rows = (
        Product.objects.filter(catalog_card_id__in=card_ids, in_stock=True)
        .values("catalog_card_id", "condition_id", "finish", "language")
        # Los productos viejos pueden tener el stock vacío: valen una unidad.
        .annotate(units=Sum(Coalesce("stock_quantity", Value(1))), price=Max("price_usd"))
        .order_by()
    )
    stock = {}
    for row in rows:
        current = stock.setdefault(
            row["catalog_card_id"],
            {"units": 0, "price_usd": None, "by_condition": {}, "by_finish": {}, "by_language": {}},
        )
        current["units"] += row["units"]
        if row["condition_id"]:
            key = str(row["condition_id"])
            current["by_condition"][key] = current["by_condition"].get(key, 0) + row["units"]
        if row["finish"]:
            current["by_finish"][row["finish"]] = current["by_finish"].get(row["finish"], 0) + row["units"]
        if row["language"]:
            current["by_language"][row["language"]] = current["by_language"].get(row["language"], 0) + row["units"]
        if row["price"] is not None and (
            current["price_usd"] is None or row["price"] > current["price_usd"]
        ):
            current["price_usd"] = row["price"]
    for current in stock.values():
        if current["price_usd"] is not None:
            current["price_usd"] = f"{current['price_usd']:.2f}"
    return stock


def references(card_ids):
    """(Referencias para validar, cartas cargadas para crear)."""
    cards = bulk_load.load_cards(list(card_ids))
    refs = References(
        cards=frozenset(cards),
        conditions=frozenset(CardCondition.objects.values_list("id", flat=True)),
        finishes={cid: tuple(card.printings or ()) for cid, card in cards.items()},
        set_languages={cid: card.card_set.language for cid, card in cards.items()},
    )
    return refs, cards


def categories():
    """{tipo: ProductCategory} para Singles y Sellados."""
    by_kind = {}
    for category in ProductCategory.objects.all():
        kind = bulk_load.category_kind(category.name)
        if kind in (KIND_SINGLE, KIND_SEALED):
            by_kind.setdefault(kind, category)
    return by_kind


def category_for(kind, by_kind):
    try:
        return by_kind[kind]
    except KeyError:
        label = "Single" if kind == KIND_SINGLE else "Sellado"
        raise MissingCategory(f"Creá la categoría «{label}» antes de usar la carga masiva.") from None


def existing_listings(card_ids, cards, by_kind):
    """
    {Row.identity: Existing} con la publicación a la que se le suma stock: la
    misma carta, categoría, condición, acabado y atributos, sin certificación, con la
    imagen del catálogo (no una foto propia) y con el nombre de catálogo (una con nombre editado es una
    pieza puntual). Agotadas también valen: vuelven a la tienda. Se prefiere la
    que está en stock y, a igualdad, la más nueva.

    Las filas quedan bloqueadas hasta el commit: dos cargas a la vez no se
    pisan la suma.
    """
    kind_by_category = {category.id: kind for kind, category in by_kind.items()}
    rows = (
        Product.objects.select_for_update()
        .filter(
            catalog_card_id__in=card_ids,
            category_id__in=list(kind_by_category),
            certification_entity__isnull=True,
            certification_grade__isnull=True,
        )
        .order_by("-in_stock", "-id")
        .values(
            "id", "catalog_card_id", "category_id", "condition_id", "name",
            "image_url", "stock_quantity", "in_stock", "finish", "language", *ATTRIBUTES,
        )
    )
    found = {}
    for p in rows:
        kind = kind_by_category[p["category_id"]]
        card = cards.get(p["catalog_card_id"])
        if card is None:
            continue
        attributes = tuple((name, bool(p[name]) and kind == KIND_SINGLE) for name in ATTRIBUTES)
        # El nombre tiene que ser el de catálogo para ese acabado y esos
        # atributos: uno con nombre editado es una pieza puntual.
        if p["name"] != bulk_load._resolve_name(card, "", p["finish"], dict(attributes)):
            continue
        image_url, stock, in_stock = p["image_url"], p["stock_quantity"], p["in_stock"]
        product_id, card_id = p["id"], p["catalog_card_id"]
        # Un producto viejo sin idioma es el de su set.
        language = p["language"] or card.card_set.language
        if kind == KIND_SEALED:
            condition_id, finish = None, ""
        else:
            # Un producto viejo sin acabado es el de por defecto de la carta.
            condition_id = p["condition_id"]
            finish = p["finish"] or finishes.default(card.printings or [])
        # Con una foto que no es la del catálogo, es una copia puntual.
        if image_url and image_url != card.image_url:
            continue
        if stock is None:
            # Criterio viejo: un single sin cantidad era exactamente una unidad.
            stock = 1 if in_stock else 0
        found.setdefault((card_id, kind, language, condition_id, finish, attributes), Existing(product_id, stock))
    return found


# ------------------------------------------------------------------ recibos
def receipt(request_id):
    return BulkLoadReceipt.objects.filter(request_id=request_id).first()


def open_receipt(request_id, user):
    """
    Inserta el recibo. Si otro request con el mismo id llegó primero, devuelve
    None: en Postgres este INSERT espera a que el otro termine, así que lo que
    se lee después ya es su resultado final.
    """
    try:
        with transaction.atomic():
            return BulkLoadReceipt.objects.create(request_id=request_id, user=user)
    except IntegrityError:
        return None


def close_receipt(entry, result):
    entry.result = result
    entry.save(update_fields=["result"])
    # Barato (índice por fecha) y evita programar una limpieza aparte.
    BulkLoadReceipt.objects.filter(created_at__lt=timezone.now() - RECEIPT_LIFETIME).delete()


# ------------------------------------------------------------------ escritura
def _item_of(row, by_kind):
    """La fila en el formato de `bulk_load.create_products`."""
    return {
        "card_id": row.card_id,
        "category": category_for(row.kind, by_kind),
        "name": row.name,
        "tcg_id": None,
        "price_usd": row.price_usd,
        "quantity": row.quantity,
        "discount_percent": row.discount_percent,
        "condition_id": row.condition_id,
        "is_single": row.kind == KIND_SINGLE,
        "language": row.language,
        "finish": row.finish,
        **row.attributes_dict,
        "description": row.description,
        "image_url": row.image_url,
        "pricecharting_url": row.pricecharting_url,
        "draft_token": row.draft_token,
    }


def create(rows, cards, by_kind):
    """Las publicaciones nuevas, en un bulk_create. Devuelve cuántas creó."""
    if not rows:
        return 0
    items = [_item_of(row, by_kind) for row in rows]
    try:
        created, _ = bulk_load.create_products(items, cards)
    except IntegrityError:
        # Otra carga tomó el mismo slug entre que se calculó y se insertó. El
        # savepoint ya se deshizo: se recalcula una vez y listo.
        created, _ = bulk_load.create_products(items, cards)
    return created


def add(adds):
    """Suma stock y actualiza precio de las publicaciones existentes, en un bulk_update."""
    if not adds:
        return 0
    by_id = {existing.product_id: (row, existing) for row, existing in adds}
    products = list(
        Product.objects.filter(id__in=by_id).only(
            "id", "stock_quantity", "reserved_quantity", "in_stock", "price_usd", "discount_percent",
        )
    )
    now = timezone.now()
    for product in products:
        row, existing = by_id[product.id]
        product.stock_quantity = existing.stock + row.quantity
        product.in_stock = product.stock_quantity - (product.reserved_quantity or 0) > 0
        product.price_usd = row.price_usd
        # El descuento solo se pisa si la fila trae uno.
        if row.discount_percent:
            product.discount_percent = row.discount_percent
        # bulk_update no toca los auto_now: el "actualizado" se pone a mano.
        product.updated_at = now
    Product.objects.bulk_update(
        products, ["stock_quantity", "in_stock", "price_usd", "discount_percent", "updated_at"]
    )
    return len(products)


def queue_images(card_ids, cards):
    """Al confirmar: baja a R2 las imágenes de las cartas que todavía no la tienen."""
    missing = [cid for cid in card_ids if not cards[cid].has_image]
    if missing:
        transaction.on_commit(lambda: bulk_load._queue_image_fetch(missing))
