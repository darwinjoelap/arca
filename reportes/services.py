"""Construcción de los reportes. Cada función devuelve un `Reporte`.

Moneda: los reportes de un período se presentan en UNA moneda (USD o Bs.)
usando el equivalente congelado de cada movimiento, con la tasa del día en
que ocurrió (A-13). El libro de una cuenta es la excepción: va en la moneda
de la cuenta, que es exacta.

Solo cuentan los movimientos confirmados: ni los anulados ni los que esperan
aprobación.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum

from finanzas.models import Concepto, Movimiento, Traslado
from presupuestos.services import comparativo as comparativo_presupuesto
from presupuestos.services import meses_del_ejercicio

from .estructura import (
    ENTERO, FECHA, GRUPO, MONTO, NORMAL, PORCENTAJE, SECCION, SUBTOTAL, TEXTO, TOTAL, Columna, Fila, Reporte,
)

CERO = Decimal("0")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
SIMBOLO = {"USD": "$", "VES": "Bs."}


def nombre_mes(fecha, con_anio=True):
    texto = MESES[fecha.month - 1].capitalize()
    return f"{texto} {fecha.year}" if con_anio else texto


def _campo(moneda):
    return "monto_usd" if moneda == "USD" else "monto_ves"


def _pct(parte, total):
    return (parte / total * 100) if total else None


def _base(organizacion, desde, hasta, caja=None):
    qs = Movimiento.objects.filter(
        organizacion=organizacion, estado=Movimiento.Estado.CONFIRMADO, fecha__gte=desde, fecha__lte=hasta,
    )
    return qs.filter(caja=caja) if caja else qs


def _periodo(desde, hasta):
    return f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"


def _alcance(caja, moneda):
    return f"{'Caja: ' + caja.nombre if caja else 'Todas las cajas'} · Expresado en {SIMBOLO[moneda]}"


# --- Totales por concepto (la base de varios reportes) ----------------------


def totales_por_concepto(organizacion, desde, hasta, caja, moneda):
    """{"ingreso": [(grupo, nombre, monto, cantidad)], "egreso": [...]} ordenado.
    `grupo` es el concepto padre o "" ; los movimientos sin concepto van como
    «Otros (sin concepto)»."""
    filas = (
        _base(organizacion, desde, hasta, caja)
        .values("tipo", "concepto_id", "concepto__nombre", "concepto__padre__nombre")
        .annotate(total=Sum(_campo(moneda)), cantidad=Count("id"))
    )
    resultado = {"ingreso": [], "egreso": []}
    for f in filas:
        nombre = f["concepto__nombre"] or "Otros (sin concepto)"
        resultado[f["tipo"]].append((f["concepto__padre__nombre"] or "", nombre, f["total"] or CERO, f["cantidad"]))
    for lista in resultado.values():
        lista.sort(key=lambda x: (x[1].startswith("Otros (sin"), (x[0] or x[1]).lower(), bool(x[0]), x[1].lower()))
    return resultado


def _bloque_conceptos(filas, items, total_del_tipo, extra=lambda monto: []):
    """Agrega a `filas` los conceptos agrupados bajo su padre, con subtotal de grupo."""
    grupo_actual, acumulado_grupo = None, CERO

    def cerrar():
        if grupo_actual:
            filas.append(Fila([f"Total {grupo_actual}", acumulado_grupo, _pct(acumulado_grupo, total_del_tipo),
                               *extra(acumulado_grupo)], SUBTOTAL, sangria=1))

    for grupo, nombre, monto, _cantidad in items:
        if grupo != grupo_actual:
            cerrar()
            grupo_actual, acumulado_grupo = grupo, CERO
            if grupo:
                filas.append(Fila([grupo] + [None] * (2 + len(extra(CERO))), GRUPO, sangria=1))
        acumulado_grupo += monto
        filas.append(Fila([nombre, monto, _pct(monto, total_del_tipo), *extra(monto)], NORMAL, sangria=2 if grupo else 1))
    cerrar()


# --- 1. Estado de ingresos y egresos ---------------------------------------


def estado_ingresos_egresos(organizacion, desde, hasta, caja, moneda):
    datos = totales_por_concepto(organizacion, desde, hasta, caja, moneda)
    total_ing = sum((m for _, _, m, _ in datos["ingreso"]), CERO)
    total_egr = sum((m for _, _, m, _ in datos["egreso"]), CERO)
    filas = [Fila(["INGRESOS", None, None], SECCION)]
    _bloque_conceptos(filas, datos["ingreso"], total_ing)
    filas.append(Fila(["Total ingresos", total_ing, Decimal("100") if total_ing else None], TOTAL))
    filas.append(Fila(["EGRESOS", None, None], SECCION))
    _bloque_conceptos(filas, datos["egreso"], total_egr)
    filas.append(Fila(["Total egresos", total_egr, Decimal("100") if total_egr else None], TOTAL))
    resultado = total_ing - total_egr
    filas.append(Fila(
        ["RESULTADO DEL PERÍODO (ingresos − egresos)", resultado, None], TOTAL,
        tonos={1: "bien" if resultado > 0 else "mal" if resultado < 0 else ""},
    ))
    return Reporte(
        clave="estado", titulo="Estado de ingresos y egresos",
        subtitulo=f"{_periodo(desde, hasta)} · {_alcance(caja, moneda)}",
        columnas=[Columna("Concepto", TEXTO, 4), Columna(f"Monto ({SIMBOLO[moneda]})", MONTO, 1.6),
                  Columna("% del total", PORCENTAJE, 1)],
        filas=filas,
        notas=["Cada movimiento se expresa con la tasa de cambio del día en que se registró.",
               "Los traslados entre cuentas no son ingresos ni egresos y no aparecen aquí."],
        firmas=["Elaborado por", "Revisado por"],
    )


# --- 2. Comparativo con el período anterior --------------------------------


def comparativo_periodos(organizacion, desde, hasta, caja, moneda):
    """El mismo período contra el inmediatamente anterior de igual duración."""
    dias = (hasta - desde).days + 1
    antes_hasta, antes_desde = desde - timedelta(days=1), desde - timedelta(days=dias)
    actual = totales_por_concepto(organizacion, desde, hasta, caja, moneda)
    anterior = totales_por_concepto(organizacion, antes_desde, antes_hasta, caja, moneda)

    filas, totales = [], {}
    for tipo, titulo in (("ingreso", "INGRESOS"), ("egreso", "EGRESOS")):
        a = {(g, n): m for g, n, m, _ in actual[tipo]}
        b = {(g, n): m for g, n, m, _ in anterior[tipo]}
        claves = sorted(set(a) | set(b), key=lambda k: (k[1].startswith("Otros (sin"), (k[0] or k[1]).lower(), k[1].lower()))
        filas.append(Fila([titulo, None, None, None, None], SECCION))
        ta = tb = CERO
        for clave in claves:
            ma, mb = a.get(clave, CERO), b.get(clave, CERO)
            ta, tb = ta + ma, tb + mb
            var = ma - mb
            bien = (var < 0) if tipo == "egreso" else (var > 0)
            nombre = f"{clave[0]} › {clave[1]}" if clave[0] else clave[1]
            filas.append(Fila([nombre, ma, mb, var, _pct(var, mb)], NORMAL, sangria=1,
                              tonos={3: ("bien" if bien else "mal") if var else ""}))
        var = ta - tb
        bien = (var < 0) if tipo == "egreso" else (var > 0)
        filas.append(Fila([f"Total {titulo.lower()}", ta, tb, var, _pct(var, tb)], TOTAL,
                          tonos={3: ("bien" if bien else "mal") if var else ""}))
        totales[tipo] = (ta, tb)
    ra, rb = totales["ingreso"][0] - totales["egreso"][0], totales["ingreso"][1] - totales["egreso"][1]
    filas.append(Fila(["RESULTADO", ra, rb, ra - rb, None], TOTAL, tonos={3: "bien" if ra > rb else "mal" if ra < rb else ""}))
    return Reporte(
        clave="variacion", titulo="Variación contra el período anterior",
        subtitulo=f"{_periodo(desde, hasta)} contra {antes_desde:%d/%m/%Y}–{antes_hasta:%d/%m/%Y} · {_alcance(caja, moneda)}",
        columnas=[Columna("Concepto", TEXTO, 3.4), Columna("Este período", MONTO, 1.4), Columna("Período anterior", MONTO, 1.4),
                  Columna("Variación", MONTO, 1.3), Columna("Variación %", PORCENTAJE, 1)],
        filas=filas,
        notas=["El período anterior tiene la misma cantidad de días que el consultado.",
               "En verde, lo favorable: más ingresos o menos egresos. Sin porcentaje cuando el período anterior fue cero."],
    )


# --- 3. Por miembro ---------------------------------------------------------


def por_miembro(organizacion, desde, hasta, caja, moneda):
    campo = _campo(moneda)
    filas_bd = (
        _base(organizacion, desde, hasta, caja)
        .values("miembro_id", "miembro__nombre_visible", "miembro__user__username", "miembro__tipo__nombre",
                "miembro__es_dueno", "miembro__es_administrador")
        .annotate(
            aporto=Sum(campo, filter=Q(tipo="ingreso")), recibio=Sum(campo, filter=Q(tipo="egreso")),
            cantidad=Count("id"),
        )
    )
    personas, otros = [], None
    for f in filas_bd:
        aporto, recibio = f["aporto"] or CERO, f["recibio"] or CERO
        if f["miembro_id"] is None:
            otros = (aporto, recibio, f["cantidad"])
            continue
        rol = "Director" if f["miembro__es_dueno"] else "Administrador" if f["miembro__es_administrador"] else (f["miembro__tipo__nombre"] or "—")
        personas.append((f["miembro__nombre_visible"] or f["miembro__user__username"], rol, aporto, recibio, f["cantidad"]))
    personas.sort(key=lambda p: p[0].lower())

    filas, ta, tr, tc = [], CERO, CERO, 0
    for nombre, rol, aporto, recibio, cantidad in personas:
        filas.append(Fila([nombre, rol, aporto, recibio, aporto - recibio, cantidad]))
        ta, tr, tc = ta + aporto, tr + recibio, tc + cantidad
    if personas:
        filas.append(Fila(["Subtotal miembros", None, ta, tr, ta - tr, tc], SUBTOTAL))
    if otros:
        filas.append(Fila(["Terceros y movimientos sin miembro", "—", otros[0], otros[1], otros[0] - otros[1], otros[2]]))
        ta, tr, tc = ta + otros[0], tr + otros[1], tc + otros[2]
    filas.append(Fila(["Total", None, ta, tr, ta - tr, tc], TOTAL))
    return Reporte(
        clave="miembros", titulo="Ingresos y egresos por miembro",
        subtitulo=f"{_periodo(desde, hasta)} · {_alcance(caja, moneda)}",
        columnas=[Columna("Miembro", TEXTO, 3), Columna("Tipo", TEXTO, 1.6), Columna("Aportó", MONTO, 1.3),
                  Columna("Recibió", MONTO, 1.3), Columna("Neto", MONTO, 1.3), Columna("Mov.", ENTERO, 0.7)],
        filas=filas,
        notas=["«Aportó»: ingresos de la organización en los que figura el miembro. «Recibió»: egresos entregados a su nombre.",
               "Es dinero de la organización. Las cuentas personales de los miembros no forman parte de este reporte."],
    )


# --- 4. Flujo mensual del ejercicio -----------------------------------------


def serie_mensual(organizacion, ejercicio, caja, moneda):
    """[(primer día del mes, ingresos, egresos)] para cada mes del ejercicio."""
    campo = _campo(moneda)
    datos = {}
    for f in (
        _base(organizacion, ejercicio.fecha_inicio, ejercicio.fecha_fin, caja)
        .values("fecha__year", "fecha__month", "tipo").annotate(total=Sum(campo))
    ):
        datos[(f["fecha__year"], f["fecha__month"], f["tipo"])] = f["total"] or CERO
    return [
        (mes, datos.get((mes.year, mes.month, "ingreso"), CERO), datos.get((mes.year, mes.month, "egreso"), CERO))
        for mes in meses_del_ejercicio(ejercicio)
    ]


def flujo_mensual(organizacion, ejercicio, caja, moneda, hoy=None):
    filas, ti, te, acumulado = [], CERO, CERO, CERO
    for mes, ing, egr in serie_mensual(organizacion, ejercicio, caja, moneda):
        futuro = hoy is not None and mes > hoy
        acumulado += ing - egr
        ti, te = ti + ing, te + egr
        resultado = ing - egr
        filas.append(Fila(
            [nombre_mes(mes), None if futuro else ing, None if futuro else egr, None if futuro else resultado,
             None if futuro else acumulado],
            tonos={3: "bien" if resultado > 0 else "mal" if resultado < 0 else ""},
        ))
    filas.append(Fila([f"Total {ejercicio.nombre}", ti, te, ti - te, None], TOTAL))
    return Reporte(
        clave="flujo", titulo="Flujo mensual de ingresos y egresos",
        subtitulo=f"Ejercicio {ejercicio.nombre} · {_alcance(caja, moneda)}",
        columnas=[Columna("Mes", TEXTO, 2), Columna("Ingresos", MONTO, 1.4), Columna("Egresos", MONTO, 1.4),
                  Columna("Resultado del mes", MONTO, 1.5), Columna("Resultado acumulado", MONTO, 1.6)],
        filas=filas,
        notas=["El resultado acumulado es la suma de los resultados mensuales; no incluye los saldos iniciales de las cuentas."],
    )


# --- 5. Presupuesto contra real ---------------------------------------------


def presupuesto_vs_real(presupuesto, mes):
    c = comparativo_presupuesto(presupuesto, mes)
    filas = []

    def tono(linea, variacion):
        bien = linea.favorable(variacion)
        return "" if bien is None else ("bien" if bien else "mal")

    for tipo, titulo, lineas in (("ingreso", "INGRESOS", c.ingresos), ("egreso", "EGRESOS", c.egresos)):
        filas.append(Fila([titulo] + [None] * 8, SECCION))
        grupo = None
        for l in lineas:
            if l.grupo != grupo:
                grupo = l.grupo
                if grupo:
                    filas.append(Fila([grupo] + [None] * 8, GRUPO, sangria=1))
            nombre = l.nombre + (" *" if l.requiere_solicitud else "") + ("" if l.tiene_partida or l.concepto is None else " (sin partida)")
            filas.append(Fila(
                [nombre, l.presupuesto_mes, l.real_mes, l.variacion_mes, l.pct_mes,
                 l.presupuesto_acumulado, l.real_acumulado, l.variacion_acumulada, l.pct_acumulado],
                NORMAL, sangria=2 if l.grupo else 1,
                tonos={3: tono(l, l.variacion_mes), 7: tono(l, l.variacion_acumulada)},
            ))
        pm, rm = c.total(tipo, "presupuesto_mes"), c.total(tipo, "real_mes")
        pa, ra = c.total(tipo, "presupuesto_acumulado"), c.total(tipo, "real_acumulado")
        filas.append(Fila([f"Total {titulo.lower()}", pm, rm, rm - pm, _pct(rm, pm), pa, ra, ra - pa, _pct(ra, pa)], TOTAL))
    pm, rm = c.resultado("presupuesto_mes"), c.resultado("real_mes")
    pa, ra = c.resultado("presupuesto_acumulado"), c.resultado("real_acumulado")
    filas.append(Fila(["RESULTADO (ingresos − egresos)", pm, rm, rm - pm, None, pa, ra, ra - pa, None], TOTAL,
                      tonos={3: "bien" if rm > pm else "mal" if rm < pm else "", 7: "bien" if ra > pa else "mal" if ra < pa else ""}))
    s = SIMBOLO[presupuesto.moneda]
    notas = [f"Acumulado: {c.meses} mes(es) del ejercicio {presupuesto.ejercicio.nombre}, hasta {nombre_mes(c.mes).lower()}.",
             "«% ejec.» es lo real sobre lo presupuestado. En verde, lo favorable: menos egresos o más ingresos que lo previsto."]
    if any(l.requiere_solicitud for l in c.ingresos + c.egresos):
        notas.append("* Partida que se solicita con antelación indicando el monto exacto.")
    if presupuesto.estado != presupuesto.Estado.APROBADO:
        notas.append("Este presupuesto es un BORRADOR: todavía no ha sido aprobado.")
    return Reporte(
        clave="presupuesto", titulo="Presupuesto contra real",
        subtitulo=f"{presupuesto.caja.nombre} · Ejercicio {presupuesto.ejercicio.nombre} · {nombre_mes(c.mes)} · Expresado en {s}",
        columnas=[Columna("Concepto", TEXTO, 3.2), Columna("Presup. mes", MONTO, 1.2), Columna("Real mes", MONTO, 1.2),
                  Columna("Variación", MONTO, 1.2), Columna("% ejec.", PORCENTAJE, 0.9),
                  Columna("Presup. acum.", MONTO, 1.3), Columna("Real acum.", MONTO, 1.3),
                  Columna("Variación", MONTO, 1.2), Columna("% ejec.", PORCENTAJE, 0.9)],
        filas=filas, notas=notas, horizontal=True, firmas=["Elaborado por", "Aprobado por"],
    )


# --- 6. Libro de una cuenta (auxiliar de caja o banco) ----------------------


def _neto_hasta(cuenta, antes_de):
    """Saldo de la cuenta al cierre del día anterior a `antes_de`."""
    saldo = cuenta.saldo_inicial
    for f in (Movimiento.objects.filter(cuenta=cuenta, estado="confirmado", fecha__lt=antes_de)
              .values("tipo").annotate(total=Sum("monto"))):
        saldo += f["total"] if f["tipo"] == "ingreso" else -f["total"]
    t = Traslado.objects.filter(estado="confirmado", fecha__lt=antes_de)
    saldo -= t.filter(cuenta_origen=cuenta).aggregate(s=Sum("monto_origen"))["s"] or CERO
    saldo += t.filter(cuenta_destino=cuenta).aggregate(s=Sum("monto_destino"))["s"] or CERO
    return saldo


def libro_cuenta(cuenta, desde, hasta):
    """Movimientos y traslados de la cuenta en orden, con saldo corrido, en SU moneda."""
    saldo = _neto_hasta(cuenta, desde)
    asientos = []
    for m in (Movimiento.objects.filter(cuenta=cuenta, estado="confirmado", fecha__gte=desde, fecha__lte=hasta)
              .select_related("concepto", "concepto__padre", "miembro", "miembro__user")):
        asientos.append((m.fecha, 0, m.pk, str(m.numero_vale), m.titulo + (f" — {m.descripcion}" if m.concepto_id and m.descripcion else ""),
                         m.nombre_persona, m.monto if m.es_ingreso else CERO, CERO if m.es_ingreso else m.monto))
    traslados = Traslado.objects.filter(estado="confirmado", fecha__gte=desde, fecha__lte=hasta).select_related(
        "cuenta_origen", "cuenta_origen__caja", "cuenta_destino", "cuenta_destino__caja")
    for t in traslados.filter(cuenta_destino=cuenta):
        asientos.append((t.fecha, 1, t.pk, "T", f"Traslado desde {t.cuenta_origen.caja.nombre} · {t.cuenta_origen.nombre}",
                         t.descripcion, t.monto_destino, CERO))
    for t in traslados.filter(cuenta_origen=cuenta):
        asientos.append((t.fecha, 1, t.pk, "T", f"Traslado a {t.cuenta_destino.caja.nombre} · {t.cuenta_destino.nombre}",
                         t.descripcion, CERO, t.monto_origen))
    asientos.sort(key=lambda a: a[:3])

    filas = [Fila([None, None, "Saldo anterior", None, None, None, saldo], SUBTOTAL)]
    te = ts = CERO
    for fecha, _o, _pk, vale, detalle, persona, entra, sale in asientos:
        saldo += entra - sale
        te, ts = te + entra, ts + sale
        filas.append(Fila([fecha, vale, detalle, persona or "", entra or None, sale or None, saldo],
                          tonos={6: "mal"} if saldo < 0 else {}))
    filas.append(Fila([None, None, "Totales del período y saldo final", None, te, ts, saldo], TOTAL))
    s = SIMBOLO[cuenta.moneda]
    return Reporte(
        clave="libro", titulo=f"Libro de {'banco' if cuenta.tipo == 'banco' else 'caja'}: {cuenta.nombre}",
        subtitulo=f"{cuenta.caja.nombre} · {_periodo(desde, hasta)} · Expresado en {s} (moneda de la cuenta)",
        columnas=[Columna("Fecha", FECHA, 1), Columna("Vale", TEXTO, 0.6), Columna("Detalle", TEXTO, 3.4),
                  Columna("Nombre", TEXTO, 1.8), Columna("Entradas", MONTO, 1.2), Columna("Salidas", MONTO, 1.2),
                  Columna("Saldo", MONTO, 1.3)],
        filas=filas, horizontal=True,
        notas=["Saldo exacto en la moneda de la cuenta, sin conversiones. «T» identifica un traslado entre cuentas."],
        firmas=["Elaborado por", "Revisado por"],
    )


# --- 7. Libro diario (todos los movimientos, en ambas monedas) ---------------


def libro_diario(organizacion, desde, hasta, caja, moneda):
    filas, ti, te = [], CERO, CERO
    campo = _campo(moneda)
    for m in (_base(organizacion, desde, hasta, caja).order_by("fecha", "id")
              .select_related("caja", "cuenta", "concepto", "concepto__padre", "miembro", "miembro__user")):
        equivalente = getattr(m, campo)
        ti, te = (ti + equivalente, te) if m.es_ingreso else (ti, te + equivalente)
        filas.append(Fila([
            m.fecha, str(m.numero_vale), f"{m.caja.nombre} · {m.cuenta.nombre}", m.titulo, m.nombre_persona or "",
            f"{SIMBOLO[m.moneda]} {m.monto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            m.tasa_aplicada, equivalente if m.es_ingreso else None, None if m.es_ingreso else equivalente,
        ]))
    filas.append(Fila([None, None, None, "Totales", None, None, None, ti, te], TOTAL))
    filas.append(Fila([None, None, None, "Resultado del período", None, None, None, ti - te, None], TOTAL))
    return Reporte(
        clave="diario", titulo="Libro diario de ingresos y egresos",
        subtitulo=f"{_periodo(desde, hasta)} · {_alcance(caja, moneda)}",
        columnas=[Columna("Fecha", FECHA, 0.9), Columna("Vale", TEXTO, 0.5), Columna("Caja · Cuenta", TEXTO, 1.8),
                  Columna("Concepto", TEXTO, 2.4), Columna("Nombre", TEXTO, 1.6), Columna("Monto original", TEXTO, 1.4),
                  Columna("Tasa", MONTO, 0.9), Columna(f"Ingreso ({SIMBOLO[moneda]})", MONTO, 1.2),
                  Columna(f"Egreso ({SIMBOLO[moneda]})", MONTO, 1.2)],
        filas=filas, horizontal=True,
        notas=["«Monto original» es lo registrado en la moneda de la cuenta; «Tasa» es Bs. por dólar del día del movimiento."],
        firmas=["Elaborado por", "Revisado por"],
    )


# --- Análisis (panel con indicadores y gráficos) ----------------------------


def analisis(organizacion, ejercicio, desde, hasta, caja, moneda):
    """Los datos del panel de análisis: indicadores, series y rankings."""
    campo = _campo(moneda)
    base = _base(organizacion, desde, hasta, caja)
    agg = base.aggregate(
        ingresos=Sum(campo, filter=Q(tipo="ingreso")), egresos=Sum(campo, filter=Q(tipo="egreso")),
        n_ingresos=Count("id", filter=Q(tipo="ingreso")), n_egresos=Count("id", filter=Q(tipo="egreso")),
    )
    ingresos, egresos = agg["ingresos"] or CERO, agg["egresos"] or CERO
    dias = (hasta - desde).days + 1

    antes_hasta, antes_desde = desde - timedelta(days=1), desde - timedelta(days=dias)
    previo = _base(organizacion, antes_desde, antes_hasta, caja).aggregate(
        ingresos=Sum(campo, filter=Q(tipo="ingreso")), egresos=Sum(campo, filter=Q(tipo="egreso")))
    prev_ing, prev_egr = previo["ingresos"] or CERO, previo["egresos"] or CERO

    conceptos = totales_por_concepto(organizacion, desde, hasta, caja, moneda)

    def ranking(items, total, maximo=8):
        """Top de conceptos por monto; el resto se agrupa en «Otros conceptos»."""
        ordenados = sorted(((f"{g} › {n}" if g else n, m) for g, n, m, _ in items), key=lambda x: -x[1])
        cabeza, cola = ordenados[:maximo], ordenados[maximo:]
        if cola:
            cabeza.append((f"Otros conceptos ({len(cola)})", sum((m for _, m in cola), CERO)))
        mayor = max((m for _, m in cabeza), default=CERO)
        return [{"nombre": n, "monto": m, "pct": _pct(m, total), "ancho": f"{float(m / mayor * 100) if mayor else 0:.1f}"}
                for n, m in cabeza]

    mayor_egreso = base.filter(tipo="egreso").order_by(f"-{campo}").select_related("concepto", "concepto__padre").first()

    miembros = (
        base.filter(miembro__isnull=False, tipo="ingreso")
        .values("miembro__nombre_visible", "miembro__user__username").annotate(total=Sum(campo)).order_by("-total")[:6]
    )
    tope = max((m["total"] or CERO for m in miembros), default=CERO)

    return {
        "ingresos": ingresos, "egresos": egresos, "resultado": ingresos - egresos,
        "n_ingresos": agg["n_ingresos"], "n_egresos": agg["n_egresos"],
        "egreso_diario": egresos / dias if dias else CERO, "dias": dias,
        "ahorro_pct": _pct(ingresos - egresos, ingresos),
        "var_ingresos": _pct(ingresos - prev_ing, prev_ing), "var_egresos": _pct(egresos - prev_egr, prev_egr),
        "previo": (antes_desde, antes_hasta, prev_ing, prev_egr),
        "top_egresos": ranking(conceptos["egreso"], egresos), "top_ingresos": ranking(conceptos["ingreso"], ingresos),
        "mayor_egreso": mayor_egreso, "mayor_egreso_monto": getattr(mayor_egreso, campo) if mayor_egreso else None,
        "aportantes": [
            {"nombre": m["miembro__nombre_visible"] or m["miembro__user__username"], "monto": m["total"],
             "pct": _pct(m["total"], ingresos), "ancho": f"{float(m['total'] / tope * 100) if tope else 0:.1f}"}
            for m in miembros
        ],
        "serie": serie_mensual(organizacion, ejercicio, caja, moneda) if ejercicio else [],
    }
