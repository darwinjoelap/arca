"""Reportes de la cuenta personal (A-48). Devuelven un `Reporte`, así salen en
pantalla, Excel y PDF con el mismo código que los de la organización.

- `estado_de_cuenta`: la cuenta personal de UN miembro, movimiento a movimiento.
  La saca el propio miembro (y el director, solo con la supervisión activada).
- `mi_relacion`: lo que el miembro aportó y recibió en el libro de la
  organización. Es dinero de la organización, así que no es privado.
- `cuentas_personales`: saldo de cada miembro. Solo director o administrador,
  y solo si la plataforma activó la supervisión de las cuentas personales.

Montos en UNA moneda: el equivalente congelado de cada movimiento con la tasa
de su día, igual que en los reportes de la organización."""

from decimal import Decimal

from django.db.models import Q, Sum

from finanzas.models import Movimiento
from organizaciones.models import Membresia
from reportes.estructura import FECHA, MONTO, SECCION, TEXTO, TOTAL, Columna, Fila, Reporte

from . import services
from .models import MovimientoPersonal

CERO = Decimal("0")
SIMBOLO = {"USD": "$", "VES": "Bs."}


def _campo(moneda):
    return "monto_usd" if moneda == "USD" else "monto_ves"


def _periodo(desde, hasta, moneda):
    return f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} · Expresado en {SIMBOLO[moneda]}"


def _saldo_hasta(membresia, fecha, campo):
    """Saldo de la cuenta personal ANTES de `fecha`."""
    datos = services.vigentes(membresia).filter(fecha__lt=fecha).aggregate(
        i=Sum(campo, filter=Q(tipo="ingreso")), e=Sum(campo, filter=Q(tipo="egreso")))
    return (datos["i"] or CERO) - (datos["e"] or CERO)


def estado_de_cuenta(membresia, desde, hasta, moneda):
    campo = _campo(moneda)
    saldo = _saldo_hasta(membresia, desde, campo)
    filas = [Fila(["", "Saldo al inicio del período", None, None, saldo], clase=SECCION)]
    ingresos = egresos = CERO
    movimientos = (services.vigentes(membresia).filter(fecha__gte=desde, fecha__lte=hasta)
                   .select_related("concepto").order_by("fecha", "id"))
    for m in movimientos:
        monto = getattr(m, campo)
        detalle = m.titulo + (" (asignación)" if m.es_asignacion else "")
        if m.es_ingreso:
            ingresos += monto
            saldo += monto
            filas.append(Fila([m.fecha, detalle, monto, None, saldo]))
        else:
            egresos += monto
            saldo -= monto
            filas.append(Fila([m.fecha, detalle, None, monto, saldo]))
    filas.append(Fila(["", "Totales del período y saldo final", ingresos, egresos, saldo], clase=TOTAL))
    return Reporte(
        clave="personal-cuenta", titulo=f"Estado de cuenta personal: {membresia.nombre}",
        subtitulo=_periodo(desde, hasta, moneda),
        columnas=[Columna("Fecha", FECHA, 1), Columna("Concepto", TEXTO, 3.4), Columna("Ingreso", MONTO, 1.2),
                  Columna("Gasto", MONTO, 1.2), Columna("Saldo", MONTO, 1.3)],
        filas=filas,
        notas=["Cuenta personal del miembro, aparte del dinero de la organización.",
               "Cada movimiento va con la tasa de su día; por eso el saldo puede variar según la moneda en que se vea.",
               "Una asignación cuenta solo mientras su egreso en la organización siga confirmado."],
    )


def mi_relacion(membresia, desde, hasta, moneda):
    campo = _campo(moneda)
    movimientos = (Movimiento.objects.filter(
        organizacion=membresia.organizacion_id, miembro=membresia, estado=Movimiento.Estado.CONFIRMADO,
        fecha__gte=desde, fecha__lte=hasta).select_related("concepto", "concepto__padre", "cuenta").order_by("fecha", "id"))
    filas, aporto, recibio = [], CERO, CERO
    for m in movimientos:
        monto = getattr(m, campo)
        concepto = str(m.concepto) if m.concepto_id else m.descripcion
        if m.es_ingreso:
            aporto += monto
            filas.append(Fila([m.fecha, m.numero_vale, concepto, monto, None]))
        else:
            recibio += monto
            filas.append(Fila([m.fecha, m.numero_vale, concepto, None, monto]))
    filas.append(Fila(["", "", "Totales", aporto, recibio], clase=TOTAL))
    return Reporte(
        clave="personal-resumen", titulo=f"Aportes y entregas: {membresia.nombre}",
        subtitulo=_periodo(desde, hasta, moneda),
        columnas=[Columna("Fecha", FECHA, 1), Columna("Vale n.º", TEXTO, 0.8), Columna("Concepto", TEXTO, 3.2),
                  Columna("Aporté", MONTO, 1.2), Columna("Recibí", MONTO, 1.2)],
        filas=filas,
        notas=["Movimientos confirmados del libro de la organización registrados a nombre del miembro.",
               "No incluye su cuenta personal."],
    )


def miembros_con_cuenta(organizacion):
    """Quienes tienen cuenta personal hoy, más quien la tuvo y dejó movimientos."""
    con_movimientos = set(MovimientoPersonal.objects.filter(organizacion=organizacion)
                          .values_list("membresia_id", flat=True))
    miembros = Membresia.objects.filter(organizacion=organizacion).select_related("user", "tipo")
    return [m for m in miembros if m.pk in con_movimientos or (m.activa and m.tiene_acceso
                                                              and m.tiene_permiso("tiene_cuenta_personal"))]


def cuentas_personales(organizacion, desde, hasta, moneda):
    campo = _campo(moneda)
    filas = []
    totales = [CERO, CERO, CERO, CERO]
    for m in sorted(miembros_con_cuenta(organizacion), key=lambda x: x.nombre.lower()):
        base = services.vigentes(m)
        periodo = base.filter(fecha__gte=desde, fecha__lte=hasta).aggregate(
            i=Sum(campo, filter=Q(tipo="ingreso")), e=Sum(campo, filter=Q(tipo="egreso")),
            a=Sum(campo, filter=Q(origen__isnull=False)))
        saldo_ves, saldo_usd = services.saldo(m)
        valores = [periodo["a"] or CERO, periodo["i"] or CERO, periodo["e"] or CERO,
                   saldo_usd if moneda == "USD" else saldo_ves]
        totales = [t + v for t, v in zip(totales, valores)]
        nombre = m.nombre + ("" if m.activa else " (inactivo)")
        filas.append(Fila([nombre, m.rol_visible, *valores], tonos={5: "mal"} if valores[3] < 0 else {}))
    filas.append(Fila(["Total", "", *totales], clase=TOTAL))
    return Reporte(
        clave="cuentas-personales", titulo="Cuentas personales de los miembros",
        subtitulo=_periodo(desde, hasta, moneda),
        columnas=[Columna("Miembro", TEXTO, 2.6), Columna("Rol", TEXTO, 1.4), Columna("Asignado", MONTO, 1.2),
                  Columna("Entró (incluye asignado)", MONTO, 1.4), Columna("Gastó", MONTO, 1.2),
                  Columna("Saldo actual", MONTO, 1.3)],
        filas=filas, horizontal=True,
        notas=["Asignado, Entró y Gastó son del período; el saldo es el de hoy.",
               "Solo se emite porque la supervisión de las cuentas personales está activada para esta organización. "
               "Cada consulta queda en la bitácora."],
    )
