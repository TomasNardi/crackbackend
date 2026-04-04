from django.contrib import admin
from django.utils import timezone
from unfold.admin import ModelAdmin, TabularInline
from .models import Order, OrderItem, MercadoPagoPayment, DiscountCode


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("subtotal",)


class MercadoPagoPaymentInline(TabularInline):
    model = MercadoPagoPayment
    extra = 0
    readonly_fields = ("preference_id", "payment_id", "status", "is_paid", "created_at")


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = (
        "id", "customer_name", "customer_email",
        "total", "status", "shipping_type", "created_at_ar",
    )
    list_filter = ("status", "shipping_type")
    search_fields = ("customer_name", "customer_email", "discount_code")
    readonly_fields = ("created_at", "updated_at")
    inlines = [OrderItemInline, MercadoPagoPaymentInline]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Fecha (AR)", ordering="created_at")
    def created_at_ar(self, obj):
        local = timezone.localtime(obj.created_at)
        return local.strftime("%d/%m/%Y %H:%M")


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
    list_display = ("preference_id", "order", "status", "is_paid", "created_at")
    list_filter = ("is_paid", "status")
    readonly_fields = ("created_at", "updated_at", "raw_response")

    def has_add_permission(self, request):
        return False
