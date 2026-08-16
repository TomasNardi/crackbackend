"""
Carga de stock
==============
Pantalla única para dar de alta muchos singles seguidos sin entrar y salir del
formulario del admin.

El flujo del admin normal (Producto → Agregar → autocomplete → guardar) es un
viaje de ida y vuelta por carta. Acá buscás, apretás Enter, y la carta cae en un
lote; cuando terminaste, guardás todo de una.

Tres endpoints, todos colgados de ProductAdmin.get_urls():
    carga-stock/            → la pantalla
    carga-stock/buscar/     → JSON, busca en el catálogo
    carga-stock/guardar/    → JSON, crea el lote entero en una transacción
"""

import json
import logging
from functools import wraps

from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse

from apps.catalog.models import CatalogCard

from .models import (
    TCG,
    CardCondition,
    CertificationEntity,
    CertificationGrade,
    Product,
    ProductCategory,
    ProductImage,
)
from .services.cloudinary_service import CloudinaryValidationError, attach_images_to_product

logger = logging.getLogger(__name__)

# Tope de resultados por búsqueda. Con 40 alcanza para elegir sin scrollear
# eternamente, y mantiene la respuesta liviana.
SEARCH_LIMIT = 40

# Tope de items por lote. Evita que un POST accidental cree miles de productos.
MAX_BATCH_SIZE = 300

SINGLE_CATEGORIES = {"single", "singles"}
SLAB_CATEGORIES = {"slab", "slabs"}
SEALED_CATEGORIES = {"sellado", "sellados"}


def category_kind(name):
    """
    Qué clase de producto es una categoría. De acá sale todo el comportamiento
    de la pantalla:

      single → carta suelta: pide condición, stock de a 1, busca solo cartas
      slab   → igual que single, pero además pide certificadora y nota
      sealed → tins, boxes y collections: sin condición, busca solo sellados
      other  → accesorios y mystery packs: no filtra el catálogo

    Cómo se separan cartas de sellados en el catálogo: ver `IS_PLAYABLE_CARD`.
    """
    slug = (name or "").strip().lower()
    if slug in SINGLE_CATEGORIES:
        return "single"
    if slug in SLAB_CATEGORIES:
        return "slab"
    if slug in SEALED_CATEGORIES:
        return "sealed"
    return "other"


# El modelo fuerza stock = 1 en estas: cada copia es un producto aparte.
UNIQUE_KINDS = {"single", "slab"}


# Cómo se distingue una carta jugable de un producto sellado.
#
# El criterio obvio —"una carta tiene número, un tin no"— no sirve: hay ~700
# cartas japonesas sueltas sin número ni rareza, y quedaban mezcladas con los
# tins al cargar sellados.
#
# Lo que sí las separa es `extended_data`, que TCGplayer llena distinto según el
# producto: una carta trae HP, Stage, Attack 1, CardType; un sellado trae a lo
# sumo Description o CardText. Alcanza con mirar CardType, que está en todas las
# cartas (Pokémon, Trainer y Energy) y en ningún sellado. Viene en dos grafías
# según la categoría, así que hay que chequear las dos.
IS_PLAYABLE_CARD = Q(extended_data__has_key="CardType") | Q(extended_data__has_key="Card Type")


