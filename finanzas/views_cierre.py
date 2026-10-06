"""Arqueo de caja y anticipos por rendir (Fase 8). Solo el director y los
administradores. Todo se filtra por `request.organizacion`."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.mixins import requiere_permiso
from core.models import RegistroAuditoria

from . import services
from .forms import AnticipoForm, AnularForm, ArqueoForm, RendicionForm
from .models import Anticipo, Arqueo, Cuenta

Accion = RegistroAuditoria.Accion


def _errores_al_form(form, error):
    if hasattr(error, "message_dict"):
        for campo, mensajes in error.message_dict.items():
            form.add_error(campo if campo in form.fields else None, mensajes)
    else:
        form.add_error(None, error.messages)


def _saldos(organizacion):
    """{cuenta_id: {"saldo", "moneda"}} para que el formulario muestre el saldo al elegir la cuenta."""
    sumas = services._sumas_por_cuenta(organizacion)
    return {str(c.pk): {"saldo": float(c.saldo_inicial + sumas.get(c.pk, 0)), "moneda": c.moneda}
            for c in Cuenta.objects.filter(organizacion=organizacion, activa=True)}


# --- Arqueos ----------------------------------------------------------------


@requiere_permiso()
def arqueos(request):
    lista = Arqueo.objects.filter(organizacion=request.organizacion).select_related("cuenta", "cuenta__caja", "realizado_por", "ajuste")
    return render(request, "finanzas/arqueo_lista.html", {"arqueos": lista[:100]})


@requiere_permiso()
def arqueo_nuevo(request):
    organizacion = request.organizacion
    form = ArqueoForm(request.POST or None, organizacion=organizacion, initial={"cuenta": request.GET.get("cuenta")})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        arqueo = services.registrar_arqueo(organizacion=organizacion, cuenta=d["cuenta"], contado=d["contado"],
                                           fecha=d["fecha"], nota=d["nota"], usuario=request.user)
        registrar(request, Accion.REGISTRAR_ARQUEO, modelo="Arqueo", objeto_id=arqueo.pk,
                  descripcion=f"{arqueo.cuenta} · sistema {arqueo.saldo_sistema:.2f} · contado {arqueo.contado:.2f} · "
                  f"diferencia {arqueo.diferencia:+.2f} {arqueo.cuenta.moneda}")
        if arqueo.cuadra:
            messages.success(request, "El arqueo cuadra: lo contado coincide con el sistema.")
        return redirect("finanzas:arqueo_detalle", pk=arqueo.pk)
    return render(request, "finanzas/arqueo_form.html", {"form": form, "saldos": _saldos(organizacion)})


@requiere_permiso()
def arqueo_detalle(request, pk):
    arqueo = get_object_or_404(
        Arqueo.objects.select_related("cuenta", "cuenta__caja", "realizado_por", "ajuste"), pk=pk, organizacion=request.organizacion)
    return render(request, "finanzas/arqueo_detalle.html", {"a": arqueo})


@requiere_permiso()
@require_POST
def arqueo_ajustar(request, pk):
    arqueo = get_object_or_404(Arqueo, pk=pk, organizacion=request.organizacion)
    try:
        movimiento = services.ajustar_arqueo(arqueo, membresia=request.membresia)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        registrar(request, Accion.AJUSTAR_ARQUEO, modelo="Arqueo", objeto_id=arqueo.pk,
                  descripcion=f"{arqueo.cuenta} · {movimiento.get_tipo_display()} #{movimiento.numero_vale} por "
                  f"{movimiento.moneda} {movimiento.monto:.2f}")
        messages.success(request, f"Ajuste registrado como {movimiento.get_tipo_display().lower()} #{movimiento.numero_vale}. "
                         "El saldo de la cuenta ya coincide con lo contado.")
    return redirect("finanzas:arqueo_detalle", pk=pk)


# --- Anticipos --------------------------------------------------------------


@requiere_permiso()
def anticipos(request):
    lista = Anticipo.objects.filter(organizacion=request.organizacion).select_related("cuenta", "miembro", "miembro__user")
    estado = request.GET.get("estado", "")
    if estado in Anticipo.Estado.values:
        lista = lista.filter(estado=estado)
    pendientes = Anticipo.objects.filter(organizacion=request.organizacion, estado=Anticipo.Estado.PENDIENTE)
    por_moneda = {}
    for a in pendientes.select_related("cuenta"):
        por_moneda[a.moneda] = por_moneda.get(a.moneda, 0) + a.monto
    return render(request, "finanzas/anticipo_lista.html", {
        "anticipos": lista[:150], "estado": estado, "n_pendientes": pendientes.count(), "por_moneda": sorted(por_moneda.items()),
    })


@requiere_permiso()
def anticipo_nuevo(request):
    organizacion = request.organizacion
    form = AnticipoForm(request.POST or None, organizacion=organizacion)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            anticipo = services.entregar_anticipo(
                organizacion=organizacion, cuenta=d["cuenta"], monto=d["monto"], fecha=d["fecha"], motivo=d["motivo"],
                miembro=d["miembro"], tercero=d["tercero"], membresia=request.membresia)
        except ValidationError as error:
            _errores_al_form(form, error)
        else:
            registrar(request, Accion.ENTREGAR_ANTICIPO, modelo="Anticipo", objeto_id=anticipo.pk,
                      descripcion=f"{anticipo.responsable} · {anticipo.moneda} {anticipo.monto:.2f} · {anticipo.motivo} · "
                      f"egreso #{anticipo.entrega.numero_vale}")
            messages.success(request, f"Anticipo entregado a {anticipo.responsable}. Queda por rendir.")
            return redirect("finanzas:anticipo_detalle", pk=anticipo.pk)
    return render(request, "finanzas/anticipo_form.html", {"form": form, "saldos": _saldos(organizacion)})


def _anticipo(request, pk):
    return get_object_or_404(
        Anticipo.objects.select_related("cuenta", "cuenta__caja", "miembro", "miembro__user", "entrega", "entregado_por"),
        pk=pk, organizacion=request.organizacion)


@requiere_permiso()
def anticipo_detalle(request, pk):
    anticipo = _anticipo(request, pk)
    return render(request, "finanzas/anticipo_detalle.html", {
        "a": anticipo, "gastos": anticipo.gastos.select_related("concepto", "concepto__padre").order_by("pk"),
    })


@requiere_permiso()
def anticipo_rendir(request, pk):
    anticipo = _anticipo(request, pk)
    if anticipo.estado != Anticipo.Estado.PENDIENTE:
        messages.info(request, "Este anticipo ya no está por rendir.")
        return redirect("finanzas:anticipo_detalle", pk=pk)
    form = RendicionForm(request.POST or None, organizacion=request.organizacion)
    if request.method == "POST" and form.is_valid():
        try:
            services.rendir_anticipo(anticipo, fecha=form.cleaned_data["fecha"], lineas=form.cleaned_data["lineas"],
                                     membresia=request.membresia)
        except ValidationError as error:
            _errores_al_form(form, error)
        else:
            anticipo.refresh_from_db()
            registrar(request, Accion.RENDIR_ANTICIPO, modelo="Anticipo", objeto_id=anticipo.pk,
                      descripcion=f"{anticipo.responsable} · entregado {anticipo.moneda} {anticipo.monto:.2f} · "
                      f"gastado {anticipo.gastado:.2f} · {len(form.cleaned_data['lineas'])} gasto(s)")
            messages.success(request, "Anticipo rendido. Los gastos ya están en el libro, cada uno con su concepto.")
            return redirect("finanzas:anticipo_detalle", pk=pk)
    return render(request, "finanzas/anticipo_rendir.html", {"form": form, "a": anticipo})


@requiere_permiso()
def anticipo_anular(request, pk):
    anticipo = _anticipo(request, pk)
    if anticipo.estado != Anticipo.Estado.PENDIENTE:
        messages.info(request, "Solo se anula un anticipo que sigue por rendir.")
        return redirect("finanzas:anticipo_detalle", pk=pk)
    form = AnularForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.anular_anticipo(anticipo, usuario=request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _errores_al_form(form, error)
        else:
            registrar(request, Accion.ANULAR_ANTICIPO, modelo="Anticipo", objeto_id=anticipo.pk,
                      descripcion=f"{anticipo.responsable} · {anticipo.moneda} {anticipo.monto:.2f} · Motivo: {form.cleaned_data['motivo']}")
            messages.success(request, "Anticipo anulado: el dinero vuelve a figurar en la cuenta.")
            return redirect("finanzas:anticipo_detalle", pk=pk)
    return render(request, "finanzas/anticipo_anular.html", {"form": form, "a": anticipo})
