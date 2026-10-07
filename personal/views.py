"""Sección «Personal» y las asignaciones.

Dos pantallas propias de cada miembro que entra al sistema:

- «Mi resumen»: su relación con la organización (lo que aportó y recibió de
  ella, y sus cuotas). Son datos del libro de la organización, filtrados a él.
- «Mi cuenta»: su cuenta personal, si su tipo de miembro la tiene.

El director las tiene igual que cualquiera: es un miembro más de la
comunidad. Su vista de director sigue en el resto del menú.

Lo del director sobre los demás: registra asignaciones y ve cuánto asignó.
La cuenta de otro miembro solo la abre si el superadmin encendió
`director_ve_cuentas_personales`; cada consulta queda en la bitácora.
"""

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.mixins import requiere_permiso
from core.models import RegistroAuditoria
from finanzas.models import Movimiento
from finanzas.services import estado_cuotas, tasa_vigente
from organizaciones.models import Ejercicio, Membresia
from presupuestos.services import meses_del_ejercicio
from reportes.services import SIMBOLO
from reportes.views import _grafico_mensual

from . import services
from .forms import AsignacionForm, ConceptoPersonalForm, MovimientoPersonalForm
from .models import ConceptoPersonal, MovimientoPersonal

Accion = RegistroAuditoria.Accion
CERO = services.CERO


def _membresia(request):
    if request.membresia is None:
        raise PermissionDenied("No perteneces a una organización.")
    return request.membresia


def _ejercicio(organizacion):
    hoy = timezone.localdate()
    qs = Ejercicio.objects.filter(organizacion=organizacion)
    return qs.filter(activo=True).first() or qs.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy).first() or qs.first()


def _moneda(request):
    pedida = request.GET.get("moneda")
    return pedida if pedida in SIMBOLO else request.organizacion.moneda_base


def _periodo(request, ejercicio):
    """El período pedido (?desde=&hasta=) o lo que va del ejercicio."""
    hoy = timezone.localdate()
    desde = ejercicio.fecha_inicio if ejercicio else hoy.replace(month=1, day=1)
    hasta = min(hoy, ejercicio.fecha_fin) if ejercicio else hoy
    try:
        desde = date.fromisoformat(request.GET.get("desde", "")) or desde
    except ValueError:
        pass
    try:
        hasta = date.fromisoformat(request.GET.get("hasta", "")) or hasta
    except ValueError:
        pass
    return (desde, hasta) if desde <= hasta else (hasta, desde)


# --- Mi resumen: mi relación con la organización ----------------------------


@login_required
def resumen(request):
    m = _membresia(request)
    organizacion = request.organizacion
    ejercicio = _ejercicio(organizacion)
    moneda = _moneda(request)
    campo = "monto_usd" if moneda == "USD" else "monto_ves"
    desde, hasta = _periodo(request, ejercicio)

    mios = Movimiento.objects.filter(organizacion=organizacion, miembro=m, estado=Movimiento.Estado.CONFIRMADO)
    periodo = mios.filter(fecha__gte=desde, fecha__lte=hasta)
    totales = periodo.aggregate(aporto=Sum(campo, filter=Q(tipo="ingreso")), recibio=Sum(campo, filter=Q(tipo="egreso")))
    aporto, recibio = totales["aporto"] or CERO, totales["recibio"] or CERO

    def por_concepto(tipo, total):
        filas = periodo.filter(tipo=tipo).values("concepto__nombre").annotate(total=Sum(campo)).order_by("-total")[:8]
        items = [(f["concepto__nombre"] or "Sin concepto", f["total"] or CERO) for f in filas]
        tope = max((x for _, x in items), default=CERO)
        return [{"nombre": n, "monto": x, "pct": (x / total * 100) if total else None,
                 "ancho": f"{float(x / tope * 100) if tope else 0:.1f}"} for n, x in items]

    serie = []
    if ejercicio:
        datos = {}
        for f in (mios.filter(fecha__gte=ejercicio.fecha_inicio, fecha__lte=ejercicio.fecha_fin)
                  .values("fecha__year", "fecha__month", "tipo").annotate(total=Sum(campo))):
            datos[(f["fecha__year"], f["fecha__month"], f["tipo"])] = f["total"] or CERO
        serie = [(mes, datos.get((mes.year, mes.month, "ingreso"), CERO), datos.get((mes.year, mes.month, "egreso"), CERO))
                 for mes in meses_del_ejercicio(ejercicio)]

    return render(request, "personal/resumen.html", {
        "m": m, "ejercicio": ejercicio, "desde": desde, "hasta": hasta, "moneda": moneda, "simbolo": SIMBOLO[moneda],
        "aporto": aporto, "recibio": recibio, "neto": aporto - recibio,
        "aportes": por_concepto("ingreso", aporto), "recibidos": por_concepto("egreso", recibio),
        "grafico": _grafico_mensual(serie), "etiquetas": ("Aporté", "Recibí"),
        "cuotas": estado_cuotas(organizacion, ejercicio, membresia=m) if ejercicio else [],
        "movimientos": mios.select_related("concepto", "concepto__padre", "cuenta").order_by("-fecha", "-id")[:15],
    })


