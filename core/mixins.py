"""Control de acceso por permiso del tipo de miembro.

En Edumia el acceso se decidía por un rol fijo (`PerfilUsuario.rol`). En Arca
cada organización define sus tipos de miembro, así que se pregunta por un
permiso: `permiso_requerido = "puede_registrar_egresos"`. El director (dueño)
y los administradores tienen todos los permisos; el permiso especial
"administrar" es solo para ellos.

Ser superusuario NO da acceso a los datos de una organización: el superadmin
administra la plataforma desde /admin/. Para entrar a una organización
necesita una membresía en ella, como cualquiera.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied

ADMINISTRAR = "administrar"

_MENSAJE = "No tienes permiso para acceder a esta página."


def tiene_permiso(request, permiso):
    membresia = getattr(request, "membresia", None)
    if membresia is None:
        return False
    return membresia.tiene_permiso(permiso)


class PermisoRequeridoMixin(LoginRequiredMixin, UserPassesTestMixin):
    """CBV mixin: exige una membresía activa con `permiso_requerido`."""

    permiso_requerido = ADMINISTRAR

    def test_func(self):
        return tiene_permiso(self.request, self.permiso_requerido)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied(_MENSAJE)


class DeLaOrganizacionMixin:
    """CBV mixin: limita el queryset a la organización activa y la asigna al
    crear. Va DESPUÉS de PermisoRequeridoMixin y antes de la vista genérica.

    Con esto, pedir por URL el pk de un objeto de otra organización responde
    404, igual que si no existiera."""

    def get_queryset(self):
        return super().get_queryset().filter(organizacion=self.request.organizacion)

    def form_valid(self, form):
        if form.instance.pk is None:
            form.instance.organizacion = self.request.organizacion
        return super().form_valid(form)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if getattr(self, "form_con_organizacion", False):
            kwargs["organizacion"] = self.request.organizacion
        return kwargs


def requiere_permiso(permiso=ADMINISTRAR):
    """Decorador para vistas basadas en función."""

    def decorador(vista):
        @login_required
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not tiene_permiso(request, permiso):
                raise PermissionDenied(_MENSAJE)
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador


class SoloSuperusuarioMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Pantallas de plataforma (p. ej. la tasa de cambio, que es global)."""

    def test_func(self):
        return self.request.user.is_active and self.request.user.is_superuser

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied(_MENSAJE)
