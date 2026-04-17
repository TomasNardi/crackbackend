"""Utilities para tokens firmados de desuscripción de newsletter."""

from django.conf import settings
from django.core import signing


_SALT = "core.newsletter.unsubscribe"


def make_unsubscribe_token(email: str) -> str:
    signer = signing.TimestampSigner(salt=_SALT)
    return signer.sign(email.strip().lower())


def read_unsubscribe_token(token: str) -> str | None:
    max_age = getattr(settings, "NEWSLETTER_UNSUBSCRIBE_TOKEN_MAX_AGE", 60 * 60 * 24 * 365 * 3)
    signer = signing.TimestampSigner(salt=_SALT)
    try:
        email = signer.unsign(token, max_age=max_age)
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    return str(email).strip().lower() or None
