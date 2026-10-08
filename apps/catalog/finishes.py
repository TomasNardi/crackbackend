"""
Acabados (variantes de impresión) de una carta
==============================================
TCGplayer no publica la reverse holo, la 1st Edition o la foil como cartas
aparte: son variantes ("subTypeName") del mismo producto, y solo aparecen en el
endpoint de precios de tcgcsv. Cada carta del catálogo guarda la lista de las
que existen (`CatalogCard.printings`) y cada producto de Crack la que es
(`Product.finish`).

Los valores se guardan tal cual los publica TCGplayer ("Reverse Holofoil"): es
la fuente, y así un acabado nuevo que aparezca mañana no rompe nada. Para
mostrar se usa la etiqueta corta.

Valores vistos en la fuente:
    Pokémon moderno   Normal · Holofoil · Reverse Holofoil
    Pokémon WOTC      Unlimited · 1st Edition · (y sus "... Holofoil")
    One Piece         Normal · Foil
    Lorcana           Normal · Holofoil · Cold Foil
"""

# Orden en el que se ofrecen. El primero que tenga la carta es su acabado por
# defecto: la impresión "común" de esa carta (Normal en una common, Holofoil
# en una rare holo, Unlimited en un set WOTC). Lo que no está en la lista va al
# final, en orden alfabético.
ORDER = (
    "Normal",
    "Holofoil",
    "Unlimited",
    "Unlimited Holofoil",
    "1st Edition",
    "1st Edition Holofoil",
    "Reverse Holofoil",
    "Foil",
    "Cold Foil",
)

# Cómo se lee en el título y en la tienda. Lo que no está acá se muestra tal cual.
LABELS = {
    "Normal": "Normal",
    "Holofoil": "Holo",
    "Reverse Holofoil": "Reverse Holo",
    "Unlimited": "Unlimited",
    "Unlimited Holofoil": "Unlimited Holo",
    "1st Edition": "1st Edition",
    "1st Edition Holofoil": "1st Edition Holo",
    "Foil": "Foil",
    "Cold Foil": "Cold Foil",
}

# Insignias de los acabados que NO son el por defecto, para marcarlos con un
# checkbox (como en TCG Fans): una letra de color por acabado. Una insignia
# agrupa variantes equivalentes ("1st Edition" y "1st Edition Holofoil" son las
# dos la primera edición, según la carta sea holo o no). Un acabado que no esté
# acá igual se puede marcar: la pantalla le arma una insignia gris con su inicial.
BADGES = (
    {"key": "reverse", "short": "R", "label": "Reverse Holo", "color": "#7c3aed",
     "printings": ["Reverse Holofoil"]},
    {"key": "1st", "short": "1st", "label": "1st Edition", "color": "#dc2626",
     "printings": ["1st Edition", "1st Edition Holofoil"]},
    {"key": "holo", "short": "H", "label": "Holo", "color": "#ca8a04",
     "printings": ["Holofoil"]},
    {"key": "foil", "short": "F", "label": "Foil", "color": "#0891b2",
     "printings": ["Foil"]},
    {"key": "cold", "short": "C", "label": "Cold Foil", "color": "#2563eb",
     "printings": ["Cold Foil"]},
    {"key": "unlimited", "short": "U", "label": "Unlimited", "color": "#475569",
     "printings": ["Unlimited", "Unlimited Holofoil"]},
)

MAX_LENGTH = 40   # Product.finish

# Acabados que se pueden marcar en cualquier carta aunque el catálogo no los
# liste: TCGplayer a veces no publica la reverse o la 1st Edition de una carta
# (o el set todavía no tiene precios), y la casilla tiene que estar igual.
OPTIONAL = ("Reverse Holofoil", "1st Edition", "1st Edition Holofoil")


def is_allowed(acabado: str, printings) -> bool:
    """Si una carta puede cargarse con ese acabado."""
    return acabado in (printings or ()) or acabado in OPTIONAL

# Lo que agrega `apps.catalog.services.unlimited` a las cartas WOTC cuyo escaneo es
# 1st Edition. Si el producto ES una 1st Edition, ese aclarado sobra.
UNLIMITED_SUFFIX = " (Unlimited)"


def label(acabado: str) -> str:
    return LABELS.get(acabado, acabado)


def sort(acabados) -> list[str]:
    """Sin repetidos ni vacíos, en el orden de ORDER."""
    unicos = {str(a).strip()[:MAX_LENGTH] for a in acabados or () if str(a or "").strip()}
    return sorted(unicos, key=lambda a: (ORDER.index(a) if a in ORDER else len(ORDER), a))


def default(printings) -> str:
    """El acabado con el que entra una carta si no se elige otro."""
    return printings[0] if printings else ""


def title(nombre: str, acabado: str, printings) -> str:
    """
    El nombre de la carta con su acabado, para el título del producto.

    El acabado por defecto no se aclara ("Bulbasaur", no "Bulbasaur (Normal)"):
    solo se nombra el que distingue una impresión de otra de la misma carta
    ("Bulbasaur (Reverse Holo)"). Un acabado optativo que el catálogo no lista
    (ver OPTIONAL) también se nombra.
    """
    if not acabado or acabado == default(printings):
        return nombre
    # El "(Unlimited)" del catálogo WOTC es justamente lo contrario de una 1st
    # Edition: se cambia por el acabado en vez de quedar los dos. Puede no
    # estar al final ("Pikachu (Unlimited) 60/64").
    if UNLIMITED_SUFFIX in nombre:
        if acabado.startswith("Unlimited"):
            return nombre
        nombre = nombre.replace(UNLIMITED_SUFFIX, "", 1)
    return f"{nombre} ({label(acabado)})"
