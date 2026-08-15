from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import CardSet, CatalogCard
from .services import images, r2


@admin.register(CardSet)
class CardSetAdmin(ModelAdmin):
    list_display = ("name", "abbreviation", "language", "released_at", "card_count", "is_supplemental")
    list_filter = ("language", "is_supplemental", "tcg")
    search_fields = ("name", "abbreviation")
    readonly_fields = ("external_id", "slug", "imported_at")
    ordering = ("-released_at", "name")

    @admin.display(description="Cartas")
    def card_count(self, obj):
        return obj.cards.count()

    def has_add_permission(self, request):
        # Las expansiones entran por `import_catalog`, no a mano.
        return False


@admin.register(CatalogCard)
class CatalogCardAdmin(ModelAdmin):
    # `search_fields` es lo que habilita el autocomplete de Producto.
    search_fields = ("search_text",)

    list_display = ("thumb", "name", "number", "rarity", "card_set", "image_status")
    list_filter = ("image_status", "card_set__language", "rarity")
    list_display_links = ("thumb", "name")
    readonly_fields = (
        "external_id", "card_set", "name", "number", "rarity", "search_text",
        "source_url", "source_image_url", "extended_data",
        "image_url", "image_url_medium", "image_url_thumb",
        "image_status", "image_error", "preview", "created_at", "updated_at",
    )
    list_select_related = ("card_set",)
    actions = ("action_download_images",)

    @admin.display(description="")
    def thumb(self, obj):
        if not obj.image_url_thumb:
            return "—"
        return format_html(
            '<img src="{}" style="height:56px;border-radius:4px" loading="lazy">',
            obj.image_url_thumb,
        )

    @admin.display(description="Imagen")
    def preview(self, obj):
        if not obj.image_url:
            return "Sin imagen. Usá la acción «Descargar imágenes» o corré sync_catalog_images."
        return format_html('<img src="{}" style="max-width:330px">', obj.image_url)

    def has_add_permission(self, request):
        # El catálogo entra por `import_catalog`, no a mano.
        return False

    def has_change_permission(self, request, obj=None):
        # Es material de referencia: se consulta, no se edita.
        return False

    @admin.action(description="Descargar imágenes de las cartas seleccionadas")
    def action_download_images(self, request, queryset):
        if not r2.is_configured():
            self.message_user(
                request,
                "R2 no está configurado. Cargá las credenciales en .env (ver .env.example).",
                level=messages.ERROR,
            )
            return

        done = failed = 0
        for card in queryset:
            card = images.process_card(card)
            if card.has_image:
                done += 1
            else:
                failed += 1

        self.message_user(
            request,
            f"{done} imágenes listas, {failed} fallidas.",
            level=messages.SUCCESS if not failed else messages.WARNING,
        )
