import types

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import RegistroAuditoria, Usuario


def _solo_superusuario(self, request):
    """El panel de Django (/admin/) es el panel de plataforma: solo para el
    superadmin. Los directores administran su organización desde
    /organizacion/configuracion/."""
    return request.user.is_active and request.user.is_superuser


admin.site.has_permission = types.MethodType(_solo_superusuario, admin.site)
admin.site.site_header = "Arca — Plataforma"
admin.site.site_title = "Arca"
admin.site.index_title = "Panel de plataforma"


@admin.register(Usuario)
class UsuarioAdmin(DjangoUserAdmin):
    list_display = ["username", "first_name", "last_name", "is_active", "is_superuser", "debe_cambiar_clave"]
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Arca", {"fields": ["telefono", "debe_cambiar_clave"]}),
    )


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = ["fecha", "organizacion", "usuario", "accion", "modelo", "objeto_id"]
    list_filter = ["accion", "organizacion"]
    search_fields = ["modelo", "objeto_id", "descripcion"]
    date_hierarchy = "fecha"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
