from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.utils import timezone
from django.urls import reverse, path
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import format_html
from django.contrib import messages
from unfold.admin import ModelAdmin, TabularInline
from .models import Order, OrderItem, MercadoPagoPayment, DiscountCode, SuggestedProductsCarousel
from .pdf_generator import generate_order_pdf


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
        "transaction_amount", "net_received_amount", "created_at",
    )


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = (
        "order_code", "customer_name", "customer_email",
        "total", "payment_method", "payment_status_display", "shipping_type",
        "pdf_download_button", "created_at_ar",
    )
    list_filter = ("payment_method", "shipping_type")
    search_fields = (
        "order_code", "customer_name", "customer_email", "discount_code",
        "mp_preference_id",
    )
    readonly_fields = (
        "order_code", "created_at", "updated_at",
        "mp_preference_id",
    )
    ordering = ("-created_at",)
    inlines = [OrderItemInline, MercadoPagoPaymentInline]
    actions = [
        "action_mark_cash_paid",
        "action_download_pdf",
    ]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Fecha (AR)", ordering="created_at")
    def created_at_ar(self, obj):
        local = timezone.localtime(obj.created_at)
        return local.strftime("%d/%m/%Y %H:%M")

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
        if obj.payment_method == Order.PAYMENT_CASH and obj.status == Order.STATUS_PAID:
            return format_html('<span style="color:#2ea44f; font-weight:600;">Pagada</span>')

        if obj.payment_method == Order.PAYMENT_MERCADOPAGO:
            mp_payment = obj.mp_payments.order_by("-updated_at", "-created_at").first()
            if not mp_payment:
                return format_html('<span style="color:#888; font-weight:600;">Sin novedades</span>')

            status_raw = (mp_payment.status or "").strip()
            status_key = status_raw.lower()
            status_labels = {
                "preference_created": "Checkout iniciado",
                "approved": "Pagada",
                "pending": "Pendiente",
                "in_process": "En proceso",
                "rejected": "Rechazada",
                "cancelled": "Cancelada",
                "refunded": "Devuelta",
                "charged_back": "Contracargo",
            }
            status_colors = {
                "preference_created": "#888",
                "approved": "#2ea44f",
                "pending": "#e36209",
                "in_process": "#C8972E",
                "rejected": "#d73a49",
                "cancelled": "#d73a49",
                "refunded": "#6f42c1",
                "charged_back": "#6f42c1",
            }
            label = status_labels.get(status_key, status_raw or "Sin estado")
            color = status_colors.get(status_key, "#888")
            return format_html('<span style="color:{}; font-weight:600;">{}</span>', color, label)

        return "—"

    @admin.display(description="PDF")
    def pdf_download_button(self, obj):
        """Botón para descargar ordenada en PDF."""
        url = reverse("admin:orders_order_pdf_download", args=[obj.pk])
        return format_html(
            '<a href="{}" style="'
            'background:#C8972E;color:#fff;padding:5px 12px;border-radius:4px;'
            'font-size:12px;font-weight:600;text-decoration:none;display:inline-block;"'
            'title="Descargar orden en PDF">📄 PDF</a>',
            url,
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
                "<int:order_id>/pdf/",
                self.admin_site.admin_view(self.pdf_download_view),
                name="orders_order_pdf_download",
            ),
        ]
        return custom + urls

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
            self.message_user(request, f"Orden #{order.order_code} marcada como pagada.", level=messages.SUCCESS)

        return HttpResponseRedirect(request.META.get("HTTP_REFERER") or reverse("admin:orders_order_changelist"))

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
        updated = pending_cash.update(status=Order.STATUS_PAID, updated_at=timezone.now())
        skipped = queryset.count() - updated

        if updated:
            self.message_user(request, f"{updated} orden(es) en efectivo marcadas como pagadas.", level=messages.SUCCESS)
        if skipped:
            self.message_user(
                request,
                f"{skipped} orden(es) omitidas: solo se actualizan órdenes en efectivo con estado pendiente.",
                level=messages.WARNING,
            )

@admin.register(DiscountCode)
class DiscountCodeAdmin(ModelAdmin):
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


@admin.register(MercadoPagoPayment)
class MercadoPagoPaymentAdmin(ModelAdmin):
    list_display = (
        "preference_id", "payment_id", "order", "status", "is_paid",
        "payment_method", "payment_type", "transaction_amount", "created_at",
    )
    list_filter = ("is_paid", "status", "payment_type", "payment_method")
    readonly_fields = ("created_at", "updated_at", "raw_response")

    def has_add_permission(self, request):
        return False


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
