import re

from django.db import migrations, models


_ORDER_CODE_RE = re.compile(r"\b([A-Z0-9]{6,8})\b")


def _extract_order_code(subject: str, valid_codes: set[str]) -> str:
    subject_value = (subject or "").upper()
    for candidate in _ORDER_CODE_RE.findall(subject_value):
        if candidate in valid_codes:
            return candidate
    return ""


def backfill_emaildelivery_traceability(apps, schema_editor):
    EmailDelivery = apps.get_model("core", "EmailDelivery")
    Order = apps.get_model("orders", "Order")

    orders = Order.objects.exclude(order_code="").values("id", "order_code")
    orders_by_code = {row["order_code"].upper(): row["id"] for row in orders}
    valid_codes = set(orders_by_code.keys())

    for delivery in EmailDelivery.objects.all().iterator(chunk_size=500):
        changed = False

        if not getattr(delivery, "order_code", ""):
            code = _extract_order_code(getattr(delivery, "subject", ""), valid_codes)
            if code:
                delivery.order_code = code
                changed = True
                if not getattr(delivery, "order_id", None):
                    delivery.order_id = orders_by_code.get(code)

        payload = getattr(delivery, "last_payload", {}) or {}
        if not getattr(delivery, "flow_kind", "") and isinstance(payload, dict):
            data = payload.get("data") or {}
            headers = data.get("headers") if isinstance(data, dict) else {}
            if isinstance(headers, dict):
                entity_ref = ""
                for key, value in headers.items():
                    if str(key).lower() == "x-entity-ref-id":
                        entity_ref = str(value or "")
                        break
                if entity_ref.lower().startswith("campaign-"):
                    delivery.flow_kind = "campaign"
                    changed = True

        if changed:
            delivery.save(update_fields=["order", "order_code", "flow_kind"])


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0010_shippingconfig_shippingorder_order_has_shipping_and_more"),
        ("core", "0013_notificationrecipient"),
    ]

    operations = [
        migrations.AddField(
            model_name="emaildelivery",
            name="flow_kind",
            field=models.CharField(blank=True, db_index=True, default="", max_length=40, verbose_name="Flujo"),
        ),
        migrations.AddField(
            model_name="emaildelivery",
            name="order",
            field=models.ForeignKey(blank=True, null=True, on_delete=models.SET_NULL, related_name="email_deliveries", to="orders.order", verbose_name="Orden"),
        ),
        migrations.AddField(
            model_name="emaildelivery",
            name="order_code",
            field=models.CharField(blank=True, db_index=True, default="", max_length=8, verbose_name="Codigo reserva"),
        ),
        migrations.RunPython(backfill_emaildelivery_traceability, migrations.RunPython.noop),
    ]
