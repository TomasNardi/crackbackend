"""Signal handlers for orders/shipping automation."""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from apps.orders.emails import send_shipment_notification
from apps.orders.models import Order, Shipment


@receiver(pre_save, sender=Shipment)
def shipment_pre_save(sender, instance: Shipment, **kwargs):
    previous = None
    if instance.pk:
        previous = Shipment.objects.filter(pk=instance.pk).first()

    if instance.tracking_code and instance.status != Shipment.STATUS_SHIPPED:
        instance.status = Shipment.STATUS_SHIPPED

    if instance.status == Shipment.STATUS_SHIPPED and not instance.shipped_at:
        instance.shipped_at = timezone.now()

    instance._should_notify_shipping = bool(
        instance.tracking_code
        and instance.status == Shipment.STATUS_SHIPPED
        and (not previous or previous.status != Shipment.STATUS_SHIPPED)
    )


@receiver(post_save, sender=Shipment)
def shipment_post_save(sender, instance: Shipment, **kwargs):
    shipping_status = (
        Order.SHIPPING_STATUS_SHIPPED
        if instance.status == Shipment.STATUS_SHIPPED
        else Order.SHIPPING_STATUS_PENDING
    )

    Order.objects.filter(pk=instance.order_id).update(
        shipping_status=shipping_status,
        has_shipping=True,
        updated_at=timezone.now(),
    )

    if getattr(instance, "_should_notify_shipping", False):
        send_shipment_notification(instance.order_id, instance.tracking_code)
