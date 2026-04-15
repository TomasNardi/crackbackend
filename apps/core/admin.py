import json
from django import forms
from django.contrib import admin
from django.shortcuts import redirect
from django.http import HttpResponseRedirect, JsonResponse
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
    change_form_template = "admin/core/emailcampaign/change_form.html"

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
            ),
            path(
                "preview-ajax/",
                self.admin_site.admin_view(self.preview_ajax),
                name="core_emailcampaign_preview_ajax",
            ),
            path(
                "queue-status/",
                self.admin_site.admin_view(self.queue_status_view),
                name="core_emailcampaign_queue_status",
            ),
            path(
                "<int:campaign_id>/send-sync/",
                self.admin_site.admin_view(self.send_sync_view),
                name="core_emailcampaign_send_sync",
            ),
        ]
        return custom_urls + urls

    # ------------------------------------------------------------------
    # AJAX endpoint — devuelve el HTML del preview en tiempo real
    # ------------------------------------------------------------------
    def preview_ajax(self, request):
        """
        POST /admin/core/emailcampaign/preview-ajax/
        Body JSON: { asunto, contenido, imagen_url }
        Returns: { html: "..." }
        """
        if request.method != "POST":
            return JsonResponse({"error": "Method not allowed"}, status=405)

        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            data = {}

        asunto = data.get("asunto", "(sin asunto)")
        contenido = data.get("contenido", "")
        imagen_url = data.get("imagen_url", "")

        from .tasks import _build_preview_html
        html = _build_preview_html(
            asunto=asunto,
            contenido=contenido,
            imagen_url=imagen_url,
            recipient_email="suscriptor@ejemplo.com",
        )
        return JsonResponse({"html": html})

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
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)

    def status_badge(self, obj):
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
            '<span style="background-color:{};color:#fff;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;letter-spacing:.04em;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = "Estado"

    def quick_send_button(self, obj):
        if obj.status != "borrador":
            return "-"
        send_url  = reverse("admin:core_emailcampaign_send_now",  args=[obj.pk])
        sync_url  = reverse("admin:core_emailcampaign_send_sync", args=[obj.pk])
        queue_url = reverse("admin:core_emailcampaign_queue_status")
        return format_html(
            '<a href="{}" style="background:#C8972E;color:#fff;padding:5px 10px;border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;margin-right:4px;">▶ Async</a>'
            '<a href="{}" style="background:#1e40af;color:#fff;padding:5px 10px;border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;margin-right:4px;" title="Envío directo sin worker">⚡ Sync</a>'
            '<a href="{}" style="background:#374151;color:#fff;padding:5px 10px;border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;" title="Ver estado de la cola">🔍</a>',
            send_url, sync_url, queue_url,
        )
    quick_send_button.short_description = "Acciones"

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
            f"✓ Campaña '{campaign.asunto}' encolada. Se procesará en segundo plano.",
            messages.SUCCESS,
        )
        return HttpResponseRedirect(reverse("admin:core_emailcampaign_change", args=[campaign_id]))

    def queue_status_view(self, request):
        """
        GET /admin/core/emailcampaign/queue-status/
        Muestra el estado real de la cola de Django Q en la DB.
        """
        from django.http import HttpResponse
        from django_q.models import OrmQ, Success, Failure

        queued   = OrmQ.objects.count()
        success  = Success.objects.order_by("-stopped")[:10]
        failures = Failure.objects.order_by("-stopped")[:10]

        lines = [
            "<h2 style='font-family:monospace'>Django Q — Estado de la cola</h2>",
            f"<p><strong>Tareas en cola (pendientes):</strong> {queued}</p>",
            "<hr>",
            "<h3>Últimas 10 exitosas:</h3>",
            "<ul style='font-family:monospace;font-size:13px'>",
        ]
        for t in success:
            lines.append(f"<li>✅ {t.name} — {t.stopped} — resultado: {str(t.result)[:100]}</li>")
        if not success:
            lines.append("<li>Sin tareas exitosas aún</li>")
        lines += ["</ul>", "<h3>Últimas 10 fallidas:</h3>", "<ul style='font-family:monospace;font-size:13px'>"]
        for t in failures:
            lines.append(f"<li>❌ {t.name} — {t.stopped} — error: {str(t.result)[:200]}</li>")
        if not failures:
            lines.append("<li>Sin tareas fallidas</li>")
        lines.append("</ul>")
        lines.append("<p><a href='javascript:location.reload()'>↻ Actualizar</a> &nbsp; <a href='../'>← Volver</a></p>")

        return HttpResponse("\n".join(lines))

    def send_sync_view(self, request, campaign_id):
        """
        Envío SÍNCRONO de emergencia — sin worker, directo en el request.
        Usar solo si el worker no está disponible. Timeout de gunicorn aplica.
        """
        from django.contrib import messages
        from .tasks import send_email_campaign

        try:
            campaign = EmailCampaign.objects.get(pk=campaign_id)
        except EmailCampaign.DoesNotExist:
            self.message_user(request, "La campaña no existe.", messages.ERROR)
            return HttpResponseRedirect(reverse("admin:core_emailcampaign_changelist"))

        if campaign.status != "borrador":
            self.message_user(request, "Solo se pueden enviar campañas en estado Borrador.", messages.WARNING)
            return HttpResponseRedirect(reverse("admin:core_emailcampaign_change", args=[campaign_id]))

        try:
            result = send_email_campaign(campaign.id)
            self.message_user(
                request,
                f"✓ Enviado directamente: {result.get('exitosos', 0)} exitosos, {result.get('fallidos', 0)} fallidos.",
                messages.SUCCESS,
            )
        except Exception as e:
            self.message_user(request, f"✗ Error: {e}", messages.ERROR)

        return HttpResponseRedirect(reverse("admin:core_emailcampaign_change", args=[campaign_id]))

    def send_campaign(self, request, queryset):
        from django_q.tasks import async_task
        from django.contrib import messages

        campaigns_to_send = queryset.filter(status='borrador')
        if not campaigns_to_send.exists():
            self.message_user(request, "Solo se pueden enviar campañas en estado 'Borrador'.", messages.WARNING)
            return

        for campaign in campaigns_to_send:
            try:
                async_task('apps.core.tasks.send_email_campaign', campaign.id)
                self.message_user(request, f"✓ '{campaign.asunto}' encolada.", messages.SUCCESS)
            except Exception as e:
                self.message_user(request, f"✗ Error encolando '{campaign.asunto}': {e}", messages.ERROR)

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
