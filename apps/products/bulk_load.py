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

import hashlib
import json
import logging
from functools import wraps

from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import Case, F, IntegerField, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.text import slugify

from apps.catalog import finishes
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
from .services.cloudinary_service import (
    MAX_PRODUCT_IMAGES,
    CloudinaryValidationError,
    sync_product_gallery,
)

logger = logging.getLogger(__name__)

# Tope de resultados por búsqueda. Con 40 alcanza para elegir sin scrollear
# eternamente, y mantiene la respuesta liviana.
SEARCH_LIMIT = 40

# Cuánto se guarda una búsqueda ya resuelta. El catálogo solo cambia al
# reimportarlo, así que podría ser mucho más largo; cinco minutos alcanza para
# toda una sesión de carga y no obliga a acordarse de vaciar la caché después de
# un import.
SEARCH_CACHE_TTL = 300

# Columnas que necesita la búsqueda: las que van al front (`_card_payload`) más
# las que usa el ordenamiento. Todo lo demás se queda en la base.
SEARCH_FIELDS = (
    "id", "name", "number", "rarity", "image_url_thumb", "image_status", "printings",
    "card_set__id", "card_set__name", "card_set__abbreviation",
    "card_set__language", "card_set__is_supplemental", "card_set__released_at",
)

# Tope de items por lote de la carga individual.
#
# Antes era 10: cada producto se creaba de a uno (~390 ms por INSERT contra la
# base de Oregon) y un lote grande pasaba el timeout de Render. Desde que el lote
# entra con un solo bulk_create (`create_products`) el tiempo casi no depende
# del tamaño; el tope queda para que la pantalla siga siendo manejable. Para
# cargar un set entero está la carga masiva (apps/products/set_load).
MAX_BATCH_SIZE = 50

# Insignia de cada atributo en la tabla de la carga masiva, como en TCG Fans
# (y en Delta): 3 letras de respaldo, el color de la casilla marcada y el ícono.
ATTRIBUTE_BADGES = {
    "altered": ("ALT", "#3730a3", "alterada"),
    "signed": ("FIR", "#57534e", "firmada"),
    "stamped": ("EST", "#dc2626", "estampada"),
    "freshly_opened": ("REC", "#ea580c", "recien_abierta"),
}

# Bandera de cada idioma (static/admin/img/flags). La de portugués es la de
# Brasil, que es de donde salen las cartas en portugués.
FLAGS = {"en": "en", "es": "es", "pt": "br", "ja": "jp", "zh": "cn"}

# Íconos de las insignias de acabado que tienen uno (las demás son una letra).
BADGE_ICONS = {"reverse": "reverse", "1st": "primera"}

# Condición con la que entran las filas nuevas. Se resuelve por `abbreviation`
# porque el nombre visible puede cambiar; si alguien borra esa condición, la
# pantalla simplemente arranca sin default y hay que elegirla a mano.
DEFAULT_CONDITION_ABBR = "MT"

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


# Cartas sueltas: la condición es parte de la identidad del producto y el
# buscador tiene que traer cartas jugables, no sellados.
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


def _card_payload(card):
    """
    Los datos de la carta que van al front. Todo esto es fijo: solo cambia
    cuando se reimporta el catálogo, así que se puede cachear.

    El contador de "ya tenés N" NO va acá a propósito: cambia cada vez que
    guardás un lote y se agrega después, en `_attach_loaded_counts`.
    """
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
        # Normal / Holofoil / Reverse Holofoil...: el primero es el por defecto.
        "printings": card.printings or [],
    }


