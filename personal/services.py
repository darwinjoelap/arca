"""Saldos y estadísticas de la cuenta personal, y el registro de asignaciones."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.functions import Coalesce
from django.db.models import Count, Q, Sum

from cambio.services import SinTasaError
from finanzas.models import Movimiento
from finanzas.services import registrar_movimiento, tasa_para

from .models import ConceptoPersonal, MovimientoPersonal

CERO = Decimal("0")


def vigentes(membresia):
    """Los movimientos personales que cuentan: los propios, y las asignaciones
    cuyo egreso en la organización sigue confirmado (si lo anulan o aún espera
    aprobación, el dinero no llegó)."""
    return MovimientoPersonal.objects.filter(membresia=membresia).filter(
        Q(origen__isnull=True) | Q(origen__estado=Movimiento.Estado.CONFIRMADO)
    )


def saldo(membresia):
    """(saldo_ves, saldo_usd). Cada movimiento con la tasa de su día: la cuenta
    personal no tiene «cuentas» con moneda propia, así que el saldo es la suma
    de los equivalentes. Sirve para el autocontrol, no es un arqueo."""
    datos = vigentes(membresia).aggregate(
        ing_ves=Sum("monto_ves", filter=Q(tipo="ingreso")), egr_ves=Sum("monto_ves", filter=Q(tipo="egreso")),
        ing_usd=Sum("monto_usd", filter=Q(tipo="ingreso")), egr_usd=Sum("monto_usd", filter=Q(tipo="egreso")),
    )
    return ((datos["ing_ves"] or CERO) - (datos["egr_ves"] or CERO), (datos["ing_usd"] or CERO) - (datos["egr_usd"] or CERO))


def conceptos_disponibles(membresia, tipo=None):
    qs = ConceptoPersonal.objects.filter(organizacion=membresia.organizacion_id, activo=True).filter(
        Q(membresia__isnull=True) | Q(membresia=membresia)
    )
    return qs.filter(tipo=tipo) if tipo else qs


def estadisticas(membresia, desde, hasta, moneda):
    """Indicadores y rankings de la cuenta personal en un período."""
    campo = "monto_usd" if moneda == "USD" else "monto_ves"
    base = vigentes(membresia).filter(fecha__gte=desde, fecha__lte=hasta)
    agg = base.aggregate(
        ingresos=Sum(campo, filter=Q(tipo="ingreso")), egresos=Sum(campo, filter=Q(tipo="egreso")),
        asignado=Sum(campo, filter=Q(origen__isnull=False)), n=Count("id"),
    )
    ingresos, egresos = agg["ingresos"] or CERO, agg["egresos"] or CERO

    def ranking(tipo, total):
        # Sin concepto, agrupa por lo que la persona escribió en la descripción.
        filas = (base.filter(tipo=tipo).annotate(rubro=Coalesce("concepto__nombre", "descripcion"))
                 .values("rubro").annotate(total=Sum(campo)).order_by("-total"))
        items = [(f["rubro"] or "Sin concepto", f["total"] or CERO) for f in filas][:8]
        tope = max((m for _, m in items), default=CERO)
        return [{"nombre": n, "monto": m, "pct": (m / total * 100) if total else None,
                 "ancho": f"{float(m / tope * 100) if tope else 0:.1f}"} for n, m in items]

    dias = (hasta - desde).days + 1
    return {
        "ingresos": ingresos, "egresos": egresos, "resultado": ingresos - egresos, "asignado": agg["asignado"] or CERO,
        "n": agg["n"], "egreso_diario": egresos / dias if dias else CERO,
        "gastado_pct": (egresos / ingresos * 100) if ingresos else None,
        "top_egresos": ranking("egreso", egresos), "top_ingresos": ranking("ingreso", ingresos),
    }


def serie_mensual(membresia, meses, moneda):
    """[(mes, ingresos, egresos)] de la cuenta personal para los meses dados."""
    campo = "monto_usd" if moneda == "USD" else "monto_ves"
    if not meses:
        return []
    datos = {}
    for f in (vigentes(membresia).filter(fecha__gte=meses[0])
              .values("fecha__year", "fecha__month", "tipo").annotate(total=Sum(campo))):
        datos[(f["fecha__year"], f["fecha__month"], f["tipo"])] = f["total"] or CERO
    return [(m, datos.get((m.year, m.month, "ingreso"), CERO), datos.get((m.year, m.month, "egreso"), CERO)) for m in meses]


def registrar_personal(movimiento):
    """Guarda un MovimientoPersonal nuevo o editado, con la tasa de su fecha."""
    try:
        movimiento.tasa, _ = tasa_para(movimiento.fecha)
    except SinTasaError:
        raise ValidationError("No hay ninguna tasa de cambio cargada para esa fecha ni antes.")
    movimiento.full_clean(exclude=["tasa_aplicada", "monto_ves", "monto_usd"])
    movimiento.save()
    return movimiento


@transaction.atomic
def asignar(*, destino, cuenta, monto, fecha, concepto, nota, actor):
    """El director entrega dinero de la organización a un miembro.

    Son dos registros en una sola operación: un egreso normal en el libro de
    la organización (para que la caja cuadre) y un ingreso en la cuenta
    personal del miembro, atado a ese egreso."""
    if destino.organizacion_id != actor.organizacion_id:
        raise ValidationError("Ese miembro es de otra organización.")
    if not destino.tiene_acceso or not destino.tiene_permiso("tiene_cuenta_personal"):
        raise ValidationError({"destino": "Ese miembro no tiene cuenta personal."})
    egreso = Movimiento(
        organizacion=actor.organizacion, tipo=Movimiento.Tipo.EGRESO, fecha=fecha, cuenta=cuenta, concepto=concepto,
        monto=monto, miembro=destino, descripcion=nota or ("" if concepto else f"Asignación a {destino.nombre}"),
    )
    egreso, _ = registrar_movimiento(egreso, membresia=actor)
    personal = MovimientoPersonal(
        organizacion=actor.organizacion, membresia=destino, tipo=MovimientoPersonal.Tipo.INGRESO, fecha=fecha,
        monto=monto, moneda=egreso.moneda, tasa=egreso.tasa, origen=egreso,
        descripcion=nota or "Asignación de la organización",
    )
    personal.save()
    return egreso, personal


def total_asignado(organizacion):
    """{membresia_id: (ves, usd, cantidad)} de asignaciones confirmadas. Es lo
    único que el director ve siempre: es dinero de la organización."""
    filas = (
        MovimientoPersonal.objects.filter(organizacion=organizacion, origen__estado=Movimiento.Estado.CONFIRMADO)
        .values("membresia_id").annotate(ves=Sum("monto_ves"), usd=Sum("monto_usd"), n=Count("id"))
    )
    return {f["membresia_id"]: (f["ves"] or CERO, f["usd"] or CERO, f["n"]) for f in filas}
