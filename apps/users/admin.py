from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Wishlist, WishlistItem


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "username", "is_staff", "is_collector", "date_joined")
    list_filter = ("is_staff", "is_collector", "is_active")
    search_fields = ("email", "username")
    ordering = ("-date_joined",)

    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "Datos adicionales",
            {
                "fields": (
                    "phone",
                    "default_address",
                    "default_city",
                    "default_province",
                    "default_zip",
                    "is_collector",
                )
            },
        ),
    )


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at")
    raw_id_fields = ("user",)


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ("wishlist", "product", "added_at")
    raw_id_fields = ("wishlist", "product")