def _attach_loaded_counts(payloads):
    """
    Agrega a cada fila cuántas unidades de esa carta ya tenés publicadas.

    Suma stock, no publicaciones: desde que las copias van a `stock_quantity`,
    contar filas diría "ya tenés 1" cuando en realidad tenés tres en la vitrina.

    Va en una consulta aparte, sobre los 40 ids que sobrevivieron al límite, en
    vez de anotarse con Sum() en la búsqueda. Anotado obligaba a la base a
    joinear productos y agrupar sobre TODOS los matches —cientos o miles de
    filas— para después tirar casi todo al cortar en 40.
    """
    if not payloads:
        return payloads

    counts = dict(
        Product.objects.filter(
            catalog_card_id__in=[p["id"] for p in payloads], in_stock=True
        )
        .values_list("catalog_card_id")
        # Los productos viejos pueden tener el stock vacío: valen una unidad.
        .annotate(total=Sum(Coalesce("stock_quantity", Value(1))))
    )

    for payload in payloads:
        # Sirve para no repetir sin querer, que es el error más caro cuando
        # cargás rápido.
        payload["loaded"] = counts.get(payload["id"], 0)

    return payloads


def _search_cache_key(*parts):
    raw = "|".join(str(p).lower() for p in parts)
    # v2: desde que la carta trae sus acabados (`printings`).
    return "bulk_load:search:v2:" + hashlib.md5(raw.encode("utf-8")).hexdigest()


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

    # Escribiendo se repiten muchísimo las mismas consultas: borrás una letra y
    # volvés a escribirla, o cargás diez cartas del mismo set una atrás de otra.
    # El catálogo solo cambia cuando se reimporta, así que guardar el resultado
    # unos minutos es gratis y saltea la base entera.
    cache_key = _search_cache_key(query, language, set_id, rarity, kind)
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({"results": _attach_loaded_counts(cached)})

    # Solo las columnas que se muestran o que se usan para ordenar.
    #
    # Sin esto la consulta arrastra `extended_data` —un JSONB con los ataques y
    # el texto de la carta— de cada fila que matchea, para ordenarlas y tirar
    # todas menos 40. Medido contra la base de producción con "charizard":
    # 42 ms trayendo todo, 5.7 ms trayendo lo que hace falta.
    cards = CatalogCard.objects.select_related("card_set").only(*SEARCH_FIELDS)

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

    payloads = [_card_payload(c) for c in cards]
    cache.set(cache_key, payloads, SEARCH_CACHE_TTL)

    return JsonResponse({"results": _attach_loaded_counts(payloads)})


def with_attributes(name, item):
    """Suma al nombre las particularidades que cambian qué es el producto: "(Firmada)"."""
    for field, label, in_name in Product.ATTRIBUTES:
        if in_name and item.get(field):
            name = f"{name} ({label})"
    return name


def _resolve_name(card, label="", finish="", attributes=None):
    """
    Mismo criterio que ProductAdminForm, para que los nombres no se bifurquen.

    `label` pisa el nombre de la carta sin tocar el catálogo. Hace falta porque
    en los sets WOTC (Jungle, Fossil, Team Rocket, Gym, Neo) TCGplayer publica
    una sola foto por carta y es la 1st Edition, así que el catálogo las titula
    "(Unlimited)": quien tiene la 1st necesita corregir ese producto puntual.
    El "— <expansión>" lo sigue poniendo el backend, para que todos los
    productos se titulen igual aunque el nombre venga editado.
    """
    label = (label or "").strip() or card.name
    if card.number and card.number not in label:
        label = f"{label} {card.number}"
    # El acabado solo se nombra cuando distingue una impresión de otra de la
    # misma carta ("Bulbasaur 001/165 (Reverse Holo)"); ver catalog/finishes.py.
    label = finishes.title(label, finish, card.printings or [])
    label = with_attributes(label, attributes or {})
    return f"{label} — {card.card_set.name}"[:255]


def _attach_uploads(product, draft_token, manual_url=""):
    """
    Engancha al producto las fotos que se subieron a Cloudinary para esa fila.

    El uploader ya dejó las `ProductImage` colgadas del draft_token; acá solo se
    las pasa al producto recién creado, en el orden en que quedaron.

    La URL manual de la fila entra a la galería detrás de las fotos. Si no,
    quedaba afuera: el sync reescribe `image_url` con lo que hay en la galería,
    así que cargar una URL y además sacar una foto se comía la URL.
    """
    if not draft_token:
        return

    pending = ProductImage.objects.filter(
        draft_token=draft_token, product__isnull=True
    ).order_by("order_index", "id")
    items = [{"id": image_id} for image_id in pending.values_list("id", flat=True)]
    if not items:
        return

    if manual_url and len(items) < MAX_PRODUCT_IMAGES:
        items.append({"id": None, "secure_url": manual_url, "source": ProductImage.SOURCE_URL})

    try:
        sync_product_gallery(
            product=product, draft_token=draft_token, items=items, admin_context=True
        )
    except CloudinaryValidationError as exc:
        # El producto ya está guardado: perder la foto es malo, perder la carga
        # entera es peor. Se avisa y sigue.
        logger.warning("No se pudieron enganchar las fotos de %s: %s", product.pk, exc)
        raise


