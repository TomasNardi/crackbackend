"""
Reglas de la carga masiva, sin Django.

Todo lo que decide qué se guarda vive acá: cómo se lee una fila, qué la hace
inválida y en qué se traduce (publicaciones nuevas o stock que se suma). No toca
la base ni sabe de HTTP, así que se prueba con datos sueltos.

Cómo se mapea una fila a Product (mismo criterio que el resto de Crack):
    Una publicación por carta + categoría + idioma + condición + acabado + atributos,
    con stock N. Tres Charizard NM son UNA publicación con stock 3, no tres
    avisos repetidos; un Charizard NM Reverse Holo o uno Firmado es otra.

    Si ya existe esa publicación (aunque esté agotada), la fila le SUMA la
    cantidad y le actualiza el precio. Si no existe, se crea.

    La excepción es la fila con algo propio de esa copia —fotos, una URL de
    imagen o un nombre distinto—: eso es una pieza puntual y va en una
    publicación aparte, igual que en el comando de duplicados.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from urllib.parse import urlparse

from apps.catalog import finishes

KIND_SINGLE = "single"
KIND_SEALED = "sealed"
KINDS = (KIND_SINGLE, KIND_SEALED)

# Un set grande de Pokémon ronda las 300 cartas; con copias en otra condición,
# 500 filas cubren cualquiera. Las unidades acotan el peor caso real.
MAX_ROWS = 500
MAX_UNITS = 5000
MAX_QTY_SINGLE = 99
MAX_QTY_SEALED = 999
MAX_PRICE_USD = Decimal("99999999.99")  # lo que entra en la columna (10, 2)
MAX_URL = 600
CENTS = Decimal("0.01")

# Idiomas que se eligen por fila (Product.SELECTABLE_LANGUAGES). Japonés no:
# una carta de un set japonés ya es japonesa, y al revés no se puede elegir.
SELECTABLE_LANGUAGES = ("en", "es", "pt", "zh")
LANGUAGE_JA = "ja"

# Particularidades de la unidad (Product.ATTRIBUTES; un test cuida que sean
# las mismas). Sí/no, las marca quien carga, solo en cartas sueltas.
ATTRIBUTES = ("altered", "signed", "stamped", "freshly_opened")


class BatchInvalid(Exception):
    """El lote no se puede guardar. `errors` va por fila: {key: mensaje}."""

    def __init__(self, message, errors=None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}


@dataclass(frozen=True)
class References:
    """Los ids válidos contra los que se valida un lote (los trae el repositorio)."""

    cards: frozenset
    conditions: frozenset
    # {card_id: (acabados que existen de esa carta)}, el primero es el por defecto.
    finishes: dict = field(default_factory=dict)
    # {card_id: idioma de su set}
    set_languages: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Row:
    """Una fila ya validada: todo lo que hace falta para persistirla."""

    key: str             # cómo la identifica el front para marcar el error
    card_id: int
    kind: str
    quantity: int
    price_usd: Decimal
    condition_id: int | None = None
    language: str = ""
    finish: str = ""         # vacío = el por defecto de la carta (solo singles)
    attributes: tuple = ()   # (("signed", True), ...) ordenado: así la fila es hasheable
    discount_percent: int = 0
    name: str = ""
    description: str = ""
    image_url: str = ""
    pricecharting_url: str = ""
    draft_token: str = ""

    @property
    def identity(self):
        """Qué publicación es: carta + tipo + idioma + condición + acabado + atributos."""
        return (self.card_id, self.kind, self.language, self.condition_id, self.finish, self.attributes)

    @property
    def attributes_dict(self):
        return dict(self.attributes)

    @property
    def is_own_copy(self):
        """Trae algo propio de esa copia física: va en una publicación aparte."""
        return bool(self.draft_token or self.image_url or self.name)


@dataclass(frozen=True)
class Existing:
    """Una publicación que ya está en la base (a la que se le suma)."""

    product_id: int
    stock: int


@dataclass
class Plan:
    """En qué se traduce el lote: publicaciones nuevas y sumas de stock."""

    creates: list = field(default_factory=list)   # [Row]
    adds: list = field(default_factory=list)      # [(Row, Existing)]

    @property
    def units(self):
        return sum(r.quantity for r in self.creates) + sum(r.quantity for r, _ in self.adds)


# ------------------------------------------------------------------ lectura
def _integer(value, *, default=None):
    """Entero estricto: "3" y 3 sí; "3.5", 3.5, True o "3abc" no (int() los truncaría)."""
    if value in (None, ""):
        return default
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise ValueError


def _optional_id(value, valid, label):
    try:
        value = _integer(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} inválida.") from None
    if value is not None and value not in valid:
        raise ValueError(f"esa {label} no existe.")
    return value


def _url(value, label):
    value = value.strip() if isinstance(value, str) else ""
    if not value:
        return ""
    parts = urlparse(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"{label} no es una URL válida.")
    if len(value) > MAX_URL:
        raise ValueError(f"{label} es demasiado larga (máx. {MAX_URL}).")
    return value


def card_ids_of(raw_rows):
    """Los card_id que pide el lote, para traer solo esas referencias."""
    ids = set()
    for raw in raw_rows:
        try:
            ids.add(int(raw.get("card_id")))
        except (AttributeError, TypeError, ValueError):
            continue
    return ids


def read_row(raw, refs: References) -> Row:
    """Una fila del JSON → Row. Levanta ValueError con un mensaje para el usuario."""
    if not isinstance(raw, dict):
        raise ValueError("fila ilegible.")

    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError("tipo de producto inválido.")

    card_id = _optional_id(raw.get("card_id"), refs.cards, "carta")
    if card_id is None:
        raise ValueError("falta la carta del catálogo.")

    try:
        quantity = _integer(raw.get("quantity"), default=0)
    except (TypeError, ValueError):
        raise ValueError("la cantidad tiene que ser un número entero.") from None
    top = MAX_QTY_SINGLE if kind == KIND_SINGLE else MAX_QTY_SEALED
    if not 1 <= quantity <= top:
        raise ValueError(f"cantidad fuera de rango (1-{top}).")

    try:
        price = Decimal(str(raw.get("price_usd"))).quantize(CENTS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("precio inválido.") from None
    if not price.is_finite() or price <= 0:
        raise ValueError("el precio tiene que ser mayor a 0.")
    if price > MAX_PRICE_USD:
        raise ValueError("precio fuera de rango.")

    condition_id = _optional_id(raw.get("condition_id"), refs.conditions, "condición")
    if kind == KIND_SINGLE and condition_id is None:
        raise ValueError("elegí la condición (un single no se publica sin estado).")

    # Una carta de un set japonés es japonesa. En el resto, uno de los
    # elegibles o, sin elegir, el del set.
    set_language = refs.set_languages.get(card_id, "")
    language = raw.get("language") or ""
    if not isinstance(language, str) or (language and language not in SELECTABLE_LANGUAGES):
        raise ValueError("idioma inválido.")
    if set_language == LANGUAGE_JA or not language:
        language = set_language

    # El acabado (Normal, Reverse Holofoil...) es de las cartas sueltas, y
    # tiene que ser uno de los que existen de esa carta (o Reverse / 1st, que
    # se pueden marcar siempre: finishes.OPTIONAL).
    finish = (raw.get("finish") or "") if kind == KIND_SINGLE else ""
    if not isinstance(finish, str):
        raise ValueError("detalle inválido.")
    if finish and not finishes.is_allowed(finish, refs.finishes.get(card_id, ())):
        raise ValueError("ese detalle no existe para esta carta.")

    # Sí/no de verdad: "false" como texto no es False.
    attributes = []
    for name in ATTRIBUTES:
        value = raw.get(name, False)
        if not isinstance(value, bool):
            raise ValueError(f"«{name}» tiene que ser sí o no.")
        attributes.append((name, value and kind == KIND_SINGLE))

    try:
        discount = _integer(raw.get("discount_percent"), default=0)
    except (TypeError, ValueError):
        raise ValueError("el descuento tiene que ser un número entero.") from None
    if not 0 <= discount <= 100:
        raise ValueError("descuento fuera de rango (0-100).")

    name = raw.get("name")
    description = raw.get("description")
    return Row(
        key=str(raw.get("key") or card_id),
        card_id=card_id,
        kind=kind,
        quantity=quantity,
        price_usd=price,
        # La condición es del single: en un sellado no aplica.
        condition_id=condition_id if kind == KIND_SINGLE else None,
        language=language,
        finish=finish,
        attributes=tuple(attributes),
        discount_percent=discount,
        name=name.strip()[:255] if isinstance(name, str) else "",
        description=description.strip() if isinstance(description, str) else "",
        image_url=_url(raw.get("image_url"), "la URL de imagen"),
        pricecharting_url=_url(raw.get("pricecharting_url"), "la URL de PriceCharting"),
        draft_token=str(raw.get("draft_token") or "").strip()[:64],
    )


def validate_batch(raw_rows, refs: References) -> list[Row]:
    """
    Valida el lote entero y junta TODOS los errores antes de fallar: el que
    carga ve de una cuáles filas corregir, en vez de ir de a una.
    """
    if not isinstance(raw_rows, list) or not raw_rows:
        raise BatchInvalid("No hay filas para guardar.")
    if len(raw_rows) > MAX_ROWS:
        raise BatchInvalid(f"Máximo {MAX_ROWS} filas por carga.")

    rows, errors = [], {}
    for index, raw in enumerate(raw_rows, start=1):
        key = str((raw.get("key") if isinstance(raw, dict) else None) or index)
        try:
            rows.append(read_row(raw, refs))
        except ValueError as exc:
            errors[key] = str(exc)

    if errors:
        raise BatchInvalid(f"Hay {len(errors)} fila(s) con errores. No se guardó nada.", errors)

    units = sum(r.quantity for r in rows)
    if units > MAX_UNITS:
        raise BatchInvalid(f"Son {units} unidades: el máximo por carga es {MAX_UNITS}.")
    return rows


# ------------------------------------------------------------------ plan
def fill_default_finishes(rows, refs: References):
    """El single sin acabado toma el por defecto de su carta (el primero de la lista)."""
    def with_default(row):
        printings = refs.finishes.get(row.card_id) or ()
        return replace(row, finish=printings[0]) if printings else row

    return [with_default(r) if r.kind == KIND_SINGLE and not r.finish else r for r in rows]


def make_plan(rows, existing) -> Plan:
    """
    Decide qué se crea y qué se suma.
    `existing`: {Row.identity: Existing}.

    La misma publicación (carta, idioma, condición, acabado y atributos) repetida en
    dos filas es ambigua (¿el precio de cuál?), así que se rechaza en vez de
    adivinar. Con otra condición, acabado o atributo sí vale: es otra. Las copias propias (con foto o nombre) no
    cuentan: cada una es una publicación aparte.
    """
    seen = set()
    plan = Plan()
    for row in rows:
        if row.is_own_copy:
            plan.creates.append(row)
            continue
        if row.identity in seen:
            raise BatchInvalid(
                "Hay una carta repetida en la misma condición y detalle.",
                {row.key: "esta carta ya está en otra fila igual (idioma, condición, detalle y particularidades): sumá las cantidades."},
            )
        seen.add(row.identity)
        match = existing.get(row.identity)
        if match:
            plan.adds.append((row, match))
        else:
            plan.creates.append(row)
    return plan