def requires_add_permission(view):
    """`admin_view` ya exige staff; esto además exige poder crear productos."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.has_perm("products.add_product"):
            return JsonResponse({"error": "No tenés permiso para crear productos."}, status=403)
        return view(request, *args, **kwargs)

    return wrapper


def _card_payload(card, product_count=0):
    return {
        "id": card.id,
        "name": card.name,
        "number": card.number,
        "rarity": card.rarity,
        "set_name": card.card_set.name,
        "set_abbr": card.card_set.abbreviation,
        "language": card.card_set.language,
        # Solo la miniatura: caer al `image_url` grande hacía que una búsqueda
        # de 40 filas bajara 40 imágenes de tamaño completo.
        "thumb": card.image_url_thumb,
        # Cuántos productos ya cargaste de esta carta. Sirve para no repetir sin
        # querer, que es el error más caro cuando cargás rápido.
        "loaded": product_count,
    }


@requires_add_permission
def search_view(request):
    """
    GET carga-stock/buscar/?q=charizard&lang=en&set=12&rarity=Rare

    Todos los filtros son opcionales y se combinan. Con un filtro de idioma, set
    o rareza puesto, `q` deja de ser obligatorio: sirve para recorrer una
    expansión —o el catálogo japonés entero— de arriba a abajo.

    No hay filtro de "solo con imagen" ni de "ocultar promos": si cargás stock de
    algo, tenés que poder encontrarlo aunque no tenga foto o sea una promo. Lo
    que resuelve el ruido es el orden, no esconder filas.
    """
    query = (request.GET.get("q") or "").strip()
    language = (request.GET.get("lang") or "").strip()
    set_id = (request.GET.get("set") or "").strip()
    rarity = (request.GET.get("rarity") or "").strip()
    kind = (request.GET.get("kind") or "").strip()

    has_filter = bool(language or set_id or rarity)

    # Sin texto y sin ningún filtro no hay nada que mostrar: devolver el
    # catálogo entero no le sirve a nadie.
    if len(query) < 2 and not has_filter:
        return JsonResponse({"results": []})

    cards = CatalogCard.objects.select_related("card_set")

    # Cada palabra tiene que aparecer: "charizard base" no trae todos los
    # Charizard. search_text ya trae nombre + número + set + abreviatura.
    for token in query.split():
        cards = cards.filter(search_text__icontains=token)

    if language:
        cards = cards.filter(card_set__language=language)
    if set_id.isdigit():
        cards = cards.filter(card_set_id=int(set_id))
    if rarity:
        cards = cards.filter(rarity=rarity)

    # Cargando singles no querés ver tins ni collections, y al revés tampoco.
    if kind in UNIQUE_KINDS:
        cards = cards.filter(IS_PLAYABLE_CARD)
    elif kind == "sealed":
        cards = cards.exclude(IS_PLAYABLE_CARD)

    # Ranking: lo que buscás casi siempre es la carta real, no un "Code Card" de
    # un set promocional. Sin esto, buscar "charizard" devuelve primero la
    # morralla de Miscellaneous porque no tiene fecha de salida.
    cards = cards.annotate(
        product_count=Count("products"),
        name_hit=Case(
            When(name__icontains=query, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        no_image=Case(
            When(image_status=CatalogCard.IMAGE_READY, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        ),
        # Las "Code Card" son códigos de canje, nunca las vas a vender. Antes se
        # escondían con un checkbox; ahora se mandan al fondo, que es mejor:
        # siguen estando si alguna vez las necesitás, pero no estorban.
        is_junk=Case(
            When(rarity="Code Card", then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ),
    ).order_by(
        "is_junk",
        "name_hit",
        "card_set__is_supplemental",
        "no_image",
        F("card_set__released_at").desc(nulls_last=True),
        "number",
    )[:SEARCH_LIMIT]

    return JsonResponse({
        "results": [_card_payload(c, c.product_count) for c in cards],
    })


def _resolve_name(card):
    """Mismo criterio que ProductAdminForm, para que los nombres no se bifurquen."""
    label = card.name
    if card.number and card.number not in label:
        label = f"{label} {card.number}"
    return f"{label} — {card.card_set.name}"[:255]


def _attach_uploads(product, draft_token):
    """
    EnganCha al producto las fotos que se subieron a Cloudinary para esa fila.

    El uploader ya dejó las `ProductImage` colgadas del draft_token; acá solo se
    las pasa al producto recién creado, en el orden en que quedaron.
    """
    if not draft_token:
        return

    pending = ProductImage.objects.filter(
        draft_token=draft_token, product__isnull=True
    ).order_by("order_index", "id")
    image_ids = list(pending.values_list("id", flat=True))
    if not image_ids:
        return

    try:
        attach_images_to_product(
            product=product, draft_token=draft_token, ordered_image_ids=image_ids
        )
    except CloudinaryValidationError as exc:
        # El producto ya está guardado: perder la foto es malo, perder la carga
        # entera es peor. Se avisa y sigue.
        logger.warning("No se pudieron enganchar las fotos de %s: %s", product.pk, exc)
        raise


@transaction.atomic
def _create_batch(items, condition_by_id):
    """
    Crea los productos del lote. Devuelve (creados, errores).

    Cada item trae su propia categoría: en un mismo lote podés mezclar singles,
    un slab certificado y un sellado suelto sin volver a la pantalla.

    Ojo con la cantidad: para Singles y Slabs el modelo fuerza stock = 1
    (`Product.normalize_stock`), así que cargar 3 copias significa 3 productos
    distintos. Para el resto de las categorías la cantidad va a stock_quantity.
    """
    card_ids = [item["card_id"] for item in items if item["card_id"]]
    cards = {
        c.id: c
        for c in CatalogCard.objects.select_related("card_set", "card_set__tcg").filter(
            id__in=card_ids
        )
    }
    entities = {e.id: e for e in CertificationEntity.objects.all()}
    grades = {g.id: g for g in CertificationGrade.objects.all()}
    tcgs = {t.id: t for t in TCG.objects.all()}

    created = 0
    errors = []

    for item in items:
        card = None
        if item["card_id"]:
            card = cards.get(item["card_id"])
            if card is None:
                errors.append(f"La carta {item['card_id']} ya no existe en el catálogo.")
                continue

        category = item["category"]
        is_unique = category_kind(category.name) in UNIQUE_KINDS
        quantity = item["quantity"]
        base = {
            "catalog_card": card,
            "category": category,
            # Sin carta (sellado suelto, accesorio) el TCG y el nombre los ponés vos.
            "tcg": card.card_set.tcg if card else tcgs.get(item["tcg_id"]),
            "name": _resolve_name(card) if card else item["name"],
            "price_usd": item["price_usd"],
            "discount_percent": item["discount_percent"],
            "condition": condition_by_id.get(item["condition_id"]),
            "certification_entity": entities.get(item["certification_entity_id"]),
            "certification_grade": grades.get(item["certification_grade_id"]),
            "description": item["description"],
            "pricecharting_url": item["pricecharting_url"],
            # Vacío deja que `apply_catalog_image_fallback` use la del catálogo.
            "image_url": item["image_url"],
            "in_stock": True,
        }

        # `save()` arma el slug y baja la imagen del catálogo, así que no se
        # puede usar bulk_create acá.
        copies = quantity if is_unique else 1
        for copy_index in range(copies):
            product = Product.objects.create(
                **base, **({} if is_unique else {"stock_quantity": quantity})
            )
            # Las fotos propias van solo a la primera copia: son de esa unidad,
            # no del modelo de carta, y una ProductImage es de un producto solo.
            if copy_index == 0:
                _attach_uploads(product, item["draft_token"])
            created += 1

    return created, errors


def _queue_image_fetch(card_ids):
    """Encola la bajada de imágenes. Si el worker no está, no rompe la carga."""
    try:
        from django_q.tasks import async_task

        async_task("apps.products.tasks.fetch_images_for_cards", list(set(card_ids)))
    except Exception as exc:  # noqa: BLE001 — el stock ya se guardó, esto es extra
        logger.warning("No se pudo encolar la bajada de imágenes del lote: %s", exc)


@requires_add_permission
def save_view(request):
    """POST carga-stock/guardar/ con {"category_id": 1, "items": [...]}"""
    if request.method != "POST":
        return JsonResponse({"error": "Método no permitido."}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "No se pudo leer el lote."}, status=400)

    raw_items = data.get("items") or []
    if not raw_items:
        return JsonResponse({"error": "El lote está vacío."}, status=400)

    if len(raw_items) > MAX_BATCH_SIZE:
        return JsonResponse(
            {"error": f"Máximo {MAX_BATCH_SIZE} items por lote."}, status=400
        )

    categories_by_id = {c.id: c for c in ProductCategory.objects.all()}
    # La categoría de arriba es solo el valor por defecto: manda la de cada fila.
    default_category = categories_by_id.get(data.get("category_id"))

    condition_by_id = {c.id: c for c in CardCondition.objects.all()}
    entity_ids = set(CertificationEntity.objects.values_list("id", flat=True))
    grade_ids = set(CertificationGrade.objects.values_list("id", flat=True))
    tcg_ids = set(TCG.objects.values_list("id", flat=True))

    def optional_id(value, valid_ids, label):
        """Devuelve (id, error). Vacío es válido; un id que no existe, no."""
        if value in (None, "", 0):
            return None, None
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None, f"{label} inválida."
        if value not in valid_ids:
            return None, f"esa {label} no existe."
        return value, None

    items = []
    for index, raw in enumerate(raw_items, start=1):
        def fail(message):
            return JsonResponse({"error": f"Fila {index}: {message}"}, status=400)

        category = categories_by_id.get(raw.get("category_id")) or default_category
        if category is None:
            return fail("elegí una categoría válida.")

        kind = category_kind(category.name)
        # En Singles y Slabs la condición es parte de la identidad del producto:
        # sin ella el cliente no sabe qué compra y el precio no se justifica.
        condition_required = kind in UNIQUE_KINDS
        # Un slab sin certificadora ni nota es solo una carta en una caja: el
        # precio de un slab lo hace justamente la nota.
        certification_required = kind == "slab"

        try:
            price = float(raw["price_usd"])
            quantity = int(raw.get("quantity") or 1)
            discount = int(raw.get("discount_percent") or 0)
            card_id = int(raw["card_id"]) if raw.get("card_id") else None
        except (KeyError, TypeError, ValueError):
            return fail("datos incompletos.")

        if price <= 0:
            return fail("el precio tiene que ser mayor a 0.")
        if not 1 <= quantity <= 99:
            return fail("cantidad fuera de rango (1-99).")
        if not 0 <= discount <= 100:
            return fail("descuento fuera de rango (0-100).")

        # Producto sin carta del catálogo: el nombre y el TCG dejan de salir
        # solos, así que se vuelven obligatorios.
        name = (raw.get("name") or "").strip()[:255]
        tcg_id, err = optional_id(raw.get("tcg_id"), tcg_ids, "TCG")
        if err:
            return fail(err)

        # Se permite en cualquier categoría, incluidos Slabs: una carta graded
        # rara puede no estar en el catálogo y hay que poder publicarla igual.
        if card_id is None:
            if not name:
                return fail("sin carta del catálogo tenés que poner un nombre.")
            if tcg_id is None:
                return fail("sin carta del catálogo tenés que elegir el TCG.")

        condition_id, err = optional_id(raw.get("condition_id"), set(condition_by_id), "condición")
        if err:
            return fail(err)
        if condition_required and condition_id is None:
            return fail(f"elegí la condición ({category.name} no se puede publicar sin estado).")

        entity_id, err = optional_id(raw.get("certification_entity_id"), entity_ids, "certificadora")
        if err:
            return fail(err)
        grade_id, err = optional_id(raw.get("certification_grade_id"), grade_ids, "nota")
        if err:
            return fail(err)

        if certification_required and (entity_id is None or grade_id is None):
            return fail("un slab necesita certificadora y nota.")
        if not certification_required and (entity_id or grade_id):
            return fail(f"la certificación es solo para Slabs, no para {category.name}.")

        image_url = (raw.get("image_url") or "").strip()
        pricecharting_url = (raw.get("pricecharting_url") or "").strip()
        for label, value in (("la URL de imagen", image_url),
                             ("la URL de referencia", pricecharting_url)):
            if value:
                try:
                    URLValidator()(value)
                except DjangoValidationError:
                    return fail(f"{label} no es una URL válida.")
                if len(value) > 600:
                    return fail(f"{label} es demasiado larga (máx. 600).")

        items.append({
            "card_id": card_id,
            "category": category,
            "name": name,
            "tcg_id": tcg_id,
            "price_usd": price,
            "quantity": quantity,
            "discount_percent": discount,
            "condition_id": condition_id,
            "certification_entity_id": entity_id,
            "certification_grade_id": grade_id,
            "image_url": image_url,
            "pricecharting_url": pricecharting_url,
            "description": (raw.get("description") or "").strip(),
            "draft_token": (raw.get("draft_token") or "").strip(),
        })

    try:
        created, errors = _create_batch(items, condition_by_id)
    except (CloudinaryValidationError, DjangoValidationError) as exc:
        # `_create_batch` es atómica: si algo se cae, no queda medio lote cargado.
        return JsonResponse({"error": f"No se guardó nada. {exc}"}, status=400)

    # Las imágenes que falten se bajan en el worker: cargar stock no tiene por
    # qué esperar a que R2 responda 300 veces.
    _queue_image_fetch([item["card_id"] for item in items])

    return JsonResponse({
        "created": created,
        "errors": errors,
        "changelist_url": reverse("admin:products_product_changelist"),
    })


def _cloudinary_ready():
    """Si no está configurado, la pantalla esconde el botón de subir foto."""
    from .services.cloudinary_service import CloudinaryConfigurationError, get_config

    try:
        get_config()
        return True
    except CloudinaryConfigurationError:
        return False


def page_view(model_admin, request):
    """GET carga-stock/ — la pantalla."""
    from apps.core.models import ExchangeRate

    from apps.catalog.models import CardSet

    # La botonera respeta este orden, así que va de lo que más se carga a lo que
    # menos: Singles es el 90% del trabajo y tiene que ser el primer botón.
    kind_order = {"single": 0, "slab": 1, "sealed": 2, "other": 3}
    categories = sorted(
        (
            {"id": c.id, "name": c.name, "kind": category_kind(c.name)}
            for c in ProductCategory.objects.all()
        ),
        key=lambda c: (kind_order[c["kind"]], c["name"]),
    )
    default_category = next(
        (c for c in categories if c["kind"] == "single"),
        categories[0] if categories else None,
    )

    # Los sets van al desplegable ordenados por fecha: lo que estás cargando
    # casi siempre es lo último que salió.
    card_sets = CardSet.objects.order_by(
        F("released_at").desc(nulls_last=True), "name"
    ).values("id", "name", "language", "abbreviation")

    rarities = (
        CatalogCard.objects.exclude(rarity="")
        .order_by("rarity")
        .values_list("rarity", flat=True)
        .distinct()
    )

    context = {
        "card_sets": list(card_sets),
        "rarities": list(rarities),
        **model_admin.admin_site.each_context(request),
        "title": "Carga de stock",
        "conditions": CardCondition.objects.all(),
        "cert_entities": CertificationEntity.objects.all(),
        "cert_grades": CertificationGrade.objects.all(),
        "tcgs": TCG.objects.all(),
        "categories": categories,
        "default_category": default_category,
        "usd_to_ars": ExchangeRate.get().usd_to_ars,
        "search_url": reverse("admin:products_product_bulk_search"),
        "save_url": reverse("admin:products_product_bulk_save"),
        # La pantalla no es un form del admin, así que no hereda el "volver" de
        # siempre: hay que dárselo a mano o quedás encerrado acá.
        "changelist_url": reverse("admin:products_product_changelist"),
        "max_batch_size": MAX_BATCH_SIZE,
        # Subida directa a Cloudinary, el mismo camino que usa el form clásico.
        "cloudinary_signature_url": reverse("cloudinary_upload_signature"),
        "cloudinary_register_url": reverse("cloudinary_register_upload"),
        "cloudinary_enabled": _cloudinary_ready(),
    }

    if not categories:
        messages.warning(
            request,
            "No hay categorías cargadas. Creá al menos 'Single' antes de usar la carga de stock.",
        )

    return render(request, "admin/products/product/bulk_load.html", context)
