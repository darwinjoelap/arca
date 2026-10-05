from django.contrib import admin

from .models import TasaCambio


@admin.register(TasaCambio)
class TasaCambioAdmin(admin.ModelAdmin):
    list_display = ["fecha", "fuente", "valor", "cargada_por", "creada_en"]
    list_filter = ["fuente"]
    date_hierarchy = "fecha"
    autocomplete_fields = ["cargada_por"]

    def save_model(self, request, obj, form, change):
        if not change:
            obj.cargada_por = request.user
        super().save_model(request, obj, form, change)
