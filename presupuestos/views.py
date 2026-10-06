"""Presupuestos: quien tiene `puede_ver_presupuesto` los consulta; solo el
director y los administradores los crean, editan y aprueban."""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.mixins import ADMINISTRAR, requiere_permiso, tiene_permiso
from core.models import RegistroAuditoria

from finanzas.models import Concepto

from .forms import PresupuestoForm
from .models import PartidaPresupuestaria, Presupuesto
from .services import comparativo, estado_de_partida, conceptos_de_la_caja, meses_del_ejercicio

Accion = RegistroAuditoria.Accion
VER = "puede_ver_presupuesto"


def _presupuesto(request, pk):
    return get_object_or_404(
        Presupuesto.objects.select_related("caja", "ejercicio", "aprobado_por"), pk=pk, organizacion=request.organizacion
    )


@requiere_permiso(VER)
def lista(request):
    presupuestos = Presupuesto.objects.filter(organizacion=request.organizacion).select_related("caja", "ejercicio")
    return render(request, "presupuestos/lista.html", {
        "presupuestos": presupuestos, "puede_editar": tiene_permiso(request, ADMINISTRAR),
    })


@requiere_permiso()
def crear(request):
    form = PresupuestoForm(request.POST or None, organizacion=request.organizacion)
    if request.method == "POST" and form.is_valid():
        presupuesto = form.save()
        registrar(request, Accion.CREAR_PRESUPUESTO, modelo="Presupuesto", objeto_id=presupuesto.pk,
                  descripcion=f"{presupuesto} ({presupuesto.moneda})")
        messages.success(request, "Presupuesto creado. Ahora asigna el monto mensual de cada concepto.")
        return redirect("presupuestos:editar", pk=presupuesto.pk)
    return render(request, "presupuestos/form.html", {"form": form})


def _mes_pedido(request, ejercicio):
    """El mes a mostrar: ?mes=AAAA-MM si cae en el ejercicio; si no, el actual o el último."""
    meses = meses_del_ejercicio(ejercicio)
    texto = request.GET.get("mes", "")
    try:
        anio, mes = texto.split("-")
        pedido = date(int(anio), int(mes), 1)
        if pedido in meses:
            return pedido, meses
    except (ValueError, TypeError):
        pass
    hoy = timezone.localdate().replace(day=1)
    return (hoy if hoy in meses else (meses[-1] if hoy > meses[-1] else meses[0])), meses


@requiere_permiso(VER)
def detalle(request, pk):
    presupuesto = _presupuesto(request, pk)
    mes, meses = _mes_pedido(request, presupuesto.ejercicio)
    return render(request, "presupuestos/detalle.html", {
        "p": presupuesto, "c": comparativo(presupuesto, mes), "mes": mes, "meses": meses,
        "puede_editar": tiene_permiso(request, ADMINISTRAR),
    })


def _leer_monto(texto):
    texto = (texto or "").strip().replace(" ", "")
    if not texto:
        return Decimal("0")
    if "," in texto:  # formato es-VE: 1.234,56
        texto = texto.replace(".", "").replace(",", ".")
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        return None
    return valor if valor >= 0 and valor.is_finite() else None


