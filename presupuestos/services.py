"""Cálculo de lo presupuestado contra lo ejecutado."""

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum

from finanzas.models import Concepto, Movimiento

CERO = Decimal("0")


def conceptos_de_la_caja(presupuesto):
    """Los conceptos que pueden tener partida: los de esa caja y los generales."""
    return (
        Concepto.objects.filter(organizacion=presupuesto.organizacion_id)
        .filter(Q(caja__isnull=True) | Q(caja=presupuesto.caja_id))
        .select_related("padre")
    )


def fin_de_mes(fecha):
    return fecha.replace(day=calendar.monthrange(fecha.year, fecha.month)[1])


def meses_transcurridos(ejercicio, hasta):
    """Cuántos meses del ejercicio cuentan hasta `hasta` (incluido su mes)."""
    hasta = min(hasta, ejercicio.fecha_fin)
    if hasta < ejercicio.fecha_inicio:
        return 0
    return (hasta.year - ejercicio.fecha_inicio.year) * 12 + hasta.month - ejercicio.fecha_inicio.month + 1


def meses_del_ejercicio(ejercicio):
    """Lista de fechas (día 1) de cada mes del ejercicio."""
    meses, actual = [], ejercicio.fecha_inicio.replace(day=1)
    while actual <= ejercicio.fecha_fin:
        meses.append(actual)
        actual = date(actual.year + (actual.month == 12), actual.month % 12 + 1, 1)
    return meses


def ejecutado_por_concepto(presupuesto, desde, hasta):
    """{concepto_id o None: monto} de movimientos confirmados de la caja, en
    la moneda del presupuesto. None agrupa los movimientos sin concepto."""
    campo = "monto_usd" if presupuesto.moneda == "USD" else "monto_ves"
    filas = (
        Movimiento.objects.filter(
            organizacion=presupuesto.organizacion_id, caja=presupuesto.caja_id,
            estado=Movimiento.Estado.CONFIRMADO, fecha__gte=desde, fecha__lte=hasta,
        )
        .values("concepto_id", "tipo")
        .annotate(total=Sum(campo))
    )
    return {(f["concepto_id"], f["tipo"]): f["total"] or CERO for f in filas}


@dataclass
class Linea:
    """Una fila del comparativo: un concepto, o los movimientos sin concepto."""

    concepto: object  # Concepto o None
    tipo: str
    nombre: str
    grupo: str = ""           # nombre del concepto padre, si lo tiene
    presupuesto_mes: Decimal = CERO
    real_mes: Decimal = CERO
    presupuesto_acumulado: Decimal = CERO
    real_acumulado: Decimal = CERO
    requiere_solicitud: bool = False
    nota: str = ""
    tiene_partida: bool = False

    def _variacion(self, real, plan):
        return real - plan

    @property
    def variacion_mes(self):
        return self.real_mes - self.presupuesto_mes

    @property
    def variacion_acumulada(self):
        return self.real_acumulado - self.presupuesto_acumulado

    @staticmethod
    def _pct(real, plan):
        return (real / plan * 100) if plan else None

    @property
    def pct_mes(self):
        return self._pct(self.real_mes, self.presupuesto_mes)

    @property
    def pct_acumulado(self):
        return self._pct(self.real_acumulado, self.presupuesto_acumulado)

    def favorable(self, variacion):
        """En egresos es bueno gastar menos; en ingresos, recibir más. None si no hay desvío."""
        if not variacion:
            return None
        return variacion < 0 if self.tipo == "egreso" else variacion > 0


@dataclass
class Comparativo:
    presupuesto: object
    mes: date
    meses: int
    ingresos: list = field(default_factory=list)
    egresos: list = field(default_factory=list)

    def total(self, tipo, atributo):
        return sum((getattr(l, atributo) for l in (self.ingresos if tipo == "ingreso" else self.egresos)), CERO)

    def resultado(self, atributo):
        return self.total("ingreso", atributo) - self.total("egreso", atributo)


def comparativo(presupuesto, mes):
    """Presupuesto contra real del mes de `mes` y acumulado desde el inicio
    del ejercicio hasta el fin de ese mes. Incluye lo ejecutado en conceptos
    sin partida (y sin concepto): es justo lo que conviene ver."""
    ejercicio = presupuesto.ejercicio
    inicio_mes = mes.replace(day=1)
    fin = min(fin_de_mes(mes), ejercicio.fecha_fin)
    n = meses_transcurridos(ejercicio, fin)

    del_mes = ejecutado_por_concepto(presupuesto, max(inicio_mes, ejercicio.fecha_inicio), fin)
    acumulado = ejecutado_por_concepto(presupuesto, ejercicio.fecha_inicio, fin)

    partidas = {p.concepto_id: p for p in presupuesto.partidas.select_related("concepto", "concepto__padre")}
    conceptos = {c.pk: c for c in conceptos_de_la_caja(presupuesto)}
    for p in partidas.values():
        conceptos.setdefault(p.concepto_id, p.concepto)
    for concepto_id, _tipo in acumulado:
        if concepto_id and concepto_id not in conceptos:
            conceptos[concepto_id] = Concepto.objects.select_related("padre").get(pk=concepto_id)

    resultado = Comparativo(presupuesto=presupuesto, mes=inicio_mes, meses=n)
    for concepto in conceptos.values():
        partida = partidas.get(concepto.pk)
        clave = (concepto.pk, concepto.tipo)
        linea = Linea(
            concepto=concepto, tipo=concepto.tipo, nombre=concepto.nombre,
            grupo=concepto.padre.nombre if concepto.padre_id else "",
            presupuesto_mes=partida.monto_mensual if partida else CERO,
            presupuesto_acumulado=(partida.monto_mensual * n) if partida else CERO,
            real_mes=del_mes.get(clave, CERO), real_acumulado=acumulado.get(clave, CERO),
            requiere_solicitud=bool(partida and partida.requiere_solicitud),
            nota=partida.nota if partida else "", tiene_partida=partida is not None,
        )
        # Sin partida y sin nada ejecutado: no aporta al reporte.
        if not linea.tiene_partida and not linea.real_acumulado and not linea.real_mes:
            continue
        (resultado.ingresos if concepto.tipo == "ingreso" else resultado.egresos).append(linea)

    for tipo, lista in (("ingreso", resultado.ingresos), ("egreso", resultado.egresos)):
        sin_concepto = acumulado.get((None, tipo), CERO)
        if sin_concepto:
            lista.append(Linea(
                concepto=None, tipo=tipo, nombre="Otros (sin concepto)",
                real_mes=del_mes.get((None, tipo), CERO), real_acumulado=sin_concepto,
            ))
        lista.sort(key=lambda l: (l.concepto is None, (l.grupo or l.nombre).lower(), bool(l.grupo), l.nombre.lower()))
    return resultado
