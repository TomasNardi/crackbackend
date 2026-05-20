"""Service layer for orders app.

Avoid eager imports here to prevent circular imports during Django app initialization.
"""


def apply_order_confirmed_side_effects(*args, **kwargs):
    from .order_confirmation_service import apply_order_confirmed_side_effects as _impl
    return _impl(*args, **kwargs)


def send_order_emails(*args, **kwargs):
    from .order_confirmation_service import send_order_emails as _impl
    return _impl(*args, **kwargs)


def extract_payment_id(*args, **kwargs):
    from .mercadopago_reconciliation_service import extract_payment_id as _impl
    return _impl(*args, **kwargs)


def extract_merchant_order_id(*args, **kwargs):
    from .mercadopago_reconciliation_service import extract_merchant_order_id as _impl
    return _impl(*args, **kwargs)


def extract_mp_topic(*args, **kwargs):
    from .mercadopago_reconciliation_service import extract_mp_topic as _impl
    return _impl(*args, **kwargs)


def get_payment_data_for_validation(*args, **kwargs):
    from .mercadopago_reconciliation_service import get_payment_data_for_validation as _impl
    return _impl(*args, **kwargs)


def is_valid_mp_signature(*args, **kwargs):
    from .mercadopago_reconciliation_service import is_valid_mp_signature as _impl
    return _impl(*args, **kwargs)


def reconcile_merchant_order_event(*args, **kwargs):
    from .mercadopago_reconciliation_service import reconcile_merchant_order_event as _impl
    return _impl(*args, **kwargs)


def reconcile_payment(*args, **kwargs):
    from .mercadopago_reconciliation_service import reconcile_payment as _impl
    return _impl(*args, **kwargs)

__all__ = [
    "apply_order_confirmed_side_effects",
    "send_order_emails",
    "extract_payment_id",
    "extract_merchant_order_id",
    "extract_mp_topic",
    "get_payment_data_for_validation",
    "is_valid_mp_signature",
    "reconcile_merchant_order_event",
    "reconcile_payment",
]