def resolve_language(requested, card):
    """
    El idioma con el que se publica.

    Una carta de un set japonés es japonesa: su imagen y su set ya lo son, así
    que no se elige. En el resto se respeta el elegido (inglés, español,
    portugués o chino) y, sin elegir, el del set. Sin carta, el elegido o nada.
    """
    set_language = card.card_set.language if card else ""
    if set_language == Product.LANGUAGE_JA:
        return Product.LANGUAGE_JA
    if requested in Product.SELECTABLE_LANGUAGES:
        return requested
    return set_language


def assign_slugs(products):
    """
    El mismo slug que arma `Product.save()` ("nombre", "nombre-1"...), pero para
    todo el lote con UNA consulta en vez de una (o varias) por producto.
    """
    max_length = Product._meta.get_field("slug").max_length
    bases = []
    for product in products:
        base = slugify(product.name)[:max_length].strip("-") or "item"
        bases.append((product, base))

    query = Q()
    for base in {base for _, base in bases}:
        query |= Q(slug__startswith=base)
    taken = set(Product.objects.filter(query).values_list("slug", flat=True))

    for product, base in bases:
        slug, counter = base, 1
        while slug in taken:
            suffix = f"-{counter}"
            slug = f"{base[:max_length - len(suffix)].rstrip('-')}{suffix}"
            counter += 1
        taken.add(slug)
        product.slug = slug


def load_cards(card_ids):
    """Las cartas del lote con solo lo que hace falta para crear el producto."""
    return {
        c.id: c
        for c in CatalogCard.objects.select_related("card_set")
        .only(
            "id", "name", "number", "image_url", "image_status", "printings",
            "card_set__id", "card_set__name", "card_set__tcg_id", "card_set__language",
        )
        .filter(id__in=card_ids)
    }


@transaction.atomic
def create_products(items, cards):
    """
    Crea los productos del lote con UN bulk_create. Devuelve (creados, unidades).

    Antes cada producto era un `Product.objects.create()`: `save()` arma el slug
    (una consulta o más), completa la imagen del catálogo y recién ahí inserta,
    y cada viaje a la base de Oregon cuesta ~390 ms. Un lote de 10 tardaba 4 s y
    uno grande pasaba el timeout de Render. Acá todo lo que hacía `save()` se
    resuelve en memoria y se inserta junto: el lote entero es un puñado de
    consultas, tenga 5 filas o 500.

    Cada item trae su propia categoría: en un mismo lote podés mezclar singles,
    un slab certificado y un sellado suelto.

    La cantidad siempre va a `stock_quantity`: tres copias de la misma carta en
    el mismo estado son una publicación con stock 3, no tres publicaciones.
    """
    entities = {e.id: e for e in CertificationEntity.objects.all()}
    grades = {g.id: g for g in CertificationGrade.objects.all()}
    conditions = {c.id: c for c in CardCondition.objects.all()}

    products = []
    units = 0
    for item in items:
        card = cards.get(item["card_id"]) if item["card_id"] else None
        quantity = item["quantity"]
        # El acabado es de las cartas sueltas: sin elegir, el por defecto de la carta.
        finish = item.get("finish", "")
        if card and item.get("is_single") and not finish:
            finish = finishes.default(card.printings or [])
        attributes = {field: bool(item.get(field)) for field, _, _ in Product.ATTRIBUTES}
        product = Product(
            catalog_card=card,
            category=item["category"],
            # Sin carta (sellado suelto, accesorio) el TCG y el nombre los ponés vos.
            tcg_id=card.card_set.tcg_id if card else item["tcg_id"],
            name=(
                _resolve_name(card, item["name"], finish, attributes)
                if card else with_attributes(item["name"], attributes)[:255]
            ),
            finish=finish,
            **attributes,
            language=resolve_language(item.get("language"), card),
            price_usd=item["price_usd"],
            discount_percent=item["discount_percent"],
            condition=conditions.get(item["condition_id"]),
            certification_entity=entities.get(item.get("certification_entity_id")),
            certification_grade=grades.get(item.get("certification_grade_id")),
            description=item.get("description", ""),
            pricecharting_url=item["pricecharting_url"],
            # Vacío deja que `apply_catalog_image_fallback` use la del catálogo.
            image_url=item["image_url"],
            in_stock=True,
            stock_quantity=quantity,
        )
        # Lo mismo que hace `save()` antes de insertar.
        product.normalize_stock()
        product.apply_catalog_image_fallback()
        products.append(product)
        units += quantity

    assign_slugs(products)
    Product.objects.bulk_create(products)

    # Las fotos subidas son la excepción (casi nunca hay): esas sí van de a una
    # porque cada producto tiene su galería.
    for product, item in zip(products, items):
        _attach_uploads(product, item["draft_token"], item["image_url"])

    return len(products), units


