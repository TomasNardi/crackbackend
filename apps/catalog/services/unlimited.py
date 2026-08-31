"""
Marcado "(Unlimited)" de los sets WOTC cuyo escaneo es 1st Edition.
==================================================================
TCGplayer publica un solo producto por carta para esos sets: la 1st Edition y la
Unlimited comparten productId, y la foto que sirve el CDN es la 1st Edition (se
le ve el sello "EDITION 1" bajo la ilustración). Como el stock que se vende es
Unlimited, el nombre lo aclara para que la foto no confunda al comprador.

No hay fuente alternativa: pokemontcg.io y TCGdex sirven exactamente el mismo
escaneo. Por eso el arreglo es el nombre y no la imagen.

Lo usan el comando `mark_unlimited_prints` y el endpoint del mismo nombre.
"""

from django.db import transaction

from apps.catalog.models import CatalogCard

SUFFIX = " (Unlimited)"
BATCH_SIZE = 500

# external_id del "group" de TCGplayer → abreviatura del set.
# Verificado carta por carta: el escaneo del CDN tiene el sello de 1st Edition.
# Base Set (604) y Base Set 2 (605) NO están: sus fotos ya son Unlimited.
AFFECTED_SETS = {
    "JU": 635,    # Jungle
    "FO": 630,    # Fossil
    "TR": 1373,   # Team Rocket
    "G1": 1441,   # Gym Heroes
    "G2": 1440,   # Gym Challenge
    "N1": 1396,   # Neo Genesis
    "N2": 1434,   # Neo Discovery
    "N3": 1389,   # Neo Revelation
    "N4": 1444,   # Neo Destiny
}

# Gym Challenge tiene el mismo problema, pero se marca solo si se pide,
# para no cambiar nombres que nadie revisó todavía.
DEFAULT_SETS = ["JU", "FO", "TR", "G1", "N1", "N2", "N3", "N4"]


class UnknownSetError(ValueError):
    """Se pidió una abreviatura que no está en AFFECTED_SETS."""


def normalize_sets(abbreviations=None):
    """
    Valida y normaliza la lista de abreviaturas. Sin argumento, los de siempre.
    """
    if not abbreviations:
        return list(DEFAULT_SETS)

    normalized = [str(abbr).strip().upper() for abbr in abbreviations]
    unknown = [abbr for abbr in normalized if abbr not in AFFECTED_SETS]
    if unknown:
        raise UnknownSetError(
            f"Sets desconocidos: {', '.join(unknown)}. "
            f"Disponibles: {', '.join(sorted(AFFECTED_SETS))}."
        )
    return normalized


def mark_unlimited(abbreviations=None, revert=False, dry_run=False):
    """
    Agrega (o saca, con `revert`) el sufijo en los singles de los sets pedidos.

    Es idempotente: las cartas que ya están como corresponde no se tocan.
    Devuelve {"total": N, "sets": [{"abbr", "set_name", "changed", "total"}, ...]}.
    """
    results = []
    total = 0

    for abbr in normalize_sets(abbreviations):
        result = _process_set(abbr, revert, dry_run)
        results.append(result)
        total += result["changed"]

    return {"total": total, "sets": results, "dry_run": dry_run, "revert": revert}


def _process_set(abbr, revert, dry_run):
    # Los singles son los que traen número; los sellados vienen sin él y
    # TCGplayer ya los separa con "[1st Edition]" / "[Unlimited Edition]".
    cards = list(
        CatalogCard.objects
        .filter(card_set__external_id=AFFECTED_SETS[abbr])
        .exclude(number="")
        .select_related("card_set")
    )

    pending = []
    for card in cards:
        if revert:
            if not card.name.endswith(SUFFIX):
                continue
            card.name = card.name[: -len(SUFFIX)]
        else:
            if card.name.endswith(SUFFIX):
                continue
            # El sufijo entra en el campo aunque el nombre venga al límite.
            card.name = f"{card.name[:255 - len(SUFFIX)]}{SUFFIX}"
        card.search_text = card.build_search_text()
        pending.append(card)

    if pending and not dry_run:
        with transaction.atomic():
            CatalogCard.objects.bulk_update(
                pending, ["name", "search_text"], batch_size=BATCH_SIZE,
            )

    return {
        "abbr": abbr,
        "set_name": cards[0].card_set.name if cards else "",
        "changed": len(pending),
        "total": len(cards),
    }
