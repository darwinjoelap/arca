"""Reportes del inventario. Devuelven un `Reporte` (reportes/estructura.py),
así que salen en pantalla, Excel y PDF con el mismo código que los demás."""

from decimal import Decimal

from cambio.services import convertir
from reportes.estructura import ENTERO, FECHA, GRUPO, MONTO, SUBTOTAL, TEXTO, TOTAL, Columna, Fila, Reporte

from . import services
from .models import Articulo, MovimientoInventario, Ubicacion

CERO = Decimal("0")
SIMBOLO = {"USD": "$", "VES": "Bs."}
FIRMAS = ["Elaborado por", "Revisado por"]

# clave -> (título, descripción, icono, filtros que usa)
CATALOGO = {
    "existencias": ("Inventario valorizado", "Todo lo que hay, por categoría, con cantidad y valor.",
                    "bi-box-seam", ("clase", "ubicacion", "moneda")),
    "ubicaciones": ("Inventario por ubicación", "Qué hay en cada lugar. Sirve como hoja de conteo.",
                    "bi-geo-alt", ("clase", "ubicacion", "moneda")),
    "reponer": ("Consumibles por reponer", "Los que están en su mínimo o por debajo, y cuánto falta.",
                "bi-exclamation-triangle", ()),
    "movimientos": ("Movimientos de inventario", "Entradas, salidas y traslados de un período.",
                    "bi-arrow-left-right", ("periodo", "articulo")),
}


def _valor(articulo, cantidad, moneda, tasa):
    """Valor de `cantidad` unidades en `moneda`, o None si no se puede calcular."""
    if articulo.valor_unitario is None:
        return None
    total = articulo.valor_unitario * cantidad
    if articulo.moneda == moneda:
        return total
    if tasa is None:
        return None
    ves, usd = convertir(total, articulo.moneda, tasa.valor)
    return usd if moneda == "USD" else ves


def _articulos(organizacion, clase):
    qs = Articulo.objects.filter(organizacion=organizacion, activo=True).select_related("categoria", "responsable", "responsable__user")
    return qs.filter(clase=clase) if clase in Articulo.Clase.values else qs


def _alcance(clase, ubicacion, moneda, tasa):
    partes = [{"bien": "Solo bienes", "consumible": "Solo consumibles"}.get(clase, "Bienes y consumibles"),
              f"Ubicación: {ubicacion.nombre}" if ubicacion else "Todas las ubicaciones", f"Valores en {SIMBOLO[moneda]}"]
    if tasa is not None:
        partes.append(f"tasa Bs. {tasa.valor:.2f} del {tasa.fecha:%d/%m/%Y}")
    return " · ".join(partes)


def _notas_valor(sin_valor):
    notas = ["El valor es informativo: cantidad por el valor por unidad cargado en cada artículo. No es dinero del libro de caja."]
    if sin_valor:
        notas.append(f"{sin_valor} artículo(s) con existencia no tienen valor cargado o no se pudieron convertir: no suman al total.")
    return notas


def existencias(organizacion, hoy, clase="", ubicacion=None, moneda="USD", tasa=None):
    saldo = services.existencias(organizacion)
    grupos, sin_valor = {}, 0
    for a in _articulos(organizacion, clase):
        if ubicacion is not None:
            cantidad = saldo.get((a.pk, ubicacion.pk), CERO)
            if not cantidad:
                continue
        else:
            cantidad = sum((c for (art, _), c in saldo.items() if art == a.pk), CERO)
        valor = _valor(a, cantidad, moneda, tasa)
        sin_valor += valor is None and cantidad > 0
        grupos.setdefault(a.categoria.nombre if a.categoria_id else "Sin categoría", []).append((a, cantidad, valor))

    filas, total = [], CERO
    for nombre in sorted(grupos, key=lambda n: (n == "Sin categoría", n.lower())):
        filas.append(Fila([nombre, None, None, None, None, None, None], GRUPO))
        sub = CERO
        for a, cantidad, valor in sorted(grupos[nombre], key=lambda x: x[0].nombre.lower()):
            unitario = _valor(a, Decimal("1"), moneda, tasa)
            bajo = a.es_consumible and a.minimo is not None and ubicacion is None and cantidad <= a.minimo
            filas.append(Fila([a.nombre, a.get_clase_display(), a.unidad, cantidad, a.minimo, unitario, valor],
                              sangria=1, tonos={3: "mal"} if bajo else {}))
            sub += valor or CERO
        filas.append(Fila([f"Total {nombre}", None, None, None, None, None, sub], SUBTOTAL))
        total += sub
    filas.append(Fila(["Valor total del inventario", None, None, None, None, None, total], TOTAL))
    return Reporte(
        clave="inv-existencias", titulo="Inventario valorizado",
        subtitulo=f"Al {hoy:%d/%m/%Y} · {_alcance(clase, ubicacion, moneda, tasa)}",
        columnas=[Columna("Artículo", TEXTO, 3.2), Columna("Clase", TEXTO, 1.2), Columna("Unidad", TEXTO, 0.9),
                  Columna("Existencia", MONTO, 1.1), Columna("Mínimo", MONTO, 0.9),
                  Columna("Valor unit.", MONTO, 1.1), Columna("Valor total", MONTO, 1.3)],
        filas=filas, firmas=FIRMAS,
        notas=_notas_valor(sin_valor) + ["En rojo: consumibles en su mínimo o por debajo."],
    )


