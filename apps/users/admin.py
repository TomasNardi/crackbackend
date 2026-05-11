from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin

from .models import User


class GroupAdminForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        permissions_field = self.fields.get("permissions")
        if permissions_field is not None:
            permissions_field.help_text = (
                "Selecciona permisos y usa las flechas para moverlos."
            )
            permissions_field.widget.attrs.update({"size": 24})


try:
    admin.site.unregister(Group)
except admin.sites.NotRegistered:
    pass


@admin.register(Group)
class GroupAdmin(ModelAdmin, BaseGroupAdmin):
    form = GroupAdminForm
    change_form_template = "admin/auth/group/change_form.html"

    class Media:
        css = {
            "all": ("admin/css/group_admin.css",),
        }


@admin.register(User)
class UserAdmin(ModelAdmin, BaseUserAdmin):
    list_display = ("email", "username", "is_staff", "is_collector", "date_joined")
    list_filter = ("is_staff", "is_collector", "is_active")
    search_fields = ("email", "username")
    ordering = ("-date_joined",)

    fieldsets = (
        (None, {"fields": ("email", "username", "password")} ),
        ("Información personal", {"fields": ("first_name", "last_name", "phone", "default_address", "default_city", "default_province", "default_zip")} ),
        ("Permisos", {"fields": ("is_active", "is_staff", "is_superuser", "is_collector", "groups", "user_permissions")} ),
        ("Fechas", {"fields": ("last_login", "date_joined")} ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "username", "password1", "password2", "is_active", "is_staff", "is_superuser"),
            },
        ),
    )
