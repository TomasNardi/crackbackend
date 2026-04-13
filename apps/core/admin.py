from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from unfold.admin import ModelAdmin
from .models import SiteConfig, PaymentSettings, EmailSubscription, ExchangeRate, ContactMessage


@admin.register(ExchangeRate)
class ExchangeRateAdmin(ModelAdmin):
    list_display = ("usd_to_ars", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not ExchangeRate.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SiteConfig)
class SiteConfigAdmin(ModelAdmin):
    list_display = ("estado_sitio", "maintenance_message")
    fieldsets = (
        (
            "Configuración general",
            {
                "fields": ("is_active", "maintenance_message"),
                "description": "Controla estado del sitio y mensaje de mantenimiento.",
            },
        ),
    )

    @admin.display(description="Estado")
    def estado_sitio(self, obj):
        return "Activo" if obj.is_active else "Mantenimiento"

    def has_add_permission(self, request):
        return not SiteConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Singleton UX: entra directo al único registro editable.
        obj = SiteConfig.get()
        change_url = reverse("admin:core_siteconfig_change", args=[obj.pk])
        return redirect(change_url)


@admin.register(PaymentSettings)
class PaymentSettingsAdmin(ModelAdmin):
    list_display = ("pago_efectivo_activo", "descuento_efectivo")
    fieldsets = (
        (
            "Configuración de pagos",
            {
                "fields": ("cash_discount_enabled", "cash_discount_percent"),
                "description": "Configura pago en efectivo y porcentaje de descuento.",
            },
        ),
    )

    @admin.display(description="Pago en efectivo")
    def pago_efectivo_activo(self, obj):
        return "Habilitado" if obj.cash_discount_enabled else "Deshabilitado"

    @admin.display(description="Descuento efectivo")
    def descuento_efectivo(self, obj):
        return f"{obj.cash_discount_percent}%"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteConfig.get()
        change_url = reverse("admin:core_paymentsettings_change", args=[obj.pk])
        return redirect(change_url)


@admin.register(EmailSubscription)
class EmailSubscriptionAdmin(ModelAdmin):
    list_display = ("email", "is_active", "subscribed_at")
    list_filter = ("is_active",)
    search_fields = ("email",)
    list_editable = ("is_active",)

    def has_add_permission(self, request):
        return False


@admin.register(ContactMessage)
class ContactMessageAdmin(ModelAdmin):
    list_display = ("name", "email", "read", "created_at")
    list_filter = ("read",)
    search_fields = ("name", "email", "message")
    list_editable = ("read",)
    readonly_fields = ("name", "email", "message", "created_at")

    def has_add_permission(self, request):
        return False