def por_ubicacion(organizacion, hoy, clase="", ubicacion=None, moneda="USD", tasa=None):
    saldo = services.existencias(organizacion)
    articulos = {a.pk: a for a in _articulos(organizacion, clase)}
    ubicaciones = Ubicacion.objects.filter(organizacion=organizacion)
    if ubicacion is not None:
        ubicaciones = ubicaciones.filter(pk=ubicacion.pk)
    filas, total, sin_valor = [], CERO, 0
    for u in ubicaciones:
        aqui = sorted(((articulos[art], c) for (art, ubi), c in saldo.items() if ubi == u.pk and c and art in articulos),
                      key=lambda x: x[0].nombre.lower())
        if not aqui:
            continue
        filas.append(Fila([u.nombre, None, None, None, None, None], GRUPO))
        sub = CERO
        for a, cantidad in aqui:
            valor = _valor(a, cantidad, moneda, tasa)
            sin_valor += valor is None
            filas.append(Fila([a.nombre, a.codigo or None, a.unidad, cantidad, None, valor], sangria=1))
            sub += valor or CERO
        filas.append(Fila([f"Total {u.nombre}", None, None, None, None, sub], SUBTOTAL))
        total += sub
    filas.append(Fila(["Valor total", None, None, None, None, total], TOTAL))
    return Reporte(
        clave="inv-ubicaciones", titulo="Inventario por ubicación",
        subtitulo=f"Al {hoy:%d/%m/%Y} · {_alcance(clase, ubicacion, moneda, tasa)}",
        columnas=[Columna("Artículo", TEXTO, 3.2), Columna("Código", TEXTO, 1.2), Columna("Unidad", TEXTO, 0.9),
                  Columna("Según sistema", MONTO, 1.2), Columna("Conteo físico", TEXTO, 1.3), Columna("Valor", MONTO, 1.3)],
        filas=filas, firmas=["Contado por", "Revisado por"],
        notas=_notas_valor(sin_valor) + ["«Conteo físico» va en blanco para llenarlo a mano; la diferencia se registra como ajuste por conteo."],
    )


def por_reponer(organizacion, hoy):
    totales = services.totales_por_articulo(organizacion)
    filas = []
    for a in _articulos(organizacion, "consumible").filter(minimo__isnull=False):
        hay = totales.get(a.pk, CERO)
        if hay <= a.minimo:
            filas.append(Fila([a.nombre, a.categoria.nombre if a.categoria_id else "—", a.unidad, hay, a.minimo, a.minimo - hay],
                              tonos={3: "mal"}))
    filas.sort(key=lambda f: f.celdas[0].lower())
    return Reporte(
        clave="inv-reponer", titulo="Consumibles por reponer", subtitulo=f"Al {hoy:%d/%m/%Y}",
        columnas=[Columna("Artículo", TEXTO, 3), Columna("Categoría", TEXTO, 1.6), Columna("Unidad", TEXTO, 0.9),
                  Columna("Hay", MONTO, 1), Columna("Mínimo", MONTO, 1), Columna("Falta para el mínimo", MONTO, 1.4)],
        filas=filas, notas=["Entran los consumibles activos cuya existencia total llegó a su mínimo o bajó de él.",
                            "«Falta para el mínimo» es lo que hay que reponer solo para volver al mínimo, no la compra recomendada."],
    )


def movimientos(organizacion, desde, hasta, articulo=None):
    qs = MovimientoInventario.objects.filter(
        organizacion=organizacion, anulado=False, fecha__gte=desde, fecha__lte=hasta,
    ).select_related("articulo", "origen", "destino", "registrado_por").order_by("fecha", "pk")
    if articulo is not None:
        qs = qs.filter(articulo=articulo)
    filas, n = [], 0
    for m in qs:
        entra = m.cantidad if m.tipo == "entrada" else None
        sale = m.cantidad if m.tipo == "salida" else None
        mueve = m.cantidad if m.tipo == "traslado" else None
        lugar = f"{m.origen} → {m.destino}" if m.tipo == "traslado" else str(m.origen or m.destino)
        filas.append(Fila([m.fecha, m.articulo.nombre, m.get_motivo_display(), entra, sale, mueve, lugar,
                           m.registrado_por.nombre_para_mostrar(), m.nota or None]))
        n += 1
    filas.append(Fila(["Movimientos", None, None, None, None, None, None, None, n], TOTAL))
    return Reporte(
        clave="inv-movimientos", titulo="Movimientos de inventario",
        subtitulo=f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y} · {'Artículo: ' + articulo.nombre if articulo else 'Todos los artículos'}",
        columnas=[Columna("Fecha", FECHA, 1), Columna("Artículo", TEXTO, 2.2), Columna("Motivo", TEXTO, 1.6),
                  Columna("Entra", MONTO, 0.8), Columna("Sale", MONTO, 0.8), Columna("Mueve", MONTO, 0.8),
                  Columna("Ubicación", TEXTO, 1.8), Columna("Registró", TEXTO, 1.2), Columna("Nota", TEXTO, 2)],
        filas=filas, horizontal=True,
        notas=["No incluye los movimientos anulados. Las cantidades van en la unidad de cada artículo, por eso no se suman."],
    )
