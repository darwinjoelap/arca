"""Pantallas de la organización: selección, y la configuración que maneja el
director (datos, tipos de miembro, miembros, ejercicios, bitácora).

Regla de aislamiento: todo objeto se busca SIEMPRE filtrando por
`request.organizacion`. Un pk de otra organización responde 404.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from core.auditoria import registrar
from core.middleware import CLAVE_SESION
from core.mixins import DeLaOrganizacionMixin, PermisoRequeridoMixin, requiere_permiso
from core.models import RegistroAuditoria
from core.utils import eliminar_protegido

from .forms import (
    EjercicioForm,
    MiembroCrearForm,
    MiembroEditarForm,
    OrganizacionForm,
    RestablecerClaveForm,
    TipoMiembroForm,
)
from .models import PERMISOS, Ejercicio, Membresia, TipoMiembro
from .services import usuario_es_exclusivo

Accion = RegistroAuditoria.Accion


# --- Selección de organización ---------------------------------------------


@login_required
def seleccionar(request):
    """Para quien pertenece a más de una organización. La elección se guarda
    en la sesión; el middleware la vuelve a validar en cada petición."""
    membresias = (
        Membresia.objects.filter(user=request.user, activa=True, organizacion__activa=True)
        .select_related("organizacion", "tipo")
        .order_by("organizacion__nombre")
    )
    if request.method == "POST":
        elegida = membresias.filter(organizacion_id=request.POST.get("organizacion")).first()
        if elegida is None:
            raise PermissionDenied("No perteneces a esa organización.")
        request.session[CLAVE_SESION] = elegida.organizacion_id
        return redirect("inicio")
    return render(request, "organizaciones/seleccionar.html", {"membresias": membresias})


# --- Configuración ---------------------------------------------------------


@requiere_permiso()
def configuracion(request):
    organizacion = request.organizacion
    contexto = {
        "total_miembros": Membresia.objects.filter(organizacion=organizacion, activa=True).count(),
        "total_tipos": TipoMiembro.objects.filter(organizacion=organizacion).count(),
        "ejercicio_activo": Ejercicio.objects.filter(organizacion=organizacion, activo=True).first(),
    }
    return render(request, "organizaciones/configuracion.html", contexto)


@requiere_permiso()
def organizacion_editar(request):
    organizacion = request.organizacion
    form = OrganizacionForm(request.POST or None, instance=organizacion)
    if request.method == "POST" and form.is_valid():
        form.save()
        registrar(
            request, Accion.EDITAR_ORGANIZACION, modelo="Organizacion", objeto_id=organizacion.pk,
            descripcion="Campos: " + ", ".join(form.changed_data) if form.changed_data else "Sin cambios",
        )
        messages.success(request, "Datos de la organización actualizados.")
        return redirect("organizaciones:configuracion")
    return render(request, "organizaciones/organizacion_form.html", {"form": form})


# --- Tipos de miembro ------------------------------------------------------


class TipoListView(PermisoRequeridoMixin, DeLaOrganizacionMixin, ListView):
    model = TipoMiembro
    template_name = "organizaciones/tipo_lista.html"
    context_object_name = "tipos"

    def get_queryset(self):
        return super().get_queryset().annotate(
            total_miembros=Count("membresias", filter=Q(membresias__activa=True))
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["permisos"] = PERMISOS
        return ctx


class _TipoFormMixin(PermisoRequeridoMixin, DeLaOrganizacionMixin):
    model = TipoMiembro
    form_class = TipoMiembroForm
    form_con_organizacion = True
    template_name = "organizaciones/tipo_form.html"
    success_url = reverse_lazy("organizaciones:tipo_lista")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["permisos"] = PERMISOS
        return ctx


class TipoCreateView(_TipoFormMixin, CreateView):
    def form_valid(self, form):
        respuesta = super().form_valid(form)
        registrar(self.request, Accion.CREAR_TIPO, modelo="TipoMiembro", objeto_id=self.object.pk,
                  descripcion=f"{self.object.nombre}: {', '.join(self.object.permisos_activos()) or 'sin permisos'}")
        messages.success(self.request, f"Tipo de miembro «{self.object.nombre}» creado.")
        return respuesta


class TipoUpdateView(_TipoFormMixin, UpdateView):
    def form_valid(self, form):
        respuesta = super().form_valid(form)
        registrar(self.request, Accion.EDITAR_TIPO, modelo="TipoMiembro", objeto_id=self.object.pk,
                  descripcion=f"{self.object.nombre}: {', '.join(self.object.permisos_activos()) or 'sin permisos'}")
        messages.success(self.request, f"Tipo de miembro «{self.object.nombre}» actualizado.")
        return respuesta


@requiere_permiso()
@require_POST
def tipo_eliminar(request, pk):
    tipo = get_object_or_404(TipoMiembro, pk=pk, organizacion=request.organizacion)
    nombre, tipo_id = tipo.nombre, tipo.pk
    respuesta = eliminar_protegido(request, tipo, "organizaciones:tipo_lista")
    if not TipoMiembro.objects.filter(pk=tipo_id).exists():
        registrar(request, Accion.ELIMINAR_TIPO, modelo="TipoMiembro", objeto_id=tipo_id, descripcion=nombre)
    return respuesta


# --- Miembros --------------------------------------------------------------


class MiembroListView(PermisoRequeridoMixin, DeLaOrganizacionMixin, ListView):
    model = Membresia
    template_name = "organizaciones/miembro_lista.html"
    context_object_name = "miembros"
    paginate_by = 30

    def get_queryset(self):
        qs = super().get_queryset().select_related("user", "tipo")
        self.q = self.request.GET.get("q", "").strip()
        self.tipo_filtro = self.request.GET.get("tipo", "")
        if self.q:
            qs = qs.filter(Q(nombre_visible__icontains=self.q) | Q(user__username__icontains=self.q))
        if self.tipo_filtro.isdigit():
            qs = qs.filter(tipo_id=int(self.tipo_filtro))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.q
        ctx["tipo_filtro"] = self.tipo_filtro
        ctx["tipos"] = TipoMiembro.objects.filter(organizacion=self.request.organizacion)
        return ctx


def _miembro_editable(request, pk):
    """La membresía `pk` de esta organización, si quien pide puede modificarla.

    - Al director (dueño) no lo modifica nadie desde aquí: el traspaso de la
      dirección lo hace el superadmin.
    - A un administrador solo lo modifica el director."""
    membresia = get_object_or_404(
        Membresia.objects.select_related("user", "tipo"), pk=pk, organizacion=request.organizacion
    )
    actor = request.membresia
    if membresia.es_dueno:
        raise PermissionDenied("El director no se modifica desde esta pantalla.")
    if membresia.es_administrador and not actor.es_dueno:
        raise PermissionDenied("Solo el director puede modificar a un administrador.")
    return membresia


@requiere_permiso()
def miembro_crear(request):
    form = MiembroCrearForm(request.POST or None, organizacion=request.organizacion, actor=request.membresia)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            membresia = form.save()
        registrar(request, Accion.CREAR_MIEMBRO, modelo="Membresia", objeto_id=membresia.pk,
                  descripcion=f"{membresia.nombre} ({membresia.user.username}) — {membresia.rol_visible}")
        messages.success(
            request,
            f"«{membresia.nombre}» agregado con el usuario «{membresia.user.username}». Entrégale la "
            "contraseña temporal directamente; se le pedirá cambiarla al entrar.",
        )
        return redirect("organizaciones:miembro_lista")
    return render(request, "organizaciones/miembro_form.html", {"form": form, "miembro": None})


@requiere_permiso()
def miembro_editar(request, pk):
    membresia = _miembro_editable(request, pk)
    form = MiembroEditarForm(
        request.POST or None, organizacion=request.organizacion, actor=request.membresia, membresia=membresia
    )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
        registrar(request, Accion.EDITAR_MIEMBRO, modelo="Membresia", objeto_id=membresia.pk,
                  descripcion=f"{membresia.nombre} ({membresia.user.username}) — {membresia.rol_visible}")
        messages.success(request, f"«{membresia.nombre}» actualizado.")
        return redirect("organizaciones:miembro_lista")
    return render(request, "organizaciones/miembro_form.html", {"form": form, "miembro": membresia})


@requiere_permiso()
def miembro_restablecer_clave(request, pk):
    membresia = _miembro_editable(request, pk)
    if not usuario_es_exclusivo(membresia.user, request.organizacion):
        # No se dice por qué en detalle: no se revela a qué más pertenece la persona.
        raise PermissionDenied(
            "La contraseña de este usuario no se puede restablecer desde la organización. "
            "Puede usar «¿Olvidaste tu contraseña?» o pedir ayuda al soporte de Arca."
        )
    form = RestablecerClaveForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(membresia.user)
        registrar(request, Accion.RESTABLECER_CLAVE, modelo="Usuario", objeto_id=membresia.user_id,
                  descripcion=membresia.user.username)
        messages.success(
            request,
            f"Contraseña de «{membresia.user.username}» restablecida. Entrégasela directamente; "
            "se le pedirá cambiarla al entrar.",
        )
        return redirect("organizaciones:miembro_lista")
    return render(request, "organizaciones/miembro_restablecer_clave.html", {"form": form, "miembro": membresia})


@requiere_permiso()
@require_POST
def miembro_toggle_activa(request, pk):
    """Activa o desactiva la MEMBRESÍA, no al usuario: la persona puede seguir
    perteneciendo a otras organizaciones."""
    membresia = _miembro_editable(request, pk)
    if membresia.pk == request.membresia.pk:
        raise PermissionDenied("No puedes desactivarte a ti mismo.")
    membresia.activa = not membresia.activa
    membresia.save(update_fields=["activa"])
    registrar(
        request, Accion.ACTIVAR_MIEMBRO if membresia.activa else Accion.DESACTIVAR_MIEMBRO,
        modelo="Membresia", objeto_id=membresia.pk, descripcion=f"{membresia.nombre} ({membresia.user.username})",
    )
    messages.success(request, f"«{membresia.nombre}» {'activado' if membresia.activa else 'desactivado'}.")
    return redirect("organizaciones:miembro_lista")


# --- Ejercicios ------------------------------------------------------------


class EjercicioListView(PermisoRequeridoMixin, DeLaOrganizacionMixin, ListView):
    model = Ejercicio
    template_name = "organizaciones/ejercicio_lista.html"
    context_object_name = "ejercicios"


class _EjercicioFormMixin(PermisoRequeridoMixin, DeLaOrganizacionMixin):
    model = Ejercicio
    form_class = EjercicioForm
    form_con_organizacion = True
    template_name = "organizaciones/ejercicio_form.html"
    success_url = reverse_lazy("organizaciones:ejercicio_lista")


class EjercicioCreateView(_EjercicioFormMixin, CreateView):
    def form_valid(self, form):
        respuesta = super().form_valid(form)
        registrar(self.request, Accion.CREAR_EJERCICIO, modelo="Ejercicio", objeto_id=self.object.pk,
                  descripcion=f"{self.object.nombre} ({self.object.fecha_inicio} a {self.object.fecha_fin})")
        messages.success(self.request, f"Ejercicio «{self.object.nombre}» creado. Actívalo para empezar a usarlo.")
        return respuesta


class EjercicioUpdateView(_EjercicioFormMixin, UpdateView):
    def get_queryset(self):
        # Un ejercicio cerrado ya no se edita.
        return super().get_queryset().filter(cerrado=False)

    def form_valid(self, form):
        messages.success(self.request, f"Ejercicio «{form.instance.nombre}» actualizado.")
        return super().form_valid(form)


@requiere_permiso()
@require_POST
def ejercicio_activar(request, pk):
    ejercicio = get_object_or_404(Ejercicio, pk=pk, organizacion=request.organizacion, cerrado=False)
    with transaction.atomic():
        # Primero se apaga el anterior: la restricción permite uno solo activo.
        Ejercicio.objects.filter(organizacion=request.organizacion, activo=True).exclude(pk=ejercicio.pk).update(activo=False)
        ejercicio.activo = True
        ejercicio.save(update_fields=["activo"])
    registrar(request, Accion.ACTIVAR_EJERCICIO, modelo="Ejercicio", objeto_id=ejercicio.pk, descripcion=ejercicio.nombre)
    messages.success(request, f"«{ejercicio.nombre}» es ahora el ejercicio activo.")
    return redirect("organizaciones:ejercicio_lista")


@requiere_permiso()
@require_POST
def ejercicio_cerrar(request, pk):
    ejercicio = get_object_or_404(Ejercicio, pk=pk, organizacion=request.organizacion, cerrado=False)
    ejercicio.cerrado = True
    ejercicio.activo = False
    ejercicio.cerrado_por = request.user
    ejercicio.fecha_cierre = timezone.now()
    ejercicio.save(update_fields=["cerrado", "activo", "cerrado_por", "fecha_cierre"])
    registrar(request, Accion.CERRAR_EJERCICIO, modelo="Ejercicio", objeto_id=ejercicio.pk, descripcion=ejercicio.nombre)
    messages.success(request, f"Ejercicio «{ejercicio.nombre}» cerrado.")
    return redirect("organizaciones:ejercicio_lista")


@requiere_permiso()
@require_POST
def ejercicio_eliminar(request, pk):
    ejercicio = get_object_or_404(Ejercicio, pk=pk, organizacion=request.organizacion, cerrado=False)
    return eliminar_protegido(request, ejercicio, "organizaciones:ejercicio_lista")


# --- Bitácora --------------------------------------------------------------


class BitacoraListView(PermisoRequeridoMixin, ListView):
    """Solo los eventos de esta organización. Los de plataforma (organizacion
    vacía) y los de otras organizaciones no aparecen."""

    template_name = "organizaciones/bitacora_lista.html"
    context_object_name = "registros"
    paginate_by = 50

    def get_queryset(self):
        qs = RegistroAuditoria.objects.filter(organizacion=self.request.organizacion).select_related("usuario")
        self.accion = self.request.GET.get("accion", "")
        if self.accion in Accion.values:
            qs = qs.filter(accion=self.accion)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["acciones"] = Accion.choices
        ctx["accion_filtro"] = self.accion
        return ctx
