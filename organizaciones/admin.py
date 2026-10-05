"""Panel de plataforma (/admin/), solo para el superadmin.

Aquí se dan de alta las organizaciones, se nombra o traspasa al director y se
decide `director_ve_cuentas_personales`. El director administra el resto
desde /organizacion/configuracion/.
"""

from django.contrib import admin, messages

from core.auditoria import registrar
from core.models import RegistroAuditoria

from .models import Ejercicio, Membresia, Organizacion, TipoMiembro
from .services import slug_disponible


class MembresiaInline(admin.TabularInline):
    model = Membresia
    extra = 0
    fields = ["user", "nombre_visible", "es_dueno", "es_administrador", "tipo", "activa"]
    autocomplete_fields = ["user"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # El tipo se limita a los de la organización que se está editando.
        if db_field.name == "tipo":
            organizacion_id = request.resolver_match.kwargs.get("object_id")
            kwargs["queryset"] = TipoMiembro.objects.filter(organizacion_id=organizacion_id or 0)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Organizacion)
class OrganizacionAdmin(admin.ModelAdmin):
    list_display = ["nombre", "director_nombre", "total_miembros", "director_ve_cuentas_personales", "activa", "creada_en"]
    list_editable = ["director_ve_cuentas_personales", "activa"]
    list_filter = ["activa", "director_ve_cuentas_personales"]
    search_fields = ["nombre", "slug", "rif"]
    readonly_fields = ["creada_en"]
    inlines = [MembresiaInline]
    fieldsets = [
        (None, {"fields": ["nombre", "slug", "activa", "creada_en"]}),
        ("Decisiones de plataforma", {
            "fields": ["director_ve_cuentas_personales"],
            "description": "Lo decide el superadmin, no la organización. El miembro ve en su cuenta "
            "un aviso que dice si el director puede ver sus montos.",
        }),
        ("Datos (los puede editar el director)", {
            "fields": ["rif", "direccion", "telefono", "email", "moneda_base", "requiere_aprobacion_egresos"],
        }),
    ]

    @admin.display(description="Director")
    def director_nombre(self, obj):
        director = obj.director
        return f"{director.nombre} ({director.usuario_texto})" if director else "— sin director —"

    @admin.display(description="Miembros activos")
    def total_miembros(self, obj):
        return obj.membresias.filter(activa=True).count()

    def get_changeform_initial_data(self, request):
        return {"moneda_base": "USD"}

    def get_prepopulated_fields(self, request, obj=None):
        return {} if obj else {"slug": ["nombre"]}

    def save_model(self, request, obj, form, change):
        """Se usa tanto en el formulario como en la edición desde la lista
        (list_editable), así que el cambio de visibilidad siempre queda anotado."""
        if not obj.slug:
            obj.slug = slug_disponible(obj.nombre)
        anterior = Organizacion.objects.filter(pk=obj.pk).first() if change else None
        super().save_model(request, obj, form, change)

        if not change:
            registrar(request, RegistroAuditoria.Accion.CREAR_ORGANIZACION, modelo="Organizacion",
                      objeto_id=obj.pk, descripcion=obj.nombre, organizacion=obj)
        elif anterior and anterior.director_ve_cuentas_personales != obj.director_ve_cuentas_personales:
            estado = "ENCENDIDA" if obj.director_ve_cuentas_personales else "APAGADA"
            registrar(
                request, RegistroAuditoria.Accion.VISIBILIDAD_CUENTAS, modelo="Organizacion", objeto_id=obj.pk,
                descripcion=f"Visibilidad de cuentas personales para el director: {estado}", organizacion=obj,
            )
            messages.info(request, f"{obj.nombre}: visibilidad de cuentas personales {estado.lower()}. Quedó en la bitácora.")

    def has_delete_permission(self, request, obj=None):
        # Una organización no se borra: se desactiva. Así no se pierde su historia.
        return False


@admin.register(Membresia)
class MembresiaAdmin(admin.ModelAdmin):
    list_display = ["user", "organizacion", "rol_visible", "activa"]
    list_filter = ["organizacion", "es_dueno", "es_administrador", "activa"]
    search_fields = ["user__username", "nombre_visible", "organizacion__nombre"]
    autocomplete_fields = ["user", "organizacion"]


@admin.register(TipoMiembro)
class TipoMiembroAdmin(admin.ModelAdmin):
    list_display = ["nombre", "organizacion", "activo"]
    list_filter = ["organizacion", "activo"]
    search_fields = ["nombre"]


@admin.register(Ejercicio)
class EjercicioAdmin(admin.ModelAdmin):
    list_display = ["nombre", "organizacion", "fecha_inicio", "fecha_fin", "activo", "cerrado"]
    list_filter = ["organizacion", "activo", "cerrado"]
