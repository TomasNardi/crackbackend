"""Tokens firmados para acciones de mensajes de contacto."""

from django.core import signing


_SALT = "core.contact.mark_read"


def make_mark_read_token(contact_message_id: int, recipient_email: str) -> str:
    payload = {
        "id": int(contact_message_id),
        "recipient": str(recipient_email or "").strip().lower(),
    }
    return signing.dumps(payload, salt=_SALT, compress=True)


def read_mark_read_token(token: str) -> tuple[int, str] | None:
    if not token:
        return None

    try:
        payload = signing.loads(token, salt=_SALT)
    except signing.BadSignature:
        return None

    try:
        contact_id = int(payload.get("id"))
        recipient_email = str(payload.get("recipient") or "").strip().lower()
        if not recipient_email:
            return None
        return contact_id, recipient_email
    except (TypeError, ValueError, AttributeError):
        return None
