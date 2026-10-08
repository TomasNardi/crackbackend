"""
Alta del cliente y vínculo con sus órdenes.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.core.models import EmailSubscription
from apps.orders.models import Order

from .models import Customer
from .supabase_auth import Identity, get_verifier

logger = logging.getLogger(__name__)

TOKEN_HEADER = "HTTP_X_CUSTOMER_TOKEN"


def token_from_request(request) -> str:
    """El token del comprador, o "" si no vino. Acepta HttpRequest o Request de DRF."""
    meta = getattr(request, "META", None) or {}
    return str(meta.get(TOKEN_HEADER, "") or "").strip()


def _split_name(full_name: str) -> tuple[str, str]:
    first, _, last = (full_name or "").strip().partition(" ")
    return first[:120], last.strip()[:120]


def get_or_create_customer(identity: Identity) -> Customer:
    first_name, last_name = _split_name(identity.name)
    customer, created = Customer.objects.get_or_create(
        supabase_uid=identity.uid,
        defaults={
            "email": identity.email,
            "email_verified": identity.email_verified,
            "provider": identity.provider,
            "first_name": first_name,
            "last_name": last_name,
            "avatar_url": identity.avatar_url,
        },
    )
    if not created:
        # Solo se escribe si algo cambió en Supabase (cambió el email, verificó
        # la cuenta, vinculó Google). La mayoría de los requests no tocan la base.
        changes = {
            field: value
            for field, value in (
                ("email", identity.email),
                ("email_verified", identity.email_verified or customer.email_verified),
                ("provider", identity.provider),
                ("avatar_url", identity.avatar_url or customer.avatar_url),
            )
            if getattr(customer, field) != value
        }
        if changes:
            Customer.objects.filter(pk=customer.pk).update(**changes)
            for field, value in changes.items():
                setattr(customer, field, value)
    return customer


def claim_guest_orders(customer: Customer) -> int:
    """Pasa a la cuenta las compras de invitado hechas con su email.

    Solo con email verificado: un pedido de invitado tiene la dirección y el
    teléfono de alguien, y no se le pueden mostrar a quien se registró con un
    email que no probó que es suyo.
    """
    if not customer.email_verified:
        return 0
    linked = Order.objects.filter(
        customer__isnull=True, customer_email__iexact=customer.email
    ).update(customer=customer)

    # El perfil se completa con la última compra, sin pisar lo que ya editó.
    if linked and not (customer.phone and customer.first_name):
        last = customer.orders.order_by("-created_at").first()
        if last:
            changes = {}
            if not customer.phone and last.customer_phone:
                changes["phone"] = last.customer_phone[:30]
            if not customer.first_name and last.customer_name:
                changes["first_name"], changes["last_name"] = _split_name(last.customer_name)
            if changes:
                Customer.objects.filter(pk=customer.pk).update(**changes)
                for field, value in changes.items():
                    setattr(customer, field, value)
    return linked


def subscribe_to_newsletter(email: str) -> None:
    """Alta (o reactivación) en la newsletter. Nunca da de baja: no marcar el
    checkbox al entrar no es lo mismo que pedir dejar de recibir mails."""
    subscription, created = EmailSubscription.objects.get_or_create(
        email=email, defaults={"is_active": True}
    )
    if not created and not subscription.is_active:
        EmailSubscription.objects.filter(pk=subscription.pk).update(is_active=True)


def sync_session(identity: Identity, marketing_opt_in: bool = False) -> tuple[Customer, int]:
    """Se llama cada vez que el comprador entra con sesión. Es idempotente.

    `marketing_opt_in`: marcó "Enviarme novedades y ofertas" en el login. Se
    suscribe el email de la sesión —ya verificado—, no uno que venga del form,
    así nadie puede anotar en la newsletter un email ajeno.
    """
    customer = get_or_create_customer(identity)
    Customer.objects.filter(pk=customer.pk).update(last_login_at=timezone.now())
    if marketing_opt_in and identity.email_verified:
        subscribe_to_newsletter(customer.email)
    return customer, claim_guest_orders(customer)


def link_order_to_session(order: Order, request) -> None:
    """El checkout acaba de crear `order`. Si el comprador tenía la sesión
    abierta, la orden queda en su cuenta.

    Nunca levanta excepciones: un token vencido o Supabase caído no puede
    costar una venta. En ese caso queda como compra de invitado y se vincula
    sola la próxima vez que entre (si el email coincide).
    """
    token = token_from_request(request)
    if not token:
        return
    order_id = order.pk

    def _link():
        try:
            customer = get_or_create_customer(get_verifier().verify(token))
            Order.objects.filter(pk=order_id, customer__isnull=True).update(customer=customer)
        except Exception as exc:  # noqa: BLE001 — queda como compra de invitado
            logger.warning("Orden %s no se pudo vincular a la cuenta: %s", order_id, exc)

    # Después del commit: valida contra Supabase (red) y no tiene sentido
    # sostener la transacción del checkout mientras tanto.
    transaction.on_commit(_link)