def _create_batch(items):
    """Crea el lote. Si otro lote tomó el mismo slug en el medio, reintenta una vez."""
    cards = load_cards([item["card_id"] for item in items if item["card_id"]])
    missing = [item["card_id"] for item in items if item["card_id"] and item["card_id"] not in cards]
    if missing:
        raise DjangoValidationError(f"La carta {missing[0]} ya no existe en el catálogo.")
    try:
        return create_products(items, cards)
    except IntegrityError:
        # La transacción ya se deshizo: se recalculan los slugs y listo.
        return create_products(items, cards)


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

        # El acabado es de las cartas sueltas y tiene que existir de esa carta
        # (o ser Reverse / 1st, que se pueden marcar siempre: finishes.OPTIONAL).
        finish = (raw.get("finish") or "").strip() if kind in UNIQUE_KINDS and card_id else ""
        if finish:
            card_printings = (
                CatalogCard.objects.filter(pk=card_id).values_list("printings", flat=True).first() or []
            )
            if not finishes.is_allowed(finish, card_printings):
                return fail("ese detalle no existe para esta carta.")

        language = (raw.get("language") or "").strip()
        if language and language not in Product.SELECTABLE_LANGUAGES:
            return fail("idioma inválido.")

        # Sí/no de verdad: "false" como texto no es False.
        attributes = {}
        for field, label, _ in Product.ATTRIBUTES:
            value = raw.get(field, False)
            if not isinstance(value, bool):
                return fail(f"«{label}» tiene que ser sí o no.")
            # Un sellado no se firma ni se altera.
            attributes[field] = value and kind != "sealed"

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
            "is_single": kind in UNIQUE_KINDS,
            "finish": finish,
            "language": language,
            **attributes,
        })

    try:
        created, units = _create_batch(items)
    except (CloudinaryValidationError, DjangoValidationError) as exc:
        # `_create_batch` es atómica: si algo se cae, no queda medio lote cargado.
        return JsonResponse({"error": f"No se guardó nada. {exc}"}, status=400)

    # Las imágenes que falten se bajan en el worker: cargar stock no tiene por
    # qué esperar a que R2 responda 300 veces.
    _queue_image_fetch([item["card_id"] for item in items])

    return JsonResponse({
        "created": created,
        "units": units,
        "errors": [],
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


# Los datos fijos de la pantalla (expansiones y rarezas) solo cambian al
# reimportar el catálogo. Se guardan armados para que abrir la pantalla no
# recorra el catálogo entero buscando las rarezas distintas en cada carga.
PAGE_DATA_CACHE_KEY = "bulk_load:page_data:v1"
PAGE_DATA_CACHE_TTL = 600


def _catalog_page_data():
    """Expansiones y rarezas del catálogo, armadas una vez cada 10 minutos."""
    from apps.catalog.models import CardSet

    try:
        cached = cache.get(PAGE_DATA_CACHE_KEY)
    except Exception:  # noqa: BLE001 — sin Redis, se arma igual
        cached = None
    if cached is not None:
        return cached

    data = {
        # Ordenados por fecha: lo que estás cargando casi siempre es lo último
        # que salió.
        "card_sets": list(
            CardSet.objects.order_by(F("released_at").desc(nulls_last=True), "name")
            .values("id", "name", "language", "abbreviation")
        ),
        "rarities": list(
            CatalogCard.objects.exclude(rarity="")
            .order_by("rarity")
            .values_list("rarity", flat=True)
            .distinct()
        ),
    }
    if data["card_sets"]:
        try:
            cache.set(PAGE_DATA_CACHE_KEY, data, PAGE_DATA_CACHE_TTL)
        except Exception:  # noqa: BLE001
            pass
    return data


def page_view(model_admin, request):
    """GET carga-stock/ — la pantalla."""
    from apps.core.models import ExchangeRate

    from .set_load.domain import MAX_ROWS, MAX_UNITS

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

    catalog = _catalog_page_data()
    conditions = list(CardCondition.objects.all())

    context = {
        "card_sets": catalog["card_sets"],
        "rarities": catalog["rarities"],
        **model_admin.admin_site.each_context(request),
        "title": "Carga de stock",
        "conditions": conditions,
        # Para la carga masiva: la abreviatura va en la columna "en stock".
        "conditions_json": [
            {"id": c.id, "label": str(c), "short": c.abbreviation or c.name[:3].upper()}
            for c in conditions
        ],
        "default_condition_id": (
            CardCondition.objects.filter(abbreviation=DEFAULT_CONDITION_ABBR)
            .values_list("id", flat=True)
            .first() or ""
        ),
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
        "max_images": MAX_PRODUCT_IMAGES,
        # Carga masiva por expansión (apps/products/set_load). La URL lleva un 0
        # que el JS reemplaza por el id del set.
        "set_load_url": reverse("admin:products_product_set_load", args=[0]),
        "set_load_save_url": reverse("admin:products_product_set_load_save"),
        "set_load_max_rows": MAX_ROWS,
        "set_load_max_units": MAX_UNITS,
        # Cómo se lee cada acabado de TCGplayer ("Reverse Holofoil" → "Reverse Holo").
        "finish_labels": {f: finishes.label(f) for f in finishes.ORDER},
        # Insignias de acabado: R y 1st con su ícono (admin/img/insignias/).
        "finish_badges": [
            {**b, "icon": static(f"admin/img/insignias/{BADGE_ICONS[b['key']]}.svg")}
            if b["key"] in BADGE_ICONS else b
            for b in finishes.BADGES
        ],
        # Idiomas que se eligen por fila (japonés no: sale del set japonés).
        "languages": [
            {"id": code, "label": label, "flag": static(f"admin/img/flags/flag-{FLAGS[code]}.svg")}
            for code, label in Product.LANGUAGE_CHOICES
            if code in Product.SELECTABLE_LANGUAGES
        ],
        # Bandera de todos los idiomas, japonés incluido (para mostrarlo fijo).
        "language_flags": {
            code: {"label": label, "flag": static(f"admin/img/flags/flag-{FLAGS[code]}.svg")}
            for code, label in Product.LANGUAGE_CHOICES
        },
        # Atributos de la unidad, con la insignia que los marca en la tabla.
        "attributes": [
            {"field": field, "label": label, "short": ATTRIBUTE_BADGES[field][0],
             "color": ATTRIBUTE_BADGES[field][1],
             "icon": static(f"admin/img/insignias/{ATTRIBUTE_BADGES[field][2]}.svg")}
            for field, label, _ in Product.ATTRIBUTES
        ],
    }

    if not categories:
        messages.warning(
            request,
            "No hay categorías cargadas. Creá al menos 'Single' antes de usar la carga de stock.",
        )

    return render(request, "admin/products/product/bulk_load.html", context)