@requiere_permiso()
def editar(request, pk):
    """Una sola pantalla con todos los conceptos de la caja y su monto mensual."""
    presupuesto = _presupuesto(request, pk)
    if not presupuesto.editable:
        messages.info(request, "Este presupuesto está aprobado. Reábrelo para cambiarlo.")
        return redirect("presupuestos:detalle", pk=pk)

    conceptos = sorted(
        conceptos_de_la_caja(presupuesto).filter(activo=True),
        key=lambda c: (c.tipo != "ingreso", (c.padre.nombre if c.padre_id else c.nombre).lower(), bool(c.padre_id), c.nombre.lower()),
    )
    partidas = {p.concepto_id: p for p in presupuesto.partidas.all()}
    errores, errores_nuevos, nuevos = {}, {}, []

    if request.method == "POST":
        cambios = []
        for concepto in conceptos:
            monto = _leer_monto(request.POST.get(f"monto_{concepto.pk}"))
            if monto is None:
                errores[concepto.pk] = "Escribe un número mayor o igual a cero."
                continue
            cambios.append((
                concepto, monto, bool(request.POST.get(f"solicitud_{concepto.pk}")),
                (request.POST.get(f"nota_{concepto.pk}") or "").strip()[:200],
            ))
        # Conceptos que aún no existen: se escriben aquí y pasan al catálogo.
        for tipo in ("ingreso", "egreso"):
            nombre = " ".join((request.POST.get(f"nuevo_{tipo}_nombre") or "").split())[:80]
            if not nombre:
                continue
            monto = _leer_monto(request.POST.get(f"nuevo_{tipo}_monto"))
            existente = Concepto.objects.filter(organizacion=request.organizacion, tipo=tipo, nombre__iexact=nombre).first()
            if existente is not None:
                donde = ("ya está en la lista de arriba" if existente.activo and existente.caja_id in (None, presupuesto.caja_id)
                         else "está desactivado o pertenece a otra caja; revísalo en Conceptos")
                errores_nuevos[tipo] = f"«{existente.nombre}» ya existe: {donde}."
            elif monto is None:
                errores_nuevos[tipo] = "Escribe un número mayor o igual a cero."
            else:
                nuevos.append((tipo, nombre, monto, bool(request.POST.get(f"nuevo_{tipo}_solicitud")),
                               (request.POST.get(f"nuevo_{tipo}_nota") or "").strip()[:200]))
        if not errores and not errores_nuevos:
            with transaction.atomic():
                for tipo, nombre, monto, solicitud, nota in nuevos:
                    # General (sin caja): queda disponible para registrar en cualquier caja.
                    concepto = Concepto.objects.create(organizacion=request.organizacion, tipo=tipo, nombre=nombre)
                    registrar(request, Accion.CREAR_CONCEPTO, modelo="Concepto", objeto_id=concepto.pk,
                              descripcion=f"{concepto.get_tipo_display()}: {concepto.nombre} (desde el presupuesto)")
                    PartidaPresupuestaria.objects.create(
                        organizacion=request.organizacion, presupuesto=presupuesto, concepto=concepto,
                        monto_mensual=monto, requiere_solicitud=solicitud, nota=nota)
                    cambios.append((concepto, monto, solicitud, nota))
                    partidas[concepto.pk] = None
                for concepto, monto, solicitud, nota in cambios[:len(cambios) - len(nuevos)]:
                    partida = partidas.get(concepto.pk)
                    vacia = not monto and not solicitud and not nota
                    if partida is None and vacia:
                        continue
                    if partida is not None and vacia:
                        partida.delete()
                        continue
                    partida = partida or PartidaPresupuestaria(
                        organizacion=request.organizacion, presupuesto=presupuesto, concepto=concepto
                    )
                    partida.monto_mensual, partida.requiere_solicitud, partida.nota = monto, solicitud, nota
                    partida.save()
            total = sum((m for c, m, _, _ in cambios if c.tipo == "egreso"), Decimal("0"))
            registrar(request, Accion.EDITAR_PRESUPUESTO, modelo="Presupuesto", objeto_id=presupuesto.pk,
                      descripcion=f"{presupuesto}: egresos mensuales {presupuesto.moneda} {total:.2f}")
            if nuevos:
                messages.success(request, "Presupuesto guardado. Se agregaron a Conceptos: "
                                 + ", ".join(n for _, n, *_ in nuevos) + ".")
            else:
                messages.success(request, "Presupuesto guardado.")
            if "otro" in request.POST:
                return redirect("presupuestos:editar", pk=pk)
            return redirect("presupuestos:detalle", pk=pk)

    filas = []
    for concepto in conceptos:
        partida = partidas.get(concepto.pk)
        enviado = request.method == "POST"
        filas.append({
            "concepto": concepto,
            "monto": request.POST.get(f"monto_{concepto.pk}", "") if enviado else (
                f"{partida.monto_mensual:.2f}" if partida and partida.monto_mensual else ""),
            "solicitud": bool(request.POST.get(f"solicitud_{concepto.pk}")) if enviado else bool(partida and partida.requiere_solicitud),
            "nota": request.POST.get(f"nota_{concepto.pk}", "") if enviado else (partida.nota if partida else ""),
            "error": errores.get(concepto.pk),
        })
    return render(request, "presupuestos/editar.html", {
        "p": presupuesto,
        "ingresos": [f for f in filas if f["concepto"].tipo == "ingreso"],
        "egresos": [f for f in filas if f["concepto"].tipo == "egreso"],
        "hay_errores": bool(errores or errores_nuevos),
        "nuevo": {t: {"nombre": request.POST.get(f"nuevo_{t}_nombre", ""), "monto": request.POST.get(f"nuevo_{t}_monto", ""),
                      "solicitud": bool(request.POST.get(f"nuevo_{t}_solicitud")), "nota": request.POST.get(f"nuevo_{t}_nota", ""),
                      "error": errores_nuevos.get(t)} for t in ("ingreso", "egreso")},
    })


