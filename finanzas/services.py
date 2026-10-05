"""Registro de movimientos y cálculo de saldos.

Saldos (decisión A-13): el saldo de una cuenta se suma en SU moneda y es
exacto. «Ver en USD / Ver en Bs.» convierte ese saldo con la tasa vigente:
responde a «¿cuánto tengo hoy?». Los ingresos y egresos de un período, en
cambio, usan el equivalente congelado de cada movimiento: responden a
«¿cuánto entró y salió?» con la tasa del día en que ocurrió.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from cambio.services import SinTasaError, convertir, obtener_tasa
from organizaciones.models import Ejercicio

from .models import Caja, Cuenta, Movimiento

CERO = Decimal("0")


def ejercicio_para(organizacion, fecha):
    """El ejercicio abierto de la organización que contiene `fecha`, o None."""
    return Ejercicio.objects.filter(
        organizacion=organizacion, cerrado=False, fecha_inicio__lte=fecha, fecha_fin__gte=fecha,
    ).first()


def tasa_para(fecha):
    """(TasaCambio, es_exacta). Prefiere la del BCV; si no hay, cualquier fuente.
    Lanza SinTasaError si no existe ninguna en esa fecha ni antes."""
    try:
        return obtener_tasa(fecha, fuente="bcv")
    except SinTasaError:
        return obtener_tasa(fecha)


def tasa_vigente():
    """La tasa para convertir saldos hoy, o (None, False) si no hay ninguna."""
    try:
        return tasa_para(timezone.localdate())
    except SinTasaError:
        return None, False


@transaction.atomic
def registrar_movimiento(movimiento, *, membresia):
    """Guarda un Movimiento nuevo ya validado por su formulario.

    Completa lo que no viene del formulario: ejercicio, tasa, número de vale
    y estado inicial. Devuelve (movimiento, creado); `creado` es False si el
    `uuid_cliente` ya existía (doble envío): se devuelve el original.
    """
    organizacion = movimiento.organizacion

    if movimiento.uuid_cliente:
        existente = Movimiento.objects.filter(
            organizacion=organizacion, uuid_cliente=movimiento.uuid_cliente
        ).first()
        if existente:
            return existente, False

    ejercicio = ejercicio_para(organizacion, movimiento.fecha)
    if ejercicio is None:
        raise ValidationError({"fecha": "No hay un ejercicio abierto que incluya esa fecha."})
    try:
        tasa, _ = tasa_para(movimiento.fecha)
    except SinTasaError:
        raise ValidationError(
            "No hay ninguna tasa de cambio cargada para esa fecha ni antes. Pide al soporte de Arca que la cargue."
        )

    movimiento.ejercicio = ejercicio
    movimiento.tasa = tasa
    movimiento.registrado_por = membresia.user
    movimiento.caja = movimiento.cuenta.caja

    # Un egreso espera aprobación solo si la organización lo exige y quien
    # registra no es director ni administrador.
    espera = (
        movimiento.tipo == Movimiento.Tipo.EGRESO
        and organizacion.requiere_aprobacion_egresos
        and not membresia.puede_administrar
    )
    movimiento.estado = Movimiento.Estado.REGISTRADO if espera else Movimiento.Estado.CONFIRMADO

    # Correlativo por caja y ejercicio. Se bloquea la fila de la caja para
    # que dos registros simultáneos no tomen el mismo número.
    Caja.objects.select_for_update().get(pk=movimiento.caja_id)
    ultimo = Movimiento.objects.filter(caja_id=movimiento.caja_id, ejercicio=ejercicio).aggregate(
        n=Max("numero_vale")
    )["n"]
    movimiento.numero_vale = (ultimo or 0) + 1

    movimiento.full_clean(exclude=["tasa_aplicada", "monto_ves", "monto_usd", "moneda"])
    movimiento.save()
    return movimiento, True


def _sumas_por_cuenta(organizacion, hasta=None):
    """{cuenta_id: saldo de movimientos confirmados, en la moneda de la cuenta}."""
    qs = Movimiento.objects.filter(organizacion=organizacion, estado=Movimiento.Estado.CONFIRMADO)
    if hasta is not None:
        qs = qs.filter(fecha__lte=hasta)
    sumas = {}
    for fila in qs.values("cuenta_id", "tipo").annotate(total=Sum("monto")):
        signo = 1 if fila["tipo"] == Movimiento.Tipo.INGRESO else -1
        sumas[fila["cuenta_id"]] = sumas.get(fila["cuenta_id"], CERO) + signo * fila["total"]
    return sumas


def saldo_cuenta(cuenta, hasta=None):
    return cuenta.saldo_inicial + _sumas_por_cuenta(cuenta.organizacion, hasta).get(cuenta.pk, CERO)


def resumen_saldos(organizacion, tasa=None):
    """Saldos por caja y cuenta, más el total, para el panel.

    Devuelve {"cajas": [{"caja", "cuentas": [{"cuenta", "saldo", "ves", "usd"}], "ves", "usd"}],
              "ves", "usd", "convertible"}.
    Sin tasa no se puede convertir: `ves` y `usd` suman solo las cuentas de
    esa moneda y `convertible` es False, para que la pantalla lo avise.
    """
    sumas = _sumas_por_cuenta(organizacion)
    cajas, total_ves, total_usd = [], CERO, CERO
    cuentas = Cuenta.objects.filter(organizacion=organizacion, activa=True, caja__activa=True).select_related("caja")
    por_caja = {}
    for cuenta in cuentas:
        saldo = cuenta.saldo_inicial + sumas.get(cuenta.pk, CERO)
        if tasa is not None:
            ves, usd = convertir(saldo, cuenta.moneda, tasa.valor)
        else:
            ves = saldo if cuenta.moneda == "VES" else CERO
            usd = saldo if cuenta.moneda == "USD" else CERO
        bloque = por_caja.setdefault(cuenta.caja_id, {"caja": cuenta.caja, "cuentas": [], "ves": CERO, "usd": CERO})
        bloque["cuentas"].append({"cuenta": cuenta, "saldo": saldo, "ves": ves, "usd": usd})
        bloque["ves"] += ves
        bloque["usd"] += usd
        total_ves += ves
        total_usd += usd
    cajas = sorted(por_caja.values(), key=lambda b: b["caja"].nombre.lower())
    return {"cajas": cajas, "ves": total_ves, "usd": total_usd, "convertible": tasa is not None}


def totales_periodo(organizacion, desde, hasta):
    """Ingresos y egresos confirmados entre dos fechas, con el equivalente
    congelado de cada movimiento. {"ingreso": {"ves","usd"}, "egreso": {...}}"""
    totales = {
        Movimiento.Tipo.INGRESO: {"ves": CERO, "usd": CERO},
        Movimiento.Tipo.EGRESO: {"ves": CERO, "usd": CERO},
    }
    filas = (
        Movimiento.objects.filter(
            organizacion=organizacion, estado=Movimiento.Estado.CONFIRMADO, fecha__gte=desde, fecha__lte=hasta,
        )
        .values("tipo")
        .annotate(ves=Sum("monto_ves"), usd=Sum("monto_usd"))
    )
    for fila in filas:
        totales[fila["tipo"]] = {"ves": fila["ves"] or CERO, "usd": fila["usd"] or CERO}
    return {"ingreso": totales[Movimiento.Tipo.INGRESO], "egreso": totales[Movimiento.Tipo.EGRESO]}
