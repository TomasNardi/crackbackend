from django.contrib import admin
from .models import Order, OrderItem, MercadoPagoPayment, DiscountCode


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("subtotal",)


class MercadoPagoPaymentInline(admin.TabularInline):
    model = MercadoPagoPayment
    extra = 0
    readonly_fields = ("preference_id", "payment_id", "status", "is_paid", "created_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id", "customer_name", "customer_email",
        "total", "status", "shipping_type", "created_at",
    )
    list_filter = ("status", "shipping_type")
    search_fields = ("customer_name", "customer_email", "discount_code")
    readonly_fields = ("created_at", "updated_at")
    inlines = [OrderItemInline, MercadoPagoPaymentInline]


@admin.register(DiscountCode)
class DiscountCodeAdmin(admin.ModelAdmin):
    list_display = (
        "code", "discount_type", "discount_amount",
        "expiration_type", "uses", "max_uses", "used",
    )
    list_filter = ("discount_type", "expiration_type", "used")
    search_fields = ("code",)
    readonly_fields = ("uses", "activated_at", "created_at")


@admin.register(MercadoPagoPayment)
class MercadoPagoPaymentAdmin(admin.ModelAdmin):
    list_display = ("preference_id", "order", "status", "is_paid", "created_at")
    list_filter = ("is_paid", "status")
    readonly_fields = ("created_at", "updated_at", "raw_response")
