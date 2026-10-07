from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from core.auditoria import registrar
from core.mixins import SoloSuperusuarioMixin
from core.models import RegistroAuditoria

from . import bcv
from .forms import TasaCambioForm
from .models import TasaCambio

# La tasa es global (sirve a todas las organizaciones), así que solo la
# administra el superadmin. Los eventos van a la bitácora sin organización.


class TasaCambioListView(SoloSuperusuarioMixin, ListView):
    """Historial de tasas cargadas, más recientes primero."""

    model = TasaCambio
    template_name = "cambio/tasa_lista.html"
    context_object_name = "tasas"
    paginate_by = 30


class TasaCambioCreateView(SoloSuperusuarioMixin, CreateView):
    model = TasaCambio
    form_class = TasaCambioForm
    template_name = "cambio/tasa_form.html"
    success_url = reverse_lazy("cambio:tasa_lista")

    def form_valid(self, form):
        form.instance.cargada_por = self.request.user
        respuesta = super().form_valid(form)
        registrar(
            self.request, RegistroAuditoria.Accion.CARGAR_TASA,
            modelo="TasaCambio", objeto_id=self.object.pk, descripcion=str(self.object), organizacion=None,
        )
        messages.success(self.request, f"Tasa «{self.object}» cargada.")
        return respuesta


class TasaCambioUpdateView(SoloSuperusuarioMixin, UpdateView):
    """Corregir el `valor` de una tasa ya cargada."""

    model = TasaCambio
    form_class = TasaCambioForm
    template_name = "cambio/tasa_form.html"
    success_url = reverse_lazy("cambio:tasa_lista")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["tiene_transacciones"] = self.object.tiene_transacciones()
        return ctx

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        registrar(
            self.request, RegistroAuditoria.Accion.EDITAR_TASA,
            modelo="TasaCambio", objeto_id=self.object.pk, descripcion=str(self.object), organizacion=None,
        )
        messages.success(self.request, f"Tasa «{self.object}» actualizada.")
        return respuesta


@require_POST
def consultar_bcv(request):
    """Botón «Consultar BCV ahora»: lo mismo que hace la tarea programada."""
    if not request.user.is_authenticated or not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    try:
        tasa, estado = bcv.actualizar(request.user)
    except Exception as e:  # noqa: BLE001 - red, certificado o página cambiada: se explica y se sigue
        messages.error(request, f"No se pudo consultar el BCV: {e}")
        return redirect("cambio:tasa_lista")
    if estado == "igual":
        messages.info(request, f"Sin cambios: la tasa «{tasa}» ya estaba cargada.")
    else:
        registrar(
            request,
            RegistroAuditoria.Accion.CARGAR_TASA if estado == "nueva" else RegistroAuditoria.Accion.EDITAR_TASA,
            modelo="TasaCambio", objeto_id=tasa.pk, descripcion=f"{tasa} (consulta al BCV)", organizacion=None,
        )
        messages.success(request, f"Tasa «{tasa}» {'cargada' if estado == 'nueva' else 'corregida'} desde el BCV.")
    return redirect("cambio:tasa_lista")
