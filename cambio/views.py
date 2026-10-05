from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView, UpdateView

from core.auditoria import registrar
from core.mixins import SoloSuperusuarioMixin
from core.models import RegistroAuditoria

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
