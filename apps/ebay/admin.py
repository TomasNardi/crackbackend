"""
Admin de importación eBay
==========================
El owner maneja todo el ciclo desde la lista de pedidos: cada estado ofrece
solo la acción que corresponde al paso siguiente, con el mismo patrón de
botones que ya usa OrderAdmin (get_urls + format_html).
"""

import logging
from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from apps.ebay import tasks
from apps.ebay.models import EbayConfig, EbayOrder, EbayOrderItem
from apps.ebay.pdf_generator import generate_ebay_order_pdf

logger = logging.getLogger(__name__)


STATUS_COLORS = {
    EbayOrder.STATUS_PENDING: "#e36209",
    EbayOrder.STATUS_APPROVED: "#2ea44f",
    EbayOrder.STATUS_REJECTED: "#d73a49",
    EbayOrder.STATUS_PAYMENT_RECEIVED: "#0969da",
    EbayOrder.STATUS_IN_ARGENTINA: "#8250df",
    EbayOrder.STATUS_DELIVERED: "#57606a",
    EbayOrder.STATUS_BLOCKED: "#9a6700",
}

# Qué botón ofrece cada estado: (url name, etiqueta, color, confirmación).
NEXT_STEP = {
    EbayOrder.STATUS_APPROVED: (
        "admin:ebay_ebayorder_payment_received", "Registrar pago recibido", "#0969da",
        "¿Estás seguro que deseas confirmar? Se enviará la notificación por correo electrónico al cliente.",
    ),
    EbayOrder.STATUS_PAYMENT_RECEIVED: (
        "admin:ebay_ebayorder_in_argentina", "Marcar llegada a Argentina", "#8250df",
        "¿Estás seguro que deseas confirmar? Se enviará la notificación por correo electrónico al cliente.",
    ),
    EbayOrder.STATUS_IN_ARGENTINA: (
        "admin:ebay_ebayorder_delivered", "Marcar entregada", "#57606a",
        "¿Estás seguro que deseas confirmar?",
    ),
}


class RejectionForm(forms.Form):
    """Motivo opcional del rechazo — se copia tal cual en el email al cliente."""

    rejection_message = forms.CharField(
        label="Mensaje para el cliente",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "style": "width:100%;"}),
        help_text="Opcional. Si lo dejás vacío, el email avisa el rechazo sin dar detalles.",
    )


class ShippingConfirmationForm(forms.Form):
    """
    Costo de envío de eBay de las publicaciones que quedaron sin confirmar.

    Se arma un campo por publicación en vez de uno solo para todo el pedido:
    cada línea viene de un vendedor distinto y cobra su propio envío.
    """

    def __init__(self, items, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = list(items)
        for item in self.items:
            self.fields[f"shipping_{item.pk}"] = forms.DecimalField(
                label=item.title,
                min_value=Decimal("0"),
                max_digits=12,
                decimal_places=2,
                initial=item.ebay_shipping,
                widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            )

    def rows(self):
        """Publicación + su campo, para que el template dibuje la fila entera."""
        for item in self.items:
            yield item, self[f"shipping_{item.pk}"]

    def confirmed_shipping(self):
        return [(item, self.cleaned_data[f"shipping_{item.pk}"]) for item in self.items]


class EbayOrderItemInline(TabularInline):
    model = EbayOrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "preview", "listing", "quantity",
        "price", "commission", "tax", "ebay_shipping_display", "arg_shipping",
        "line_total_display", "price_change_display",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="")
    def preview(self, obj):
        if not obj.image_url:
            return "—"
        return format_html(
            '<img src="{}" style="width:56px;height:56px;object-fit:cover;border-radius:8px;'
            'border:1px solid #E8E4DD;" alt="" />',
            obj.image_url,
        )

    @admin.display(description="Envío eBay")
    def ebay_shipping_display(self, obj):
        """
        El costo de envío, o el aviso de que eBay no lo informó.

        Sin esto un envío desconocido se ve como US$ 0.00 —idéntico a un envío
        gratis— y el pedido se aprueba sin que nadie cargue el costo real.
        """
        if not obj.shipping_to_confirm:
            return format_html("US$ {}", f"{obj.ebay_shipping:,.2f}")
        return format_html(
            '<span style="color:#d73a49;font-weight:600;white-space:nowrap;" '
            'title="eBay no informó el costo de envío de esta publicación">'
            '⚠ A confirmar</span>'
        )

    @admin.display(description="Publicación")
    def listing(self, obj):
        return format_html(
            '<div style="max-width:340px;line-height:1.45;">'
            '<div style="font-weight:600;">{}</div>'
            '<a href="{}" target="_blank" rel="noopener noreferrer" '
            'style="font-size:11px;color:#C8972E;">Ver en eBay ↗</a>'
            '</div>',
            obj.title,
            obj.ebay_url,
        )

    @admin.display(description="Total línea")
    def line_total_display(self, obj):
        return format_html('<strong>${}</strong>', f"{obj.line_total:,.2f}")

    @admin.display(description="Precio")
    def price_change_display(self, obj):
        if not obj.price_changed or obj.original_price is None:
            return format_html('<span style="color:#9ca3af;font-size:11px;">Sin cambios</span>')

        went_up = obj.price > obj.original_price
        return format_html(
            '<span style="color:{};font-size:11px;font-weight:600;" title="Cambió entre la '
            'cotización y la confirmación">{} ${} → ${}</span>',
            "#d73a49" if went_up else "#2ea44f",
            "▲" if went_up else "▼",
            f"{obj.original_price:,.2f}",
            f"{obj.price:,.2f}",
        )


