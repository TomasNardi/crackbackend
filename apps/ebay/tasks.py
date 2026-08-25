"""
Wrappers para la cola de django_q.

Los emails no deben demorar la respuesta HTTP ni tumbar una acción del admin si
Resend está caído, así que salen todos por `async_task`.
"""

import logging

from apps.ebay import emails

logger = logging.getLogger(__name__)


def send_order_received_task(order_id: int) -> None:
    emails.send_order_received(order_id)


def send_new_order_admin_notification_task(order_id: int) -> None:
    emails.send_new_order_admin_notification(order_id)


def send_order_approved_task(order_id: int) -> None:
    emails.send_order_approved(order_id)


def send_order_rejected_task(order_id: int) -> None:
    emails.send_order_rejected(order_id)


def send_payment_received_task(order_id: int) -> None:
    emails.send_payment_received(order_id)


def send_order_in_argentina_task(order_id: int) -> None:
    emails.send_order_in_argentina(order_id)


def enqueue(task_name: str, order_id: int) -> None:
    """
    Encola una tarea, y si la cola no está disponible la corre en el momento.

    En desarrollo casi nunca hay un cluster de django_q levantado; sin este
    fallback los emails simplemente no saldrían y costaría darse cuenta.
    """
    try:
        from django_q.tasks import async_task

        async_task(f"apps.ebay.tasks.{task_name}", order_id)
    except Exception as exc:
        logger.warning("No se pudo encolar %s (%s). Se ejecuta en línea.", task_name, exc)
        try:
            globals()[task_name](order_id)
        except Exception:
            logger.exception("Falló la ejecución en línea de %s para el pedido %s", task_name, order_id)
