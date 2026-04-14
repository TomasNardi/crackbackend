from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.db.models import Sum
from django.utils.html import format_html
from ckeditor.widgets import CKEditorWidget
from unfold.admin import ModelAdmin
from .models import SiteConfig, PaymentSettings, EmailSubscription, EmailCampaign, ExchangeRate, ContactMessage


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
    readonly_fields = ("subscribed_at",)

    def has_add_permission(self, request):
        return False


class EmailCampaignAdminForm(forms.ModelForm):
    contenido = forms.CharField(
        label="Contenido del email",
        widget=CKEditorWidget(config_name="default"),
        help_text="Puedes usar {{email}} como variable para personalización.",
    )

    class Meta:
        model = EmailCampaign
        fields = "__all__"


@admin.register(EmailCampaign)
class EmailCampaignAdmin(ModelAdmin):
    """Admin para gestionar campañas de email masivo"""

    form = EmailCampaignAdminForm
    change_list_template = "admin/core/emailcampaign/change_list.html"

    list_display = (
        "asunto",
        "status_badge",
        "cantidad_enviados",
        "cantidad_fallidos",
        "fecha_creacion",
        "creado_por",
        "quick_send_button",
    )
    list_filter = ("status", "fecha_creacion", "creado_por")
    search_fields = ("asunto", "contenido")
    readonly_fields = (
        "status_badge",
        "cantidad_enviados",
        "cantidad_fallidos",
        "fecha_creacion",
        "fecha_envio",
        "creado_por",
        "preview_html",
    )
    actions = ["send_campaign"]

    fieldsets = (
        ('Información Básica', {
            'fields': ('asunto', 'status_badge', 'contenido')
        }),
        ('Imagen (opcional)', {
            'fields': ('imagen_url',),
            'description': 'URL de una imagen para incluir en el email (ej: banner, oferta)'
        }),
        ('Vista previa', {
            'fields': ('preview_html',),
            'description': 'Previsualiza cómo verá el suscriptor el email antes de enviarlo.'
        }),
        ('Estadísticas', {
            'classes': ('collapse',),
            'fields': ('cantidad_enviados', 'cantidad_fallidos', 'fecha_envio')
        }),
        ('Sistema', {
            'classes': ('collapse',),
            'fields': ('creado_por', 'fecha_creacion')
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:campaign_id>/send-now/",
                self.admin_site.admin_view(self.send_now_view),
                name="core_emailcampaign_send_now",
            )
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        queryset = EmailCampaign.objects.all()
        totals = queryset.aggregate(
            total_enviados=Sum("cantidad_enviados"),
            total_fallidos=Sum("cantidad_fallidos"),
        )

        total_campaigns = queryset.count()
        borradores = queryset.filter(status="borrador").count()
        enviadas = queryset.filter(status="enviado").count()

        total_enviados = totals.get("total_enviados") or 0
        total_fallidos = totals.get("total_fallidos") or 0
        total_intentos = total_enviados + total_fallidos
        tasa_entrega = round((total_enviados / total_intentos) * 100, 2) if total_intentos else 0

        metrics = {
            "total_campaigns": total_campaigns,
            "borradores": borradores,
            "enviadas": enviadas,
            "total_enviados": total_enviados,
            "total_fallidos": total_fallidos,
            "tasa_entrega": tasa_entrega,
        }

        extra_context = extra_context or {}
        extra_context["campaign_metrics"] = metrics
        return super().changelist_view(request, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        """Asignar usuario que crea la campaña"""
        if not change:  # Si es nueva
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)

    def status_badge(self, obj):
        """Mostrar estado con colores"""
        if not obj:
            return "Borrador"

        colors = {
            'borrador': '#999999',
            'enviando': '#FF9800',
            'enviado': '#4CAF50',
            'cancelado': '#F44336',
        }
        color = colors.get(obj.status, '#999999')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = "Estado"

    def quick_send_button(self, obj):
        if obj.status != "borrador":
            return "-"

        send_url = reverse("admin:core_emailcampaign_send_now", args=[obj.pk])
        return format_html(
            '<a class="button" href="{}" style="background:#1f7a8c;color:#fff;padding:6px 10px;border-radius:6px;">Enviar ahora</a>',
            send_url,
        )
    quick_send_button.short_description = "Acción rápida"

    def send_now_view(self, request, campaign_id):
        from django_q.tasks import async_task
        from django.contrib import messages

        try:
            campaign = EmailCampaign.objects.get(pk=campaign_id)
        except EmailCampaign.DoesNotExist:
            self.message_user(request, "La campaña no existe.", messages.ERROR)
            return HttpResponseRedirect(reverse("admin:core_emailcampaign_changelist"))

        if campaign.status != "borrador":
            self.message_user(
                request,
                "Solo se pueden enviar campañas en estado Borrador.",
                messages.WARNING,
            )
            return HttpResponseRedirect(reverse("admin:core_emailcampaign_change", args=[campaign_id]))

        async_task("apps.core.tasks.send_email_campaign", campaign.id)
        self.message_user(
            request,
            f"Campaña '{campaign.asunto}' encolada para envío.",
            messages.SUCCESS,
        )
        return HttpResponseRedirect(reverse("admin:core_emailcampaign_change", args=[campaign_id]))

    def preview_html(self, obj):
        if not obj.pk:
            return "Guarda la campaña para habilitar la vista previa."

        body = (obj.contenido or "").replace("{{email}}", "cliente@ejemplo.com")
        image_html = ""
        if obj.imagen_url:
            image_html = (
                f'<img src="{obj.imagen_url}" alt="Imagen campaña" '
                'style="display:block;max-width:100%;height:auto;border-radius:8px;margin-bottom:16px;">'
            )

        preview = f"""
            <div style=\"max-width:680px;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:24px;\">
                <h3 style=\"margin:0 0 12px 0;font-size:20px;\">{obj.asunto}</h3>
                {image_html}
                <div>{body}</div>
            </div>
        """
        return format_html(preview)
    preview_html.short_description = "Preview"

    def send_campaign(self, request, queryset):
        """Acción para enviar las campañas seleccionadas de forma asincrónica"""
        from django_q.tasks import async_task
        from django.contrib import messages
        
        campaigns_to_send = queryset.filter(status='borrador')
        
        if not campaigns_to_send.exists():
            self.message_user(
                request,
                "Solo se pueden enviar campañas en estado 'Borrador'.",
                messages.WARNING
            )
            return
        
        for campaign in campaigns_to_send:
            try:
                # Disparar tarea asincrónica sin bloquear la solicitud HTTP
                async_task('apps.core.tasks.send_email_campaign', campaign.id)
                self.message_user(
                    request,
                    f"✓ Campaña '{campaign.asunto}' encolada para envío. Se procesará en segundo plano.",
                    messages.SUCCESS
                )
            except Exception as e:
                self.message_user(
                    request,
                    f"✗ Error encolando campaña '{campaign.asunto}': {str(e)}",
                    messages.ERROR
                )

    send_campaign.short_description = "📧 Enviar campaña seleccionada"


@admin.register(ContactMessage)
class ContactMessageAdmin(ModelAdmin):
    list_display = ("name", "email", "read", "created_at")
    list_filter = ("read",)
    search_fields = ("name", "email", "message")
    list_editable = ("read",)
    readonly_fields = ("name", "email", "message", "created_at")

    def has_add_permission(self, request):
        return False
