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
        "total", "status", "payment_method", "shipping_type", "paqar_status_display",
        "paqar_label_button", "created_at_ar",
    )
    list_filter = ("status", "payment_method", "shipping_type", "paqar_status")
    search_fields = (
        "order_code", "customer_name", "customer_email", "discount_code",
        "paqar_tracking_number", "mp_preference_id",
    )
    readonly_fields = (
        "order_code", "created_at", "updated_at",
        "paqar_tracking_number", "paqar_error", "paqar_status", "mp_preference_id",
    )
    ordering = ("-created_at",)
    inlines = [OrderItemInline, MercadoPagoPaymentInline]
    actions = ["action_create_paqar_order", "action_cancel_paqar_order"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Fecha (AR)", ordering="created_at")
    def created_at_ar(self, obj):
        local = timezone.localtime(obj.created_at)
        return local.strftime("%d/%m/%Y %H:%M")

    @admin.display(description="Paq.ar", ordering="paqar_status")
    def paqar_status_display(self, obj):
        colors = {
            "pending": "#888",
            "created": "#2ea44f",
            "error": "#d73a49",
            "cancelled": "#e36209",
        }
        color = colors.get(obj.paqar_status, "#888")
        label = obj.get_paqar_status_display()
        return format_html('<span style="color:{}; font-weight:600;">{}</span>', color, label)

    @admin.display(description="Etiqueta")
    def paqar_label_button(self, obj):
        if obj.paqar_status == Order.PAQAR_STATUS_CREATED and obj.paqar_tracking_number:
            url = reverse("admin:orders_order_paqar_label", args=[obj.pk])
            return format_html(
                '<a href="{}" target="_blank" style="'
                'background:#C8972E;color:#fff;padding:3px 10px;border-radius:4px;'
                'font-size:12px;font-weight:600;text-decoration:none;">'
                '⬇ Descargar</a>',
                url,
            )
        return "—"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:order_id>/paqar-label/",
                self.admin_site.admin_view(self.paqar_label_view),
                name="orders_order_paqar_label",
            ),
        ]
        return custom + urls

    def paqar_label_view(self, request, order_id):
        """Descarga la etiqueta PDF desde Paq.ar y la sirve como respuesta HTTP."""
        from .paqar_client import get_label, PaqarError
        order = Order.objects.get(pk=order_id)

        if not order.paqar_tracking_number:
            self.message_user(request, "Esta orden no tiene Tracking Number en Paq.ar.", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_order_change", args=[order_id]))

        try:
            pdf_bytes = get_label(order.paqar_tracking_number)
        except PaqarError as exc:
            self.message_user(request, f"Error al obtener etiqueta: {exc}", level=messages.ERROR)
            return HttpResponseRedirect(reverse("admin:orders_order_change", args=[order_id]))

        filename = f"etiqueta_{order.order_code}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @admin.action(description="Generar envío en Paq.ar (Correo Argentino)")
    def action_create_paqar_order(self, request, queryset):
        from .paqar_client import create_order, PaqarError
        ok = 0
        ko = 0
        for order in queryset:
            if order.paqar_status == Order.PAQAR_STATUS_CREATED:
                self.message_user(
                    request,
                    f"Orden #{order.order_code} ya tiene envío generado (TN: {order.paqar_tracking_number}).",
                    level=messages.WARNING,
                )
                continue
            if order.shipping_type != Order.SHIPPING_HOME:
                # Para retiro en sucursal también se puede dar de alta pero requiere agencyId
                pass
            try:
                data = create_order(order)
                tracking = data.get("trackingNumber", "")
                order.paqar_tracking_number = tracking
                order.paqar_status = Order.PAQAR_STATUS_CREATED
                order.paqar_error = ""
                order.save(update_fields=["paqar_tracking_number", "paqar_status", "paqar_error", "updated_at"])
                self.message_user(request, f"Orden #{order.order_code} generada en Paq.ar — TN: {tracking}")
                ok += 1
            except PaqarError as exc:
                order.paqar_status = Order.PAQAR_STATUS_ERROR
                order.paqar_error = str(exc)
                order.save(update_fields=["paqar_status", "paqar_error", "updated_at"])
                self.message_user(request, f"Error en orden #{order.order_code}: {exc}", level=messages.ERROR)
                ko += 1
        if ok:
            self.message_user(request, f"{ok} orden(es) generadas correctamente en Paq.ar.")

    @admin.action(description="Cancelar envío en Paq.ar")
    def action_cancel_paqar_order(self, request, queryset):
        from .paqar_client import cancel_order, PaqarError
        for order in queryset:
            if not order.paqar_tracking_number:
                self.message_user(request, f"Orden #{order.order_code} no tiene TN de Paq.ar.", level=messages.WARNING)
                continue
            try:
                cancel_order(order.paqar_tracking_number)
                order.paqar_status = Order.PAQAR_STATUS_CANCELLED
                order.save(update_fields=["paqar_status", "updated_at"])
                self.message_user(request, f"Orden #{order.order_code} cancelada en Paq.ar.")
            except PaqarError as exc:
                self.message_user(request, f"Error cancelando #{order.order_code}: {exc}", level=messages.ERROR)


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

    def changelist_view(self, request, extra_context=None):
        config, _ = SuggestedProductsCarousel.objects.get_or_create(pk=1)
        url = reverse("admin:orders_suggestedproductscarousel_change", args=[config.pk])
        return redirect(url)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
