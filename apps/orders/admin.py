from django import forms
from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from django.shortcuts import redirect, render
from django.utils import timezone
from django.urls import reverse, path
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import format_html
from django.contrib import messages
from django.db.models import Q
import logging
from unfold.admin import ModelAdmin, TabularInline

logger = logging.getLogger(__name__)
from .models import (
    Order,
    OrderItem,
    MercadoPagoPayment,
    DiscountCode,
    SuggestedProductsCarousel,
    ShippingConfig,
    Shipment,
    ShippingOrder,
)
from .pdf_generator import generate_order_pdf
from .services.stock_reservation_service import consume_order_stock, release_order_stock


class SuggestedProductAdminForm(forms.ModelForm):
    class Meta:
        model = SuggestedProductsCarousel
        fields = "__all__"

    def clean_suggested_products(self):
        suggested = self.cleaned_data.get("suggested_products")
        if suggested is None:
            return suggested

        if suggested.count() > 3:
            raise forms.ValidationError("Solo puedes seleccionar hasta 3 productos sugeridos.")

        return suggested


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("subtotal",)


class MercadoPagoPaymentInline(TabularInline):
    model = MercadoPagoPayment
    extra = 0
    readonly_fields = (
        "preference_id", "payment_id", "status", "is_paid",
        "payment_method", "payment_type", "external_reference",
        "transaction_amount", "net_received_amount", "expires_at", "expired_at", "created_at",
    )


class ShipmentInline(TabularInline):
    model = Shipment
    extra = 0
    max_num = 1
    fields = ("carrier", "tracking_code", "status", "shipped_at", "created_at")
    readonly_fields = ("created_at",)

    def get_readonly_fields(self, request, obj=None):
        base = list(super().get_readonly_fields(request, obj))
        if obj and obj.status != Order.STATUS_PAID:
            for field in ("tracking_code", "status", "shipped_at"):
                if field not in base:
                    base.append(field)
        return tuple(base)

    def has_add_permission(self, request, obj=None):
        if obj and obj.status != Order.STATUS_PAID:
            return False
        return super().has_add_permission(request, obj)


class ShipmentQuickUpdateForm(forms.Form):
    carrier = forms.ChoiceField(
        label="Empresa de correo",
        required=True,
        choices=Shipment.CARRIER_CHOICES,
    )
    tracking_code = forms.CharField(
        label="Código de seguimiento",
        max_length=120,
        required=True,
        widget=forms.TextInput(attrs={"placeholder": "Ej: PAQ123456789AR"}),
    )


