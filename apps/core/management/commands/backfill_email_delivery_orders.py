import json
import re

from django.core.management.base import BaseCommand

from apps.core.models import EmailDelivery
from apps.orders.models import Order


CODE_RE = re.compile(r"\b([A-Z0-9]{6,8})\b")


def extract_entity_ref(headers) -> str:
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == "x-entity-ref-id":
                return str(value or "").strip()

    if isinstance(headers, list):
        for item in headers:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                if str(item[0] or "").lower() == "x-entity-ref-id":
                    return str(item[1] or "").strip()
            elif isinstance(item, dict):
                key = str(item.get("key") or item.get("name") or "").lower()
                if key == "x-entity-ref-id":
                    return str(item.get("value") or "").strip()

    return ""


def collect_candidates(*values) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        for code in CODE_RE.findall(text.upper()):
            if code not in result:
                result.append(code)
    return result


class Command(BaseCommand):
    help = "Backfill order/order_code on EmailDelivery rows using payload headers, subject and metadata."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum rows to process (0 = all).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show potential updates without writing DB changes.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        limit = int(options["limit"] or 0)

        orders_by_code = {
            (order.order_code or "").upper(): order
            for order in Order.objects.only("id", "order_code")
            if order.order_code
        }

        queryset = EmailDelivery.objects.all().order_by("id")
        if limit > 0:
            queryset = queryset[:limit]

        total = 0
        patched = 0

        for delivery in queryset.iterator(chunk_size=500):
            total += 1
            payload = delivery.last_payload or {}
            data = payload.get("data") if isinstance(payload, dict) else {}
            headers = data.get("headers") if isinstance(data, dict) else {}
            entity_ref = extract_entity_ref(headers)

            candidates = collect_candidates(
                delivery.order_code,
                delivery.subject,
                entity_ref,
                data.get("subject") if isinstance(data, dict) else None,
                data.get("text") if isinstance(data, dict) else None,
                data.get("html") if isinstance(data, dict) else None,
                headers,
                data.get("tags") if isinstance(data, dict) else None,
            )

            resolved_order = None
            resolved_code = ""
            for candidate in candidates:
                order = orders_by_code.get(candidate)
                if order:
                    resolved_order = order
                    resolved_code = order.order_code
                    break

            if not resolved_order:
                continue

            needs_update = (delivery.order_id != resolved_order.id) or (delivery.order_code != resolved_code)
            if not needs_update:
                continue

            patched += 1
            self.stdout.write(
                f"[PATCH] delivery_id={delivery.id} email_id={delivery.email_id[:12]} order={resolved_code}"
            )

            if not dry_run:
                delivery.order = resolved_order
                delivery.order_code = resolved_code
                delivery.save(update_fields=["order", "order_code"])

        summary = (
            f"Done. processed={total} patched={patched} dry_run={dry_run}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
