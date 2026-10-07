"""Tasa de cambio propia de la organización (A-47). La del BCV llega sola a
todas; aquí el director o un administrador carga la suya: por si la automática
falla o porque la organización trabaja con otra. Solo vale para ella."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cambio.forms import TasaPropiaForm
from cambio.models import TasaCambio
from core.auditoria import registrar
from core.mixins import requiere_permiso
from core.models import RegistroAuditoria
from finanzas.services import tasa_vigente

Accion = RegistroAuditoria.Accion


def _contexto(request, form, editando=None):
    organizacion = request.organizacion
    vigente, exacta = tasa_vigente(organizacion)
    global_, _ = tasa_vigente()
    return {
        "form": form, "editando": editando, "vigente": vigente, "vigente_exacta": exacta, "global": global_,
        "propias": TasaCambio.objects.filter(organizacion=organizacion).select_related("cargada_por")[:60],
    }


@requiere_permiso()
def inicio(request):
    organizacion = request.organizacion
    form = TasaPropiaForm(request.POST or None, organizacion=organizacion)
    if request.method == "POST" and form.is_valid():
        tasa = form.save(commit=False)
        tasa.organizacion, tasa.fuente, tasa.cargada_por = organizacion, TasaCambio.Fuente.MANUAL, request.user
        tasa.save()
        registrar(request, Accion.CARGAR_TASA, modelo="TasaCambio", objeto_id=tasa.pk, descripcion=str(tasa))
        messages.success(request, f"Tasa del {tasa.fecha:%d/%m/%Y} cargada: Bs. {tasa.valor} por dólar.")
        return redirect("organizaciones:tasa")
    return render(request, "organizaciones/tasa.html", _contexto(request, form))


@requiere_permiso()
def corregir(request, pk):
    tasa = get_object_or_404(TasaCambio, pk=pk, organizacion=request.organizacion)
    anterior = tasa.valor
    form = TasaPropiaForm(request.POST or None, instance=tasa, organizacion=request.organizacion)
    if request.method == "POST" and form.is_valid():
        form.save()
        registrar(request, Accion.EDITAR_TASA, modelo="TasaCambio", objeto_id=tasa.pk,
                  descripcion=f"{tasa} (antes {anterior})")
        messages.success(request, "Tasa corregida. Lo ya confirmado conserva la tasa con la que se registró.")
        return redirect("organizaciones:tasa")
    return render(request, "organizaciones/tasa.html", _contexto(request, form, editando=tasa))


@requiere_permiso()
@require_POST
def eliminar(request, pk):
    tasa = get_object_or_404(TasaCambio, pk=pk, organizacion=request.organizacion)
    if tasa.tiene_transacciones():
        messages.error(request, "Esa tasa ya se usó en movimientos: no se puede eliminar, solo corregir.")
    else:
        descripcion = f"{tasa} (eliminada)"
        tasa.delete()
        registrar(request, Accion.EDITAR_TASA, modelo="TasaCambio", objeto_id=pk, descripcion=descripcion)
        messages.success(request, "Tasa eliminada. Vuelve a aplicar la del BCV.")
    return redirect("organizaciones:tasa")
