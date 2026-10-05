from django.contrib import admin

from finanzas.admin import SoloLecturaAdmin

from .models import Presupuesto


@admin.register(Presupuesto)
class PresupuestoAdmin(SoloLecturaAdmin):
    list_display = ["caja", "ejercicio", "organizacion", "moneda", "estado"]
    list_filter = ["organizacion", "estado"]
