"""
Casos de uso de la carga masiva: orquestan dominio y repositorio.

No saben de HTTP (eso es `views`) ni arman consultas (eso es `repository`):
deciden el orden de las cosas y dónde está el límite de la transacción.
"""

from __future__ import annotations

import uuid

from django.db import transaction

from . import repository as repo
from .domain import BatchInvalid, card_ids_of, fill_default_finishes, make_plan, validate_batch


class SetNotFound(Exception):
    pass


def view_set(set_id):
    """El set entero para la grilla, con el stock que ya hay de cada carta."""
    card_set = repo.card_set(set_id)
    if card_set is None:
        raise SetNotFound
    cards = repo.set_cards(set_id)
    return {
        "set": {
            "id": card_set.id,
            "name": card_set.name,
            "abbreviation": card_set.abbreviation,
            "language": card_set.language,
        },
        "cards": cards,
        "stock": repo.stock_of([c["id"] for c in cards]),
    }


def _request_id(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        raise BatchInvalid("Falta el identificador de la carga (request_id).") from None


def save(request_id, raw_rows, user):
    """
    Guarda el lote entero o nada. Idempotente por `request_id`: el mismo id
    devuelve el resultado de la primera vez, sin volver a cargar.

    Orden: primero se valida (solo lecturas, sin bloquear nada); recién con
    todo bien se abre la transacción, se toma el recibo y se escribe.
    """
    request_id = _request_id(request_id)

    previous = repo.receipt(request_id)
    if previous is not None:
        return {**previous.result, "repeated": True}

    refs, cards = repo.references(card_ids_of(raw_rows or []))
    rows = fill_default_finishes(validate_batch(raw_rows, refs), refs)
    by_kind = repo.categories()
    for kind in {r.kind for r in rows}:
        try:
            repo.category_for(kind, by_kind)
        except repo.MissingCategory as exc:
            raise BatchInvalid(str(exc)) from None
    card_ids = sorted({r.card_id for r in rows})

    with transaction.atomic():
        entry = repo.open_receipt(request_id, user)
        if entry is None:
            # Un doble envío que entró en paralelo y ya terminó.
            return {**repo.receipt(request_id).result, "repeated": True}

        plan = make_plan(rows, repo.existing_listings(card_ids, cards, by_kind))
        created = repo.create(plan.creates, cards, by_kind)
        updated = repo.add(plan.adds)
        result = {
            "created": created,
            "updated": updated,
            "units": plan.units,
            # El "ya tenés" nuevo de cada carta: el front lo pinta sin pedir el set de nuevo.
            "stock": {str(k): v for k, v in repo.stock_of(card_ids).items()},
        }
        repo.close_receipt(entry, result)
        repo.queue_images(card_ids, cards)

    return {**result, "repeated": False}