# --- Mi cuenta personal -----------------------------------------------------


def _con_cuenta(request):
    m = _membresia(request)
    if not m.tiene_permiso("tiene_cuenta_personal"):
        raise PermissionDenied("Tu tipo de miembro no tiene cuenta personal.")
    return m


def _contexto_cuenta(request, m, solo_lectura):
    organizacion = m.organizacion
    ejercicio = _ejercicio(organizacion)
    moneda = _moneda(request)
    desde, hasta = _periodo(request, ejercicio)
    saldo_ves, saldo_usd = services.saldo(m)
    meses = meses_del_ejercicio(ejercicio) if ejercicio else []
    tasa, _ = tasa_vigente(request.organizacion)
    return {
        "m": m, "solo_lectura": solo_lectura, "moneda": moneda, "simbolo": SIMBOLO[moneda],
        "desde": desde, "hasta": hasta, "ejercicio": ejercicio, "tasa": tasa,
        "saldo_ves": saldo_ves, "saldo_usd": saldo_usd,
        "e": services.estadisticas(m, desde, hasta, moneda),
        "grafico": _grafico_mensual(services.serie_mensual(m, meses, moneda)),
        "movimientos": services.vigentes(m).select_related("concepto", "origen")[:40],
        "etiquetas": ("Entró", "Gasté"),
        "director_ve": organizacion.director_ve_cuentas_personales,
    }


@login_required
def cuenta(request):
    m = _con_cuenta(request)
    return render(request, "personal/cuenta.html", _contexto_cuenta(request, m, solo_lectura=False))


@login_required
def movimiento_form(request, tipo=None, pk=None):
    m = _con_cuenta(request)
    instancia = None
    if pk is not None:
        # Solo los propios, y nunca una asignación: esa la registró la organización.
        instancia = get_object_or_404(MovimientoPersonal, pk=pk, membresia=m, origen__isnull=True)
        tipo = instancia.tipo
    form = MovimientoPersonalForm(request.POST or None, instance=instancia, membresia=m, tipo=tipo)
    if request.method == "POST" and form.is_valid():
        try:
            services.registrar_personal(form.save(commit=False))
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            messages.success(request, "Guardado en tu cuenta personal.")
            return redirect("personal:cuenta")
    return render(request, "personal/movimiento_form.html", {"form": form, "tipo": tipo, "instancia": instancia})


@login_required
@require_POST
def movimiento_eliminar(request, pk):
    m = _con_cuenta(request)
    get_object_or_404(MovimientoPersonal, pk=pk, membresia=m, origen__isnull=True).delete()
    messages.success(request, "Movimiento eliminado de tu cuenta personal.")
    return redirect("personal:cuenta")