@admin.register(EbayOrder)
class EbayOrderAdmin(ModelAdmin):
    list_display = (
        "order_summary", "customer_summary", "total_display",
        "status_display", "workflow_actions", "pdf_button",
    )
    list_display_links = ("order_summary",)
    list_filter = ("status", "delivery_type", "has_price_changes")
    search_fields = ("order_code", "customer_name", "customer_email", "items__title", "items__ebay_item_id")
    ordering = ("-created_at",)
    list_per_page = 40
    inlines = [EbayOrderItemInline]

    readonly_fields = (
        "order_code", "created_at", "updated_at",
        "commission_percent", "tax_percent",
        "items_total", "commission_total", "tax_total",
        "ebay_shipping_total", "arg_shipping_total", "total",
        "has_price_changes", "block_reason",
        "approved_at", "rejected_at", "payment_received_at", "arrived_at", "delivered_at",
        "timeline_display",
    )

    fieldsets = (
        ("Pedido", {
            "fields": ("order_code", "status", "timeline_display", "created_at", "updated_at"),
        }),
        ("Cliente", {
            "fields": ("customer_name", "customer_email", "customer_phone"),
        }),
        ("Entrega", {
            "description": "El costo del envío nacional no está incluido en el total: se coordina por WhatsApp.",
            "fields": (
                "delivery_type", "shipping_address", "shipping_city",
                "shipping_province", "shipping_zip", "shipping_branch", "customer_notes",
            ),
        }),
        ("Totales (USD)", {
            "fields": (
                ("commission_percent", "tax_percent"),
                "items_total", "commission_total", "tax_total",
                "ebay_shipping_total", "arg_shipping_total", "total",
                "has_price_changes",
            ),
        }),
        ("Seguimiento interno", {
            "fields": ("rejection_message", "block_reason", "admin_notes"),
        }),
    )

    def has_add_permission(self, request):
        # Los pedidos entran por el sitio, no se cargan a mano.
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("items")

    # ─── Columnas ─────────────────────────────────────────────────────────────

    @admin.display(description="Pedido", ordering="created_at")
    def order_summary(self, obj):
        local = timezone.localtime(obj.created_at)
        return format_html(
            '<div style="line-height:1.45;">'
            '<div style="font-weight:700;font-size:13px;letter-spacing:0.03em;">{}</div>'
            '<div style="color:#9ca3af;font-size:11px;margin-top:2px;white-space:nowrap;">{}</div>'
            '<div style="color:#9ca3af;font-size:11px;">{} ítem(s)</div>'
            '</div>',
            obj.order_code,
            local.strftime("%d/%m/%Y · %H:%M"),
            obj.items.count(),
        )

    @admin.display(description="Cliente", ordering="customer_name")
    def customer_summary(self, obj):
        return format_html(
            '<div style="line-height:1.45;max-width:240px;">'
            '<div style="font-weight:600;color:#1a1a1a;white-space:nowrap;overflow:hidden;'
            'text-overflow:ellipsis;">{}</div>'
            '<div style="color:#9ca3af;font-size:11px;margin-top:2px;white-space:nowrap;'
            'overflow:hidden;text-overflow:ellipsis;">{}</div>'
            '<div style="color:#9ca3af;font-size:11px;">{}</div>'
            '</div>',
            obj.customer_name or "—",
            obj.customer_email or "—",
            obj.get_delivery_type_display(),
        )

    @admin.display(description="Total", ordering="total")
    def total_display(self, obj):
        warning = ""
        if obj.has_price_changes:
            warning = format_html(
                '<div style="color:#d73a49;font-size:10px;font-weight:600;margin-top:2px;" '
                'title="Algún ítem cambió de precio entre la cotización y la confirmación">'
                '⚠ Precio modificado</div>'
            )
        return format_html(
            '<div><span style="font-weight:700;font-size:13px;white-space:nowrap;">US$ {}</span>{}</div>',
            f"{obj.total:,.2f}",
            warning,
        )

    @admin.display(description="Estado", ordering="status")
    def status_display(self, obj):
        color = STATUS_COLORS.get(obj.status, "#6b7280")
        badge = format_html(
            '<span style="display:inline-block;padding:3px 10px;border-radius:6px;'
            'font-size:11px;font-weight:600;color:{};background:{}1f;">{}</span>',
            color, color, obj.get_status_display(),
        )
        if obj.status == EbayOrder.STATUS_BLOCKED and obj.block_reason:
            return format_html(
                '<div>{}<div style="color:#9ca3af;font-size:10px;margin-top:4px;max-width:220px;">{}</div></div>',
                badge, obj.block_reason,
            )
        return badge

    @admin.display(description="Acciones")
    def workflow_actions(self, obj):
        """Solo el botón del paso siguiente — el flujo es secuencial."""
        if obj.status == EbayOrder.STATUS_PENDING:
            return format_html(
                '<div style="display:flex;flex-direction:column;gap:5px;">{}{}</div>',
                self._button(
                    reverse("admin:ebay_ebayorder_approve", args=[obj.pk]),
                    "Aprobar pedido", "#2ea44f",
                    # Con envíos por cargar el botón abre un formulario, así que
                    # un confirm() antes solo agrega un click de más.
                    "" if any(i.shipping_to_confirm for i in obj.items.all())
                    else "¿Estás seguro que deseas confirmar? Se enviará la notificación por correo electrónico al cliente.",
                ),
                self._button(
                    reverse("admin:ebay_ebayorder_reject", args=[obj.pk]),
                    "Rechazar", "#d73a49", "",
                ),
            )

        step = NEXT_STEP.get(obj.status)
        if step:
            url_name, label, color, confirm = step
            return self._button(reverse(url_name, args=[obj.pk]), label, color, confirm)

        if obj.status == EbayOrder.STATUS_DELIVERED:
            return format_html('<span style="font-size:11px;color:#9ca3af;">Finalizada</span>')

        if obj.status == EbayOrder.STATUS_REJECTED:
            return format_html('<span style="font-size:11px;color:#9ca3af;">Rechazada</span>')

        return format_html('<span style="font-size:11px;color:#9ca3af;">Sin acciones</span>')

    @staticmethod
    def _button(url, label, color, confirm):
        onclick = format_html('return confirm(&#39;{}&#39;);', confirm) if confirm else ""
        return format_html(
            '<a href="{}" onclick="{}" style="background:{};color:#fff;padding:4px 10px;'
            'border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;'
            'display:inline-block;text-align:center;white-space:nowrap;">{}</a>',
            url, onclick, color, label,
        )

    @admin.display(description="PDF")
    def pdf_button(self, obj):
        return format_html(
            '<a href="{}" style="background:#1A1A1A;color:#fff;padding:4px 10px;border-radius:6px;'
            'font-size:11px;font-weight:600;text-decoration:none;display:inline-block;">⬇ PDF</a>',
            reverse("admin:ebay_ebayorder_pdf", args=[obj.pk]),
        )

    @admin.display(description="Línea de tiempo")
    def timeline_display(self, obj):
        steps = [
            ("Pedido recibido", obj.created_at),
            ("Aprobado", obj.approved_at),
            ("Pago recibido", obj.payment_received_at),
            ("En Argentina", obj.arrived_at),
            ("Entregado", obj.delivered_at),
        ]
        if obj.rejected_at:
            steps = [("Pedido recibido", obj.created_at), ("Rechazado", obj.rejected_at)]

        rows = []
        for label, moment in steps:
            if moment:
                rows.append(format_html(
                    '<li style="color:#1a1a1a;margin-bottom:4px;"><strong>{}</strong> — {}</li>',
                    label, timezone.localtime(moment).strftime("%d/%m/%Y %H:%M"),
                ))
            else:
                rows.append(format_html(
                    '<li style="color:#9ca3af;margin-bottom:4px;">{} — pendiente</li>', label,
                ))
        return format_html('<ul style="margin:0;padding-left:16px;font-size:12px;">{}</ul>',
                           format_html("".join(rows)))

    # ─── URLs de las acciones ─────────────────────────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("<int:order_id>/approve/", self.admin_site.admin_view(self.approve_view),
                 name="ebay_ebayorder_approve"),
            path("<int:order_id>/reject/", self.admin_site.admin_view(self.reject_view),
                 name="ebay_ebayorder_reject"),
            path("<int:order_id>/payment-received/", self.admin_site.admin_view(self.payment_received_view),
                 name="ebay_ebayorder_payment_received"),
            path("<int:order_id>/in-argentina/", self.admin_site.admin_view(self.in_argentina_view),
                 name="ebay_ebayorder_in_argentina"),
            path("<int:order_id>/delivered/", self.admin_site.admin_view(self.delivered_view),
                 name="ebay_ebayorder_delivered"),
            path("<int:order_id>/pdf/", self.admin_site.admin_view(self.pdf_view),
                 name="ebay_ebayorder_pdf"),
        ]
        return custom + urls

    def _get_order(self, request, order_id):
        order = EbayOrder.objects.filter(pk=order_id).first()
        if not order:
            self.message_user(request, "Pedido no encontrado.", level=messages.ERROR)
        return order

    def _back(self, request):
        return HttpResponseRedirect(
            request.META.get("HTTP_REFERER") or reverse("admin:ebay_ebayorder_changelist")
        )

    def _advance(self, request, order_id, *, expected, new_status, task, success, wrong_state):
        """
        Avanza un paso del flujo.

        Verifica el estado previo antes de tocar nada: sin eso, recargar la
        página de un botón reenvía el email al cliente.
        """
        order = self._get_order(request, order_id)
        if not order:
            return HttpResponseRedirect(reverse("admin:ebay_ebayorder_changelist"))

        if order.status != expected:
            self.message_user(request, wrong_state.format(code=order.order_code), level=messages.WARNING)
            return self._back(request)

        order.mark(new_status)
        if task:
            tasks.enqueue(task, order.id)
        self.message_user(request, success.format(code=order.order_code), level=messages.SUCCESS)
        return self._back(request)

    def approve_view(self, request, order_id):
        """
        Aprobación. Si alguna publicación quedó con el envío de eBay sin
        confirmar, primero pide esos valores: el email de aprobación lleva el
        total, y mandarlo con un envío en cero es cobrar de menos.
        """
        order = self._get_order(request, order_id)
        if not order:
            return HttpResponseRedirect(reverse("admin:ebay_ebayorder_changelist"))

        if order.status != EbayOrder.STATUS_PENDING:
            self.message_user(
                request, f"El pedido {order.order_code} ya no está pendiente de aprobación.",
                level=messages.WARNING,
            )
            return self._back(request)

        pending = list(order.items.filter(shipping_to_confirm=True))
        if not pending:
            return self._advance(
                request, order_id,
                expected=EbayOrder.STATUS_PENDING,
                new_status=EbayOrder.STATUS_APPROVED,
                task="send_order_approved_task",
                success="Pedido {code} aprobado. Se le envió el email al cliente.",
                wrong_state="El pedido {code} ya no está pendiente de aprobación.",
            )

        if request.method == "POST":
            form = ShippingConfirmationForm(pending, request.POST)
            if form.is_valid():
                for item, shipping in form.confirmed_shipping():
                    item.ebay_shipping = shipping
                    item.shipping_to_confirm = False
                    item.save(update_fields=["ebay_shipping", "shipping_to_confirm"])

                order.recalculate_totals()
                order.mark(EbayOrder.STATUS_APPROVED)
                tasks.enqueue("send_order_approved_task", order.id)
                self.message_user(
                    request,
                    f"Pedido {order.order_code} aprobado por US$ {order.total:,.2f}. "
                    "Se le envió el email al cliente.",
                    level=messages.SUCCESS,
                )
                return HttpResponseRedirect(reverse("admin:ebay_ebayorder_changelist"))
        else:
            form = ShippingConfirmationForm(pending)

        return render(request, "admin/ebay/approve_shipping_popup.html", {
            **self.admin_site.each_context(request),
            "title": f"Aprobar pedido {order.order_code}",
            "order": order,
            "form": form,
            "opts": self.model._meta,
        })

    def reject_view(self, request, order_id):
        """Rechazo con mensaje opcional — abre un formulario en vez de actuar directo."""
        order = self._get_order(request, order_id)
        if not order:
            return HttpResponseRedirect(reverse("admin:ebay_ebayorder_changelist"))

        if order.status != EbayOrder.STATUS_PENDING:
            self.message_user(
                request, f"El pedido {order.order_code} ya no está pendiente de aprobación.",
                level=messages.WARNING,
            )
            return self._back(request)

        if request.method == "POST":
            form = RejectionForm(request.POST)
            if form.is_valid():
                order.rejection_message = form.cleaned_data["rejection_message"].strip()
                order.save(update_fields=["rejection_message", "updated_at"])
                order.mark(EbayOrder.STATUS_REJECTED)
                tasks.enqueue("send_order_rejected_task", order.id)
                self.message_user(
                    request, f"Pedido {order.order_code} rechazado. Se le envió el email al cliente.",
                    level=messages.SUCCESS,
                )
                return HttpResponseRedirect(reverse("admin:ebay_ebayorder_changelist"))
        else:
            form = RejectionForm()

        return render(request, "admin/ebay/reject_popup.html", {
            **self.admin_site.each_context(request),
            "title": f"Rechazar pedido {order.order_code}",
            "order": order,
            "form": form,
            "opts": self.model._meta,
        })

    def payment_received_view(self, request, order_id):
        return self._advance(
            request, order_id,
            expected=EbayOrder.STATUS_APPROVED,
            new_status=EbayOrder.STATUS_PAYMENT_RECEIVED,
            task="send_payment_received_task",
            success="Pago del pedido {code} registrado. Se le envió el comprobante al cliente.",
            wrong_state="El pedido {code} tiene que estar aprobado antes de registrar el pago.",
        )

    def in_argentina_view(self, request, order_id):
        return self._advance(
            request, order_id,
            expected=EbayOrder.STATUS_PAYMENT_RECEIVED,
            new_status=EbayOrder.STATUS_IN_ARGENTINA,
            task="send_order_in_argentina_task",
            success="Pedido {code} marcado como llegado. Se le avisó al cliente.",
            wrong_state="Primero hay que registrar el pago del pedido {code}.",
        )

    def delivered_view(self, request, order_id):
        return self._advance(
            request, order_id,
            expected=EbayOrder.STATUS_IN_ARGENTINA,
            new_status=EbayOrder.STATUS_DELIVERED,
            task=None,
            success="Pedido {code} cerrado como entregado.",
            wrong_state="El pedido {code} todavía no llegó a Argentina.",
        )

    def pdf_view(self, request, order_id):
        order = self._get_order(request, order_id)
        if not order:
            return HttpResponseRedirect(reverse("admin:ebay_ebayorder_changelist"))

        try:
            buffer = generate_ebay_order_pdf(order)
        except Exception:
            logger.exception("Error generando el PDF del pedido eBay %s", order.order_code)
            self.message_user(request, "No se pudo generar el PDF.", level=messages.ERROR)
            return self._back(request)

        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="pedido-ebay-{order.order_code}.pdf"'
        return response


@admin.register(EbayConfig)
class EbayConfigAdmin(ModelAdmin):
    list_display = ("__str__", "is_active", "updated_at")

    # Solo lo que el owner decide y cambia. El resto de la config (estado de la
    # sección, texto de la portada, límites, WhatsApp) vive en el modelo pero no
    # se edita: son decisiones de producto que se tocan por código.
    fieldsets = (
        ("Cargos", {
            "fields": ("commission_percent", "tax_percent"),
        }),
        ("Envío a Argentina", {
            "fields": ("arg_shipping",),
        }),
        ("Conexión con eBay", {
            "fields": ("us_zip",),
        }),
    )

    def has_add_permission(self, request):
        # Singleton: se entra siempre al mismo registro.
        return not EbayConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        """Salta la lista de un solo elemento y va derecho al formulario."""
        config = EbayConfig.get()
        return HttpResponseRedirect(
            reverse("admin:ebay_ebayconfig_change", args=[config.pk])
        )
