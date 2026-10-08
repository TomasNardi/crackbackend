from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from apps.orders.models import Order

from .models import Customer, CustomerAddress


class CustomerAddressInline(TabularInline):
    model = CustomerAddress
    extra = 0
    fields = ("kind", "branch_name", "address", "city", "province", "zip_code", "phone", "is_default")


class CustomerOrderInline(TabularInline):
    model = Order
    fk_name = "customer"
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ("order_code", "created_at", "status", "total")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(ModelAdmin):
    list_display = ("email", "full_name", "phone", "provider", "email_verified", "created_at", "last_login_at")
    list_filter = ("provider", "email_verified")
    search_fields = ("email", "first_name", "last_name", "phone")
    readonly_fields = ("supabase_uid", "email", "email_verified", "provider", "avatar_url", "created_at", "last_login_at")
    fields = (
        "email", "first_name", "last_name", "phone",
        "provider", "email_verified", "supabase_uid", "avatar_url", "created_at", "last_login_at",
    )
    inlines = [CustomerAddressInline, CustomerOrderInline]

    @admin.display(description="Nombre")
    def full_name(self, obj):
        return obj.full_name or "—"