class DiscountCodeAdminForm(forms.ModelForm):
    class Meta:
        model = DiscountCode
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        expiration_type = cleaned_data.get("expiration_type")

        if expiration_type == DiscountCode.EXPIRATION_NONE:
            # If there is no expiration, avoid persisting stale date values.
            cleaned_data["valid_from"] = None
            cleaned_data["valid_until"] = None

        return cleaned_data


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    MP_STATUS_LABELS = {
        "preference_created": "Checkout iniciado",
        "approved": "Pagada",
        "pending": "Pendiente",
        "in_process": "En proceso",
        "rejected": "Rechazada",
        "cancelled": "Cancelada",
        "refunded": "Devolución",
        "charged_back": "Contracargo",
        "expired": "Checkout vencido",
    }
    MP_STATUS_COLORS = {
        "preference_created": "#888888",
        "approved": "#2ea44f",
        "pending": "#e36209",
        "in_process": "#C8972E",
        "rejected": "#d73a49",
        "cancelled": "#d73a49",
        "refunded": "#d73a49",
        "charged_back": "#d73a49",
        "expired": "#C8972E",
    }

    list_display = (
        "order_summary", "customer_summary", "total_display",
        "payment_summary", "shipping_summary", "pdf_download_button",
    )
    list_display_links = ("order_summary",)
    list_filter = ("payment_method", "shipping_type", "shipping_method", "shipping_status")
    search_fields = (
        "order_code", "customer_name", "customer_email", "discount_code",
        "mp_preference_id",
    )
    readonly_fields = (
        "order_code", "created_at", "updated_at",
        "mp_preference_id",
    )
    ordering = ("-created_at",)
    list_per_page = 40
    list_max_show_all = 200
    inlines = [OrderItemInline, MercadoPagoPaymentInline]
    actions = [
        "action_mark_cash_paid",
        "action_return_stock",
        "action_download_pdf",
    ]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Orden", ordering="created_at")
    def order_summary(self, obj):
        """Código de orden + fecha en una sola celda compacta."""
        local = timezone.localtime(obj.created_at)
        return format_html(
            '<div style="line-height:1.45;">'
            '<div style="font-weight:700;font-size:13px;letter-spacing:0.03em;">{}</div>'
            '<div style="color:#9ca3af;font-size:11px;margin-top:2px;white-space:nowrap;">{}</div>'
            '</div>',
            obj.order_code,
            local.strftime("%d/%m/%Y · %H:%M"),
        )

    @admin.display(description="Cliente", ordering="customer_name")
    def customer_summary(self, obj):
        """Nombre + email en una sola celda, con recorte para evitar desbordes."""
        return format_html(
            '<div style="line-height:1.45;max-width:240px;">'
            '<div style="font-weight:600;color:#1a1a1a;white-space:nowrap;'
            'overflow:hidden;text-overflow:ellipsis;">{}</div>'
            '<div style="color:#9ca3af;font-size:11px;margin-top:2px;white-space:nowrap;'
            'overflow:hidden;text-overflow:ellipsis;" title="{}">{}</div>'
            '</div>',
            obj.customer_name or "—",
            obj.customer_email or "",
            obj.customer_email or "—",
        )

    @admin.display(description="Total", ordering="total")
    def total_display(self, obj):
        """Total con formato de moneda argentino ($ 1.234,56)."""
        amount = f"{obj.total:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
        return format_html(
            '<span style="font-weight:700;font-size:13px;white-space:nowrap;">$ {}</span>',
            amount,
        )

    @admin.display(description="Pago", ordering="payment_method")
    def payment_summary(self, obj):
        """Método de pago + estado de cobro (badge o botón de acción)."""
        method = obj.get_payment_method_display()
        if obj.payment_method == Order.PAYMENT_CASH and obj.status == Order.STATUS_PENDING:
            url = reverse("admin:orders_order_mark_cash_paid", args=[obj.pk])
            badge = format_html(
                '<a href="{}" style="background:#2ea44f;color:#fff;padding:3px 9px;'
                'border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;'
                'display:inline-block;" title="Marcar orden en efectivo como pagada">'
                '✓ Marcar pagada</a>',
                url,
            )
        else:
            _, label, color = self._payment_status_meta(obj)
            badge = format_html(
                '<span style="display:inline-block;padding:2px 9px;border-radius:6px;'
                'font-size:11px;font-weight:600;color:{};background:{}1f;">{}</span>',
                color, color, label,
            )
        return format_html(
            '<div style="line-height:1.6;">'
            '<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">{}</div>'
            '<div>{}</div>'
            '<div style="margin-top:4px;">{}</div>'
            '</div>',
            method,
            badge,
            self.return_stock_button(obj),
        )

    def return_stock_button(self, obj):
        """
        Deshace la orden y devuelve la mercadería a la venta.

        Aparece mientras la orden tenga mercadería tomada —apartada por una
        reserva o ya descontada por una venta—, así sirve tanto para el que
        nunca transfirió como para la venta que se cae después de cobrada.
        """
        if obj.stock_status not in {Order.STOCK_RESERVED, Order.STOCK_CONSUMED}:
            return format_html('<span style="font-size:10px;color:#9ca3af;">Sin stock tomado</span>')

        label = (
            "↩ Regresar al stock"
            if obj.stock_status == Order.STOCK_RESERVED
            else "↩ Regresar al stock (revierte la venta)"
        )
        url = reverse("admin:orders_order_return_stock", args=[obj.pk])
        return format_html(
            '<a href="{}" onclick="return confirm(&#39;¿Devolver la mercadería de esta '
            'orden al stock? La orden queda cancelada.&#39;);" '
            'style="background:#d73a49;color:#fff;padding:3px 9px;'
            'border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;'
            'display:inline-block;" title="Libera la mercadería y cancela la orden">{}</a>',
            url, label,
        )

    @admin.display(description="Envío", ordering="shipping_type")
    def shipping_summary(self, obj):
        """Tipo de envío + botón/estado de despacho en una sola celda."""
        return format_html(
            '<div style="line-height:1.6;">'
            '<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">{}</div>'
            '<div>{}</div>'
            '</div>',
            obj.get_shipping_type_display(),
            self.shipping_hub_button(obj),
        )

    def _payment_status_meta(self, obj):
        # Order-level terminal overrides.
        if obj.status == Order.STATUS_REFUNDED:
            return "refunded", "Devolución", "#d73a49"
        if obj.status == Order.STATUS_EXPIRED:
            return "expired", "Vencida", "#C8972E"
        if obj.status == Order.STATUS_CANCELLED:
            return "cancelled", "Cancelada", "#d73a49"

        if obj.payment_method == Order.PAYMENT_CASH and obj.status == Order.STATUS_PENDING:
            return "pending_cash", "Pendiente", "#2ea44f"
        if obj.payment_method == Order.PAYMENT_CASH and obj.status == Order.STATUS_PAID:
            return "paid_cash", "Pagada", "#2ea44f"

        if obj.payment_method == Order.PAYMENT_MERCADOPAGO:
            mp_payment = obj.mp_payments.order_by("-updated_at", "-created_at").first()
            if not mp_payment:
                return "none", "Sin novedades", "#888888"

            status_raw = (mp_payment.status or "").strip()
            status_key = status_raw.lower()
            label = self.MP_STATUS_LABELS.get(status_key, status_raw or "Sin estado")
            color = self.MP_STATUS_COLORS.get(status_key, "#888888")
            return status_key, label, color

        return "none", "—", "#888888"

    def _requires_shipping_dispatch(self, obj):
        """Detect if an order requires shipment even when legacy has_shipping is desynced."""
        if obj.shipping_method == Order.SHIPPING_METHOD_STORE_PICKUP:
            return False

        if obj.shipping_method in {
            Order.SHIPPING_METHOD_HOME,
            Order.SHIPPING_METHOD_BRANCH_NORMAL,
            Order.SHIPPING_METHOD_BRANCH_EXPRESS,
        }:
            return True

        if obj.shipping_type == Order.SHIPPING_PICKUP:
            return False

        if obj.shipping_type == Order.SHIPPING_HOME:
            return True

        return bool(
            obj.has_shipping
            or obj.shipping_address
            or obj.shipping_branch
            or obj.shipping_city
            or obj.shipping_province
            or obj.shipping_zip
        )

    def _is_store_pickup(self, obj):
        if obj.shipping_method == Order.SHIPPING_METHOD_STORE_PICKUP:
            return True
        return obj.shipping_type == Order.SHIPPING_PICKUP

    @admin.display(description="Cobro")
    def payment_status_display(self, obj):
        if obj.payment_method == Order.PAYMENT_CASH and obj.status == Order.STATUS_PENDING:
            url = reverse("admin:orders_order_mark_cash_paid", args=[obj.pk])
            return format_html(
                '<a href="{}" style="'
                'background:#2ea44f;color:#fff;padding:4px 10px;border-radius:4px;'
                'font-size:12px;font-weight:600;text-decoration:none;display:inline-block;"'
                'title="Marcar orden en efectivo como pagada">Marcar pagada</a>',
                url,
            )
        _, label, color = self._payment_status_meta(obj)
        return format_html('<span style="color:{}; font-weight:600;">{}</span>', color, label)

    @admin.display(description="PDF")
    def pdf_download_button(self, obj):
        """Botón para descargar ordenada en PDF."""
        url = reverse("admin:orders_order_pdf_download", args=[obj.pk])
        _, _, color = self._payment_status_meta(obj)
        return format_html(
            '<a href="{}" style="'
            'background:{};color:#fff;padding:5px 12px;border-radius:4px;'
            'font-size:12px;font-weight:600;text-decoration:none;display:inline-block;"'
            'title="Descargar orden en PDF">📄 PDF</a>',
            url, color,
        )

    @admin.display(description="Envíos")
    def shipping_hub_button(self, obj):
        if self._is_store_pickup(obj):
            if obj.status != Order.STATUS_PAID:
                return format_html(
                    '<span style="'
                    'background:#9ca3af;color:#fff;padding:5px 12px;border-radius:4px;'
                    'font-size:12px;font-weight:600;display:inline-block;cursor:not-allowed;opacity:0.75;"'
                    ' title="La orden debe estar pagada antes de avisar que está preparada para retiro.">Preparado</span>'
                )

            if obj.pickup_ready_notified_at:
                return format_html(
                    '<span style="'
                    'background:#2ea44f;color:#fff;padding:5px 12px;border-radius:4px;'
                    'font-size:12px;font-weight:600;display:inline-block;cursor:not-allowed;opacity:0.85;"'
                    ' title="Ya se envió el aviso de retiro preparado al cliente.">✅ Preparado y listo</span>'
                )

            url = reverse("admin:orders_order_pickup_ready", args=[obj.pk])
            return format_html(
                '<a href="{}" style="'
                'background:#2ea44f;color:#fff;padding:5px 12px;border-radius:4px;'
                'font-size:12px;font-weight:600;text-decoration:none;display:inline-block;"'
                'title="Enviar email para coordinar retiro">Preparado</a>',
                url,
            )

        if not self._requires_shipping_dispatch(obj):
            return format_html('<span style="color:#999;">—</span>')

        if obj.shipping_status == Order.SHIPPING_STATUS_SHIPPED:
            return format_html(
                '<span style="'
                'background:#2ea44f;color:#fff;padding:5px 12px;border-radius:4px;'
                'font-size:12px;font-weight:600;display:inline-block;">🚚 Enviado</span>'
            )

        if obj.status != Order.STATUS_PAID:
            return format_html(
                '<span style="'
                'background:#9ca3af;color:#fff;padding:5px 12px;border-radius:4px;'
                'font-size:12px;font-weight:600;display:inline-block;cursor:not-allowed;opacity:0.75;"'
                ' title="La orden debe estar pagada antes de cargar el envío.">Pendiente de pago</span>'
            )

        url = reverse("admin:orders_order_shipping_popup", args=[obj.pk])
        return format_html(
            '<a href="{}" onclick="window.open(this.href, \'shipping-popup-{}\', \'width=560,height=520,resizable=yes,scrollbars=yes\'); return false;" style="'
            'background:#2d6cdf;color:#fff;padding:5px 12px;border-radius:4px;'
            'font-size:12px;font-weight:600;text-decoration:none;display:inline-block;"'
            'title="Cargar envío de esta orden">Cargar envío</a>',
            url,
            obj.pk,
        )

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:order_id>/mark-cash-paid/",
                self.admin_site.admin_view(self.mark_cash_paid_view),
                name="orders_order_mark_cash_paid",
            ),
            path(
                "<int:order_id>/return-stock/",
                self.admin_site.admin_view(self.return_stock_view),
                name="orders_order_return_stock",
            ),
            path(
                "<int:order_id>/pdf/",
                self.admin_site.admin_view(self.pdf_download_view),
                name="orders_order_pdf_download",
            ),
            path(
                "<int:order_id>/shipping-popup/",
                self.admin_site.admin_view(self.shipping_popup_view),
                name="orders_order_shipping_popup",
            ),
            path(
                "<int:order_id>/pickup-ready/",
                self.admin_site.admin_view(self.pickup_ready_view),
                name="orders_order_pickup_ready",
            ),
        ]
        return custom + urls

    def pickup_ready_view(self, request, order_id):
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            self.message_user(request, "Orden no encontrada.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_order_changelist"))

        if not self._is_store_pickup(order):
            self.message_user(
                request,
                f"La orden #{order.order_code} no es retiro en local.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist"))

        if order.status != Order.STATUS_PAID:
            self.message_user(
                request,
                "La orden debe estar pagada antes de enviar el aviso de retiro preparado.",
                level=messages.WARNING,
            )
            return HttpResponseRedirect(request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist"))

        if order.pickup_ready_notified_at:
            self.message_user(
                request,
                f"La orden #{order.order_code} ya estaba marcada como retiro preparado.",
                level=messages.INFO,
            )
            return HttpResponseRedirect(request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist"))

        try:
            from .emails import send_pickup_ready_notification

            send_pickup_ready_notification(order.id)
            order.pickup_ready_notified_at = timezone.now()
            order.save(update_fields=["pickup_ready_notified_at", "updated_at"])
            self.message_user(
                request,
                f"Se envió el email de retiro preparado para la orden #{order.order_code}.",
                level=messages.SUCCESS,
            )
        except Exception as exc:
            logger.exception("Error enviando email de retiro preparado para orden %s: %s", order.order_code, exc)
            self.message_user(
                request,
                f"No se pudo enviar el email de retiro preparado: {exc}",
                level=messages.ERROR,
            )

        return HttpResponseRedirect(request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist"))

    def shipping_popup_view(self, request, order_id):
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return HttpResponse("Orden no encontrada.", status=404)

        if not self._requires_shipping_dispatch(order):
            return HttpResponse("Esta orden es retiro en persona y no requiere despacho.", status=400)

        if order.status != Order.STATUS_PAID:
            return HttpResponse(
                "La orden debe estar pagada antes de cargar el envío.",
                status=403,
            )

        shipment, _ = Shipment.objects.get_or_create(order=order, defaults={"status": Shipment.STATUS_PENDING})

        if request.method == "POST":
            form = ShipmentQuickUpdateForm(request.POST)
            if form.is_valid():
                shipment.carrier = form.cleaned_data["carrier"]
                shipment.tracking_code = form.cleaned_data["tracking_code"].strip()
                shipment.status = Shipment.STATUS_SHIPPED
                shipment.save(update_fields=["carrier", "tracking_code", "status", "shipped_at"])

                return HttpResponse(
                    "<script>"
                    "if (window.opener) { window.opener.location.reload(); }"
                    "window.close();"
                    "</script>"
                )
        else:
            form = ShipmentQuickUpdateForm(initial={
                "carrier": shipment.carrier,
                "tracking_code": shipment.tracking_code,
            })

        context = {
            "title": "Cargar envío",
            "order": order,
            "shipment": shipment,
            "form": form,
        }
        return render(request, "admin/orders/shipping_popup.html", context)

    def mark_cash_paid_view(self, request, order_id):
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            self.message_user(request, "Orden no encontrada.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_order_changelist"))

        if order.payment_method != Order.PAYMENT_CASH:
            self.message_user(
                request,
                f"La orden #{order.order_code} no es de pago en efectivo.",
                level=messages.WARNING,
            )
        elif order.status == Order.STATUS_PAID:
            self.message_user(request, f"La orden #{order.order_code} ya estaba pagada.", level=messages.INFO)
        else:
            order.status = Order.STATUS_PAID
            order.save(update_fields=["status", "updated_at"])
            # Recién acá la reserva se convierte en venta y baja el stock.
            consume_order_stock(order)
            self.message_user(request, f"Orden #{order.order_code} marcada como pagada.", level=messages.SUCCESS)
            try:
                from .emails import send_payment_confirmed_email
                send_payment_confirmed_email(order.id)
            except Exception as exc:
                logger.exception("Error enviando email de pago confirmado para orden %s: %s", order.order_code, exc)

        return HttpResponseRedirect(request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist"))

    def return_stock_view(self, request, order_id):
        """Devuelve la mercadería de una orden al stock y la deja cancelada."""
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            self.message_user(request, "Orden no encontrada.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_order_changelist"))

        released = release_order_stock(order)

        if not released:
            self.message_user(
                request,
                f"La orden #{order.order_code} no tiene mercadería tomada del stock.",
                level=messages.WARNING,
            )
        else:
            if order.status != Order.STATUS_CANCELLED:
                order.status = Order.STATUS_CANCELLED
                order.save(update_fields=["status", "updated_at"])
            self.message_user(
                request,
                f"Mercadería de la orden #{order.order_code} devuelta al stock. "
                "La orden quedó cancelada.",
                level=messages.SUCCESS,
            )

        return HttpResponseRedirect(
            request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist")
        )

    def pdf_download_view(self, request, order_id):
        """Genera y descarga el PDF de la orden."""
        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            self.message_user(request, "Orden no encontrada.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_order_changelist"))

        try:
            pdf_buffer = generate_order_pdf(order)
            filename = f"orden_{order.order_code}.pdf"
            response = HttpResponse(pdf_buffer, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            return response
        except Exception as exc:
            self.message_user(request, f"Error al generar PDF: {exc}", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_order_change", args=[order_id]))

    @admin.action(description="⬇ Descargar seleccionadas como ZIP")
    def action_download_pdf(self, request, queryset):
        """Acción para descargar múltiples órdenes (para futura implementación con ZIP)."""
        if queryset.count() == 1:
            # Si es una sola, descargar directamente
            order = queryset.first()
            try:
                pdf_buffer = generate_order_pdf(order)
                filename = f"orden_{order.order_code}.pdf"
                response = HttpResponse(pdf_buffer, content_type="application/pdf")
                response["Content-Disposition"] = f'attachment; filename="{filename}"'
                return response
            except Exception as exc:
                self.message_user(request, f"Error al generar PDF: {exc}", level=messages.ERROR)
        else:
            # Para múltiples, mostrar mensaje informativo
            self.message_user(
                request,
                f"{queryset.count()} orden(es) seleccionadas. Usa el botón PDF en cada orden o descargalas de una en una.",
                level=messages.INFO
            )

    @admin.action(description="Marcar como pagadas (solo efectivo pendientes)")
    def action_mark_cash_paid(self, request, queryset):
        pending_cash = queryset.filter(
            payment_method=Order.PAYMENT_CASH,
            status=Order.STATUS_PENDING,
        )
        # Una por una y no con `update()`: cada orden tiene que convertir su
        # reserva en venta, y eso mira los ítems de esa orden.
        order_ids = []
        for order in pending_cash:
            order.status = Order.STATUS_PAID
            order.save(update_fields=["status", "updated_at"])
            consume_order_stock(order)
            order_ids.append(order.id)

        updated = len(order_ids)
        skipped = queryset.count() - updated

        if updated:
            self.message_user(request, f"{updated} orden(es) en efectivo marcadas como pagadas.", level=messages.SUCCESS)
            from .emails import send_payment_confirmed_email
            for order_id in order_ids:
                try:
                    send_payment_confirmed_email(order_id)
                except Exception as exc:
                    logger.exception("Error enviando email de pago confirmado para orden id=%s: %s", order_id, exc)
        if skipped:
            self.message_user(
                request,
                f"{skipped} orden(es) omitidas: solo se actualizan órdenes en efectivo con estado pendiente.",
                level=messages.WARNING,
            )
            

    @admin.action(description="↩ Regresar al stock y cancelar")
    def action_return_stock(self, request, queryset):
        returned = 0
        for order in queryset:
            if not release_order_stock(order):
                continue
            if order.status != Order.STATUS_CANCELLED:
                order.status = Order.STATUS_CANCELLED
                order.save(update_fields=["status", "updated_at"])
            returned += 1

        skipped = queryset.count() - returned

        if returned:
            self.message_user(
                request,
                f"{returned} orden(es) devueltas al stock y canceladas.",
                level=messages.SUCCESS,
            )
        if skipped:
            self.message_user(
                request,
                f"{skipped} orden(es) omitidas: no tenían mercadería tomada del stock.",
                level=messages.WARNING,
            )


@admin.register(DiscountCode)
class DiscountCodeAdmin(ModelAdmin):
    form = DiscountCodeAdminForm
    list_display = (
        "code", "discount_type", "discount_amount",
        "expiration_type", "valid_from_ar", "valid_until_ar",
        "uses", "max_uses", "used",
    )
    list_filter = ("discount_type", "expiration_type", "used")
    search_fields = ("code",)
    readonly_fields = ("uses", "activated_at", "created_at")

    fieldsets = (
        ("Código", {
            "fields": ("code", "discount_type", "discount_amount"),
        }),
        ("Expiración", {
            "description": "Las fechas se interpretan en hora de Argentina (ART, UTC-3).",
            "fields": ("expiration_type", "valid_from", "valid_until"),
        }),
        ("Uso", {
            "fields": ("max_uses", "uses", "used"),
        }),
        ("Auditoría", {
            "fields": ("activated_at", "created_at"),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="Válido desde (AR)", ordering="valid_from")
    def valid_from_ar(self, obj):
        if not obj.valid_from:
            return "—"
        return timezone.localtime(obj.valid_from).strftime("%d/%m/%Y %H:%M")

    @admin.display(description="Válido hasta (AR)", ordering="valid_until")
    def valid_until_ar(self, obj):
        if not obj.valid_until:
            return "—"
        return timezone.localtime(obj.valid_until).strftime("%d/%m/%Y %H:%M")

    class Media:
        js = ("admin/js/discount_code_expiration.js",)


@admin.register(MercadoPagoPayment)
class MercadoPagoPaymentAdmin(ModelAdmin):
    list_display = (
        "preference_id", "payment_id", "order", "status", "is_paid",
        "payment_method", "payment_type", "transaction_amount", "expires_at", "expired_at", "created_at",
    )
    list_filter = ("is_paid", "status", "payment_type", "payment_method")
    readonly_fields = ("created_at", "updated_at", "raw_response")

    def has_add_permission(self, request):
        return False


@admin.register(ShippingConfig)
class ShippingConfigAdmin(ModelAdmin):
    list_display = ("key", "price", "updated_at")
    list_editable = ("price",)
    search_fields = ("key",)
    ordering = ("key",)


@admin.register(Shipment)
class ShipmentAdmin(ModelAdmin):
    list_display = ("order", "carrier", "tracking_code", "status", "shipped_at", "created_at")
    list_filter = ("status", "carrier")
    search_fields = ("order__order_code", "order__customer_name", "tracking_code")
    readonly_fields = ("created_at",)


class ShippingDispatchFilter(SimpleListFilter):
    title = "Despacho"
    parameter_name = "dispatch_state"

    def lookups(self, request, model_admin):
        return [
            ("pending", "No despachados"),
            ("shipped", "Enviados"),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "pending":
            return queryset.filter(shipping_status=Order.SHIPPING_STATUS_PENDING)
        if value == "shipped":
            return queryset.filter(shipping_status=Order.SHIPPING_STATUS_SHIPPED)
        return queryset


class ShippingModeFilter(SimpleListFilter):
    title = "Modalidad"
    parameter_name = "shipping_mode"

    def lookups(self, request, model_admin):
        return [
            ("express", "Express"),
            ("home", "Domicilio"),
            ("branch", "Sucursal"),
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if value == "express":
            return queryset.filter(shipping_method=Order.SHIPPING_METHOD_BRANCH_EXPRESS)
        if value == "home":
            return queryset.filter(shipping_method=Order.SHIPPING_METHOD_HOME)
        if value == "branch":
            return queryset.filter(
                shipping_method__in=[
                    Order.SHIPPING_METHOD_BRANCH_NORMAL,
                    Order.SHIPPING_METHOD_BRANCH_EXPRESS,
                ]
            )
        return queryset


@admin.register(ShippingOrder)
class ShippingOrderAdmin(ModelAdmin):
    list_display = (
        "order_link",
        "customer_name",
        "shipping_method_display",
        "shipping_status_display",
        "shipping_carrier_display",
        "tracking_code",
        "created_at_ar",
        "shipped_at_display",
    )
    list_filter = (ShippingDispatchFilter, ShippingModeFilter, "shipping_method", "shipping_status")
    search_fields = ("order_code", "customer_name", "customer_email", "shipment__tracking_code")
    ordering = ("-created_at",)
    readonly_fields = (
        "order_code",
        "created_at",
        "updated_at",
        "mp_preference_id",
        "shipping_method",
        "shipping_status",
        "shipping_price",
        "has_shipping",
    )
    inlines = [ShipmentInline]

    fieldsets = (
        ("Orden", {"fields": ("order_code", "customer_name", "customer_email", "created_at")}),
        (
            "Envío",
            {
                "fields": (
                    "has_shipping",
                    "shipping_method",
                    "shipping_status",
                    "shipping_price",
                    "shipping_address",
                    "shipping_city",
                    "shipping_province",
                    "shipping_zip",
                    "shipping_branch",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                Q(has_shipping=True)
                | Q(shipping_type=Order.SHIPPING_HOME)
                | Q(shipping_method__in=[
                    Order.SHIPPING_METHOD_HOME,
                    Order.SHIPPING_METHOD_BRANCH_NORMAL,
                    Order.SHIPPING_METHOD_BRANCH_EXPRESS,
                ])
            )
            .select_related("shipment")
            .order_by("-created_at")
        )

    def has_add_permission(self, request):
        return False

    @admin.display(description="Orden", ordering="id")
    def order_link(self, obj):
        url = reverse("admin:orders_order_change", args=[obj.pk])
        return format_html('<a href="{}">#{}</a>', url, obj.order_code)

    @admin.display(description="Código seguimiento")
    def tracking_code(self, obj):
        shipment = getattr(obj, "shipment", None)
        return shipment.tracking_code if shipment and shipment.tracking_code else "—"

    @admin.display(description="Correo")
    def shipping_carrier_display(self, obj):
        shipment = getattr(obj, "shipment", None)
        if not shipment:
            return "—"
        return shipment.get_carrier_display()

    @admin.display(description="Método envío", ordering="shipping_method")
    def shipping_method_display(self, obj):
        return obj.get_shipping_method_display()

    @admin.display(description="Estado", ordering="shipping_status")
    def shipping_status_display(self, obj):
        return obj.get_shipping_status_display()

    @admin.display(description="Fecha compra", ordering="created_at")
    def created_at_ar(self, obj):
        local = timezone.localtime(obj.created_at)
        return local.strftime("%d/%m/%Y %H:%M")

    @admin.display(description="Fecha despacho")
    def shipped_at_display(self, obj):
        shipment = getattr(obj, "shipment", None)
        if not shipment or not shipment.shipped_at:
            return "—"
        return timezone.localtime(shipment.shipped_at).strftime("%d/%m/%Y %H:%M")


@admin.register(SuggestedProductsCarousel)
class SuggestedProductsCarouselAdmin(ModelAdmin):
    form = SuggestedProductAdminForm
    list_display = ("id", "suggested_count", "updated_at")
    filter_horizontal = ("suggested_products",)
    fieldsets = (
        ("Productos sugeridos", {
            "fields": ("suggested_products",),
            "description": "Elegí hasta 3 productos para el carrusel del detalle.",
        }),
    )

    def suggested_count(self, obj):
        return obj.suggested_products.count()

    suggested_count.short_description = "Sugeridos"

    class Media:
        js = ("admin/js/suggested_products_limit.js",)

    def changelist_view(self, request, extra_context=None):
        config, _ = SuggestedProductsCarousel.objects.get_or_create(pk=1)
        url = reverse("admin:orders_suggestedproductscarousel_change", args=[config.pk])
        return redirect(url)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