@login_required
def conceptos(request):
    m = _con_cuenta(request)
    form = ConceptoPersonalForm(request.POST or None, membresia=m)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Concepto agregado.")
        return redirect("personal:conceptos")
    lista = ConceptoPersonal.objects.filter(organizacion=request.organizacion).filter(
        Q(membresia=m) | Q(membresia__isnull=True))
    return render(request, "personal/conceptos.html", {"form": form, "conceptos": lista})


@login_required
@require_POST
def concepto_eliminar(request, pk):
    m = _con_cuenta(request)
    concepto = get_object_or_404(ConceptoPersonal, pk=pk, membresia=m)
    if concepto.movimientos.exists():
        concepto.activo = False
        concepto.save(update_fields=["activo"])
        messages.info(request, "Ese concepto ya tiene movimientos: se desactivó en vez de eliminarse.")
    else:
        concepto.delete()
        messages.success(request, "Concepto eliminado.")
    return redirect("personal:conceptos")


# --- Del director: asignaciones y cuentas de los miembros -------------------


@requiere_permiso()
def asignaciones(request):
    organizacion = request.organizacion
    asignado = services.total_asignado(organizacion)
    ve = organizacion.director_ve_cuentas_personales
    miembros = []
    for m in Membresia.objects.filter(organizacion=organizacion, activa=True, user__isnull=False).select_related("user", "tipo"):
        if not m.tiene_permiso("tiene_cuenta_personal"):
            continue
        ves, usd, n = asignado.get(m.pk, (CERO, CERO, 0))
        fila = {"m": m, "asignado_ves": ves, "asignado_usd": usd, "n": n}
        fila["saldo_ves"] = fila["saldo_usd"] = None
        if ve and m.pk != request.membresia.pk:
            fila["saldo_ves"], fila["saldo_usd"] = services.saldo(m)
        miembros.append(fila)
    recientes = (
        MovimientoPersonal.objects.filter(organizacion=organizacion, origen__isnull=False)
        .select_related("membresia", "membresia__user", "origen", "origen__cuenta")[:30]
    )
    return render(request, "personal/asignaciones.html", {"miembros": miembros, "recientes": recientes, "ve": ve})


@requiere_permiso()
def asignacion_nueva(request):
    form = AsignacionForm(request.POST or None, organizacion=request.organizacion)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            egreso, _ = services.asignar(
                destino=d["destino"], cuenta=d["cuenta"], monto=d["monto"], fecha=d["fecha"],
                concepto=d["concepto"], nota=d["nota"], actor=request.membresia,
            )
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for campo, mensajes in error.message_dict.items():
                    form.add_error(campo if campo in form.fields else None, mensajes)
            else:
                form.add_error(None, error.messages)
        else:
            registrar(request, Accion.ASIGNAR, modelo="Movimiento", objeto_id=egreso.pk,
                      descripcion=f"{egreso.moneda} {egreso.monto:.2f} a {d['destino'].nombre} · egreso #{egreso.numero_vale} · {egreso.cuenta}")
            messages.success(request, f"Asignación registrada: egreso #{egreso.numero_vale} y entrada en la cuenta de {d['destino'].nombre}.")
            return redirect("personal:asignaciones")
    return render(request, "personal/asignacion_form.html", {"form": form})


@requiere_permiso()
def cuenta_de_miembro(request, pk):
    """La cuenta personal de otro miembro, en solo lectura. Solo si el
    superadmin lo permitió para esta organización."""
    organizacion = request.organizacion
    m = get_object_or_404(Membresia.objects.select_related("user", "tipo"), pk=pk, organizacion=organizacion)
    if m.pk == request.membresia.pk:
        return redirect("personal:cuenta")
    if not organizacion.director_ve_cuentas_personales:
        raise PermissionDenied("Las cuentas personales de los miembros son privadas en esta organización.")
    registrar(request, Accion.VER_CUENTA_PERSONAL, modelo="Membresia", objeto_id=m.pk, descripcion=m.nombre)
    return render(request, "personal/cuenta.html", _contexto_cuenta(request, m, solo_lectura=True))
