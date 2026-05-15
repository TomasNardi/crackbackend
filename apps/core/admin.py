import json
import re
from django import forms
from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.shortcuts import redirect
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import path, reverse
from django.db.models import Q, Sum
from django.utils.html import format_html
from ckeditor.widgets import CKEditorWidget
from unfold.admin import ModelAdmin
from .emails import send_sale_request_status_email
from .models import (
    SiteConfig,
    PaymentSettings,
    EmailSubscription,
    EmailCampaign,
    ExchangeRate,
    ContactMessage,
    SolicitudVenta,
    NotificationRecipient,
    EmailDelivery,
)


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
    list_display = ("estado_sitio", "banner_superior", "maintenance_message")
    fieldsets = (
        (
            "Configuración general",
            {
                "fields": ("is_active", "maintenance_message", "show_top_banner", "top_banner_message"),
                "description": "Controla estado del sitio y mensaje de mantenimiento.",
            },
        ),
    )

    @admin.display(description="Estado")
    def estado_sitio(self, obj):
        return "Activo" if obj.is_active else "Mantenimiento"

    @admin.display(description="Banner superior")
    def banner_superior(self, obj):
        return "Visible" if obj.show_top_banner else "Oculto"

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
                "metrics-live/",
                self.admin_site.admin_view(self.metrics_live_view),
                name="core_emailcampaign_metrics_live",
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

    def _build_campaign_metrics(self):
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
        enviando = queryset.filter(status="enviando").count()

        return {
            "total_campaigns": total_campaigns,
            "borradores": borradores,
            "enviadas": enviadas,
            "enviando": enviando,
            "total_enviados": total_enviados,
            "total_fallidos": total_fallidos,
            "tasa_entrega": tasa_entrega,
        }

    def changelist_view(self, request, extra_context=None):
        metrics = self._build_campaign_metrics()

        extra_context = extra_context or {}
        extra_context["campaign_metrics"] = metrics
        return super().changelist_view(request, extra_context=extra_context)

    def metrics_live_view(self, request):
        return JsonResponse(self._build_campaign_metrics())

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
        send_url = reverse("admin:core_emailcampaign_send_now", args=[obj.pk])
        return format_html(
            '<a href="{}" style="background:#C8972E;color:#fff;padding:5px 10px;border-radius:6px;font-size:11px;font-weight:600;text-decoration:none;">▶ Enviar</a>',
            send_url,
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


@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(ModelAdmin):
    list_display = ("email", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("email", "name")
    list_editable = ("is_active",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            None,
            {
                "fields": ("email", "name", "is_active"),
                "description": (
                    "Cada destinatario recibe las notificaciones internas (nuevas órdenes, "
                    "solicitudes de venta). Desactivá uno con el checkbox para dejar de "
                    "enviarle sin borrar el registro."
                ),
            },
        ),
        (
            "Metadatos",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(EmailDelivery)
class EmailDeliveryAdmin(ModelAdmin):
    _RESERVATION_CODE_RE = re.compile(r"\b([ABCDEFGHJKMNPQRSTUVWXYZ23456789]{6,8})\b")

    list_display = (
        "last_received_at",
        "status_badge",
        "order_column",
        "reservation_code",
        "subject",
        "milestones",
        "email_id_short",
    )
    list_filter = ("status", "last_received_at")
    search_fields = ("to_email", "from_email", "subject", "email_id")
    search_help_text = "Buscar por código de reserva (ej: A9K3X2), asunto o email ID."
    date_hierarchy = "last_received_at"
    readonly_fields = (
        "email_id",
        "to_email",
        "from_email",
        "subject",
        "status",
        "sent_at",
        "delivery_delayed_at",
        "delivered_at",
        "opened_at",
        "clicked_at",
        "bounced_at",
        "complained_at",
        "failed_at",
        "bounce_reason",
        "failure_reason",
        "first_received_at",
        "last_received_at",
        "last_event_at",
        "processed_event_ids",
        "last_payload_pretty",
    )
    fieldsets = (
        (
            "Resumen",
            {
                "fields": (
                    "status",
                    "to_email",
                    "from_email",
                    "subject",
                    "email_id",
                ),
            },
        ),
        (
            "Línea de tiempo",
            {
                "fields": (
                    "sent_at",
                    "delivery_delayed_at",
                    "delivered_at",
                    "opened_at",
                    "clicked_at",
                    "bounced_at",
                    "complained_at",
                    "failed_at",
                ),
            },
        ),
        (
            "Errores",
            {
                "fields": ("bounce_reason", "failure_reason"),
                "classes": ("collapse",),
            },
        ),
        (
            "Metadatos",
            {
                "fields": (
                    "first_received_at",
                    "last_received_at",
                    "last_event_at",
                    "processed_event_ids",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Último payload",
            {
                "fields": ("last_payload_pretty",),
                "classes": ("collapse",),
            },
        ),
    )

    _STATUS_COLORS = {
        EmailDelivery.Status.SENT: "#6B7280",
        EmailDelivery.Status.DELIVERY_DELAYED: "#D4A017",
        EmailDelivery.Status.DELIVERED: "#228B5A",
        EmailDelivery.Status.OPENED: "#2563EB",
        EmailDelivery.Status.CLICKED: "#0EA5E9",
        EmailDelivery.Status.COMPLAINED: "#7C3AED",
        EmailDelivery.Status.BOUNCED: "#D14343",
        EmailDelivery.Status.FAILED: "#991B1B",
    }

    def _get_orders_by_code(self):
        if hasattr(self, "_orders_by_code_cache"):
            return self._orders_by_code_cache

        from apps.orders.models import Order

        self._orders_by_code_cache = {
            (order.order_code or "").upper(): order
            for order in Order.objects.only("id", "order_code", "customer_email")
            if order.order_code
        }
        return self._orders_by_code_cache

    def _extract_reservation_code(self, subject):
        subject_value = (subject or "").upper()
        orders_by_code = self._get_orders_by_code()
        for candidate in self._RESERVATION_CODE_RE.findall(subject_value):
            if candidate in orders_by_code:
                return candidate
        return ""

    def _resolve_order_for_delivery(self, obj):
        if hasattr(obj, "_resolved_order_cache"):
            return obj._resolved_order_cache

        reservation_code = self._extract_reservation_code(obj.subject)
        order = None
        if reservation_code:
            candidate = self._get_orders_by_code().get(reservation_code)
            if candidate and (candidate.customer_email or "").strip().lower() == (obj.to_email or "").strip().lower():
                order = candidate

        obj._resolved_order_cache = order
        obj._reservation_code_cache = reservation_code
        return order

    def _is_campaign_delivery(self, obj):
        payload = obj.last_payload or {}
        if not isinstance(payload, dict):
            return False

        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return False

        headers = data.get("headers") or {}
        if isinstance(headers, dict):
            x_entity = headers.get("X-Entity-Ref-ID") or headers.get("x-entity-ref-id") or ""
            return str(x_entity).lower().startswith("campaign-")
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        from apps.orders.models import Order

        customer_emails = {
            (email or "").strip().lower()
            for email in Order.objects.exclude(customer_email="").values_list("customer_email", flat=True)
            if email
        }
        internal_emails = {
            (email or "").strip().lower()
            for email in NotificationRecipient.objects.exclude(email="").values_list("email", flat=True)
            if email
        }

        purchase_subject_filter = (
            Q(subject__icontains="pedido")
            | Q(subject__icontains="devolucion de compra")
            | Q(subject__icontains="devolución de compra")
            | Q(subject__icontains="tu compra está en camino")
            | Q(subject__icontains="tu compra esta en camino")
        )

        queryset = (
            queryset
            .filter(to_email__in=customer_emails)
            .exclude(to_email__in=internal_emails)
            .exclude(subject__icontains="nueva orden")
            .filter(purchase_subject_filter)
        )

        non_campaign_ids = [
            item.id for item in queryset.only("id", "last_payload")
            if not self._is_campaign_delivery(item)
        ]
        return queryset.filter(id__in=non_campaign_ids)

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)

        term = (search_term or "").strip().upper()
        if not term:
            return queryset, use_distinct

        from apps.orders.models import Order

        order = Order.objects.filter(order_code__iexact=term).only("order_code", "customer_email").first()
        if order:
            code_queryset = self.get_queryset(request).filter(
                to_email__iexact=(order.customer_email or "").strip()
            ).filter(
                Q(subject__icontains=order.order_code)
                | Q(subject__icontains="tu compra está en camino")
                | Q(subject__icontains="tu compra esta en camino")
            )
            queryset = queryset | code_queryset
            use_distinct = True

        return queryset, use_distinct

    @admin.display(description="Estado", ordering="status")
    def status_badge(self, obj):
        color = self._STATUS_COLORS.get(obj.status, "#999999")
        return format_html(
            '<span style="background-color:{};color:#fff;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;letter-spacing:.04em;">{}</span>',
            color,
            obj.get_status_display(),
        )

    @admin.display(description="Hitos")
    def milestones(self, obj):
        chips = []
        spec = [
            ("Env", obj.sent_at, "#6B7280"),
            ("Entr", obj.delivered_at, "#228B5A"),
            ("Abr", obj.opened_at, "#2563EB"),
            ("Clk", obj.clicked_at, "#0EA5E9"),
            ("Bnc", obj.bounced_at, "#D14343"),
            ("Spam", obj.complained_at, "#7C3AED"),
        ]
        for label, ts, color in spec:
            if not ts:
                continue
            chips.append(
                f'<span style="display:inline-block;background:{color};color:#fff;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:600;margin-right:4px;">{label}</span>'
            )
        return format_html("".join(chips)) if chips else "—"

    @admin.display(description="Orden")
    def order_column(self, obj):
        order = self._resolve_order_for_delivery(obj)
        if not order:
            return "—"

        url = reverse("admin:orders_order_change", args=[order.pk])
        return format_html('<a href="{}">#{}</a>', url, order.order_code)

    @admin.display(description="Codigo reserva")
    def reservation_code(self, obj):
        self._resolve_order_for_delivery(obj)
        return getattr(obj, "_reservation_code_cache", "") or "—"

    @admin.display(description="Email ID")
    def email_id_short(self, obj):
        if not obj.email_id:
            return "—"
        short = obj.email_id[:8]
        return format_html('<code style="font-size:11px;">{}…</code>', short)

    @admin.display(description="Último payload")
    def last_payload_pretty(self, obj):
        try:
            formatted = json.dumps(obj.last_payload or {}, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            formatted = str(obj.last_payload or "")
        return format_html(
            '<pre style="background:#0f172a;color:#e2e8f0;padding:14px 18px;border-radius:8px;font-size:12px;line-height:1.5;max-height:420px;overflow:auto;">{}</pre>',
            formatted,
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SolicitudVenta)
class SolicitudVentaAdmin(ModelAdmin):
    list_display = (
        "nombre_completo",
        "email",
        "celular",
        "tipo_coleccion_admin",
        "estado_badge",
        "fecha_creacion",
        "imagenes_admin",
    )
    list_filter = ("estado", "tipo_coleccion", "fecha_creacion")
    search_fields = ("nombre_completo", "email", "celular")
    readonly_fields = ("fecha_creacion", "imagenes_preview")
    actions = ("marcar_como_rechazado", "marcar_como_aceptado")
    fieldsets = (
        (
            "Datos de la solicitud",
            {
                "fields": (
                    "nombre_completo",
                    "email",
                    "celular",
                    "tipo_coleccion",
                    "estado",
                    "fecha_creacion",
                ),
            },
        ),
        (
            "Imágenes",
            {
                "fields": ("imagenes_preview",),
            },
        ),
    )

    @admin.display(description="Tipo de colección")
    def tipo_coleccion_admin(self, obj):
        return obj.get_tipo_coleccion_display()

    @admin.display(description="Estado")
    def estado_badge(self, obj):
        colors = {
            SolicitudVenta.Estado.PENDIENTE: "#D4A017",
            SolicitudVenta.Estado.RECHAZADO: "#D14343",
            SolicitudVenta.Estado.ACEPTADO: "#228B5A",
        }
        color = colors.get(obj.estado, "#999999")
        return format_html(
            '<span style="background-color:{};color:#fff;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600;letter-spacing:.04em;">{}</span>',
            color,
            obj.get_estado_display(),
        )

    @admin.display(description="Imágenes")
    def imagenes_admin(self, obj):
        count = len(obj.imagenes or [])
        if count == 0:
            return "Sin imágenes"
        return format_html("<span>{} imagen(es)</span>", count)

    @admin.display(description="Vista previa de imágenes")
    def imagenes_preview(self, obj):
        if not obj or not obj.imagenes:
            return "Sin imágenes cargadas"

        previews = []
        for image in obj.imagenes:
            secure_url = image.get("secure_url", "")
            if not secure_url:
                continue
            previews.append(
                format_html(
                    '<a href="{}" target="_blank" rel="noreferrer" style="display:inline-block;margin:0 12px 12px 0;text-align:center;text-decoration:none;color:#1A1A1A;">'
                    '<img src="{}" alt="Imagen" style="width:110px;height:110px;object-fit:cover;border-radius:10px;border:1px solid #E8E4DD;display:block;margin-bottom:8px;" />'
                    '<span style="font-size:12px;">Abrir</span>'
                    '</a>',
                    secure_url,
                    secure_url,
                )
            )
        return format_html("".join(str(item) for item in previews)) if previews else "Sin imágenes válidas"

    def has_add_permission(self, request):
        return False

    def has_module_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return False

    def marcar_como_rechazado(self, request, queryset):
        from django.contrib import messages

        updated = 0
        for solicitud in queryset.exclude(estado=SolicitudVenta.Estado.RECHAZADO):
            solicitud.estado = SolicitudVenta.Estado.RECHAZADO
            solicitud.save(update_fields=["estado"])
            send_sale_request_status_email(solicitud.id)
            updated += 1

        self.message_user(request, f"{updated} solicitud(es) marcadas como rechazadas.", messages.SUCCESS)

    marcar_como_rechazado.short_description = "Marcar como Rechazado"

    def marcar_como_aceptado(self, request, queryset):
        from django.contrib import messages

        updated = 0
        for solicitud in queryset.exclude(estado=SolicitudVenta.Estado.ACEPTADO):
            solicitud.estado = SolicitudVenta.Estado.ACEPTADO
            solicitud.save(update_fields=["estado"])
            send_sale_request_status_email(solicitud.id)
            updated += 1

        self.message_user(request, f"{updated} solicitud(es) marcadas como aceptadas.", messages.SUCCESS)

    marcar_como_aceptado.short_description = "Marcar como Aceptado"


# Feature toggled off: keep code/data but remove models from Django admin UI.
for _model in (SolicitudVenta,):
    try:
        admin.site.unregister(_model)
    except NotRegistered:
        pass
