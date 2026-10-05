from django.contrib import admin

from .models import Caja, Concepto, Cuenta, Movimiento

# Solo consulta para soporte: el superadmin no registra ni corrige dinero de
# una organización desde aquí (A-07).


class SoloLecturaAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Caja)
class CajaAdmin(SoloLecturaAdmin):
    list_display = ["nombre", "organizacion", "activa"]
    list_filter = ["organizacion"]


@admin.register(Cuenta)
class CuentaAdmin(SoloLecturaAdmin):
    list_display = ["nombre", "caja", "organizacion", "moneda", "saldo_inicial", "activa"]
    list_filter = ["organizacion", "moneda"]


@admin.register(Concepto)
class ConceptoAdmin(SoloLecturaAdmin):
    list_display = ["nombre", "tipo", "padre", "organizacion", "activo"]
    list_filter = ["organizacion", "tipo"]


@admin.register(Movimiento)
class MovimientoAdmin(SoloLecturaAdmin):
    list_display = ["fecha", "organizacion", "tipo", "numero_vale", "cuenta", "moneda", "monto", "estado"]
    list_filter = ["organizacion", "tipo", "estado"]
    date_hierarchy = "fecha"