@requiere_permiso()
@require_POST
def aprobar(request, pk):
    presupuesto = _presupuesto(request, pk)
    if presupuesto.estado == Presupuesto.Estado.BORRADOR:
        presupuesto.estado = Presupuesto.Estado.APROBADO
        presupuesto.aprobado_por = request.user
        presupuesto.fecha_aprobacion = timezone.now()
        presupuesto.save(update_fields=["estado", "aprobado_por", "fecha_aprobacion"])
        registrar(request, Accion.APROBAR_PRESUPUESTO, modelo="Presupuesto", objeto_id=presupuesto.pk, descripcion=str(presupuesto))
        messages.success(request, "Presupuesto aprobado. Queda bloqueado para cambios.")
    return redirect("presupuestos:detalle", pk=pk)


@requiere_permiso()
@require_POST
def reabrir(request, pk):
    presupuesto = _presupuesto(request, pk)
    if presupuesto.estado == Presupuesto.Estado.APROBADO and not presupuesto.ejercicio.cerrado:
        presupuesto.estado = Presupuesto.Estado.BORRADOR
        presupuesto.save(update_fields=["estado"])
        registrar(request, Accion.REABRIR_PRESUPUESTO, modelo="Presupuesto", objeto_id=presupuesto.pk, descripcion=str(presupuesto))
        messages.warning(request, "Presupuesto reabierto: vuelve a ser un borrador. Quedó en la bitácora.")
    return redirect("presupuestos:detalle", pk=pk)


@requiere_permiso()
@require_POST
def eliminar(request, pk):
    presupuesto = _presupuesto(request, pk)
    if presupuesto.estado != Presupuesto.Estado.BORRADOR:
        messages.error(request, "Un presupuesto aprobado no se elimina. Reábrelo primero.")
        return redirect("presupuestos:detalle", pk=pk)
    nombre = str(presupuesto)
    presupuesto.delete()
    registrar(request, Accion.ELIMINAR_PRESUPUESTO, modelo="Presupuesto", objeto_id=pk, descripcion=nombre)
    messages.success(request, f"«{nombre}» eliminado.")
    return redirect("presupuestos:lista")


@login_required
def partida_disponible(request):
    """JSON para el formulario de egreso: cuánto queda de la partida del mes.
    Lo consulta quien puede registrar egresos; solo informa, nunca impide."""
    from finanzas.models import Cuenta

    if not tiene_permiso(request, "puede_registrar_egresos"):
        raise PermissionDenied
    try:
        fecha = date.fromisoformat(request.GET.get("fecha", ""))
        cuenta_id, concepto_id = int(request.GET.get("cuenta", "")), int(request.GET.get("concepto", ""))
    except ValueError:
        return JsonResponse({"partida": None})
    cuenta = Cuenta.objects.filter(organizacion=request.organizacion, pk=cuenta_id).first()
    estado = estado_de_partida(request.organizacion, cuenta.caja_id, concepto_id, fecha) if cuenta else None
    if estado is None:
        return JsonResponse({"partida": None})
    return JsonResponse({"partida": {k: (float(v) if isinstance(v, Decimal) else v) for k, v in estado.items()}})
