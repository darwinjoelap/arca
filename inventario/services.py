"""Existencias y registro de movimientos de inventario."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from cambio.services import convertir

from .models import Articulo, MovimientoInventario

CERO = Decimal("0")


def existencias(organizacion, articulo=None, excluir=None):
    """{(articulo_id, ubicacion_id): cantidad} con los movimientos vigentes."""
    base = MovimientoInventario.objects.filter(organizacion=organizacion, anulado=False)
    if articulo is not None:
        base = base.filter(articulo=articulo)
    if excluir is not None:
        base = base.exclude(pk=excluir)
    saldo = {}
    for fila in base.filter(destino__isnull=False).values("articulo_id", "destino_id").annotate(t=Sum("cantidad")):
        clave = (fila["articulo_id"], fila["destino_id"])
        saldo[clave] = saldo.get(clave, CERO) + fila["t"]
    for fila in base.filter(origen__isnull=False).values("articulo_id", "origen_id").annotate(t=Sum("cantidad")):
        clave = (fila["articulo_id"], fila["origen_id"])
        saldo[clave] = saldo.get(clave, CERO) - fila["t"]
    return saldo


def totales_por_articulo(organizacion):
    """{articulo_id: cantidad total en todas las ubicaciones}."""
    totales = {}
    for (articulo_id, _), cantidad in existencias(organizacion).items():
        totales[articulo_id] = totales.get(articulo_id, CERO) + cantidad
    return totales


def en_ubicacion(organizacion, articulo, ubicacion, excluir=None):
    return existencias(organizacion, articulo=articulo, excluir=excluir).get((articulo.pk, ubicacion.pk), CERO)


def _fmt(cantidad):
    return f"{cantidad.normalize():f}" if cantidad else "0"


@transaction.atomic
def registrar(movimiento, *, usuario):
    """Guarda un movimiento nuevo. Una salida o un traslado no pueden sacar
    más de lo que hay en la ubicación de origen."""
    # Se bloquea el artículo: dos salidas a la vez no pueden pasarse entre las dos.
    Articulo.objects.select_for_update().get(pk=movimiento.articulo_id)
    movimiento.registrado_por = usuario
    movimiento.full_clean()
    if movimiento.origen_id:
        hay = en_ubicacion(movimiento.organizacion, movimiento.articulo, movimiento.origen)
        if movimiento.cantidad > hay:
            raise ValidationError({"cantidad": (
                f"En «{movimiento.origen}» solo hay {_fmt(hay)} {movimiento.articulo.unidad}. "
                "Si el conteo real es otro, registra primero un ajuste."
            )})
    movimiento.save()
    return movimiento


@transaction.atomic
def anular(movimiento, *, usuario, motivo):
    """Anula un movimiento, salvo que deshacerlo deje alguna ubicación en negativo
    (p. ej. anular una entrada cuya mercancía ya salió)."""
    if movimiento.anulado:
        raise ValidationError("Ese movimiento ya está anulado.")
    Articulo.objects.select_for_update().get(pk=movimiento.articulo_id)
    if movimiento.destino_id:
        quedaria = en_ubicacion(movimiento.organizacion, movimiento.articulo, movimiento.destino) - movimiento.cantidad
        if quedaria < 0:
            raise ValidationError(
                f"No se puede anular: «{movimiento.destino}» quedaría con existencia negativa "
                f"({_fmt(quedaria)}). Anula o corrige primero lo que salió después."
            )
    movimiento.anulado, movimiento.motivo_anulacion, movimiento.anulado_por = True, motivo.strip()[:200], usuario
    movimiento.save(update_fields=["anulado", "motivo_anulacion", "anulado_por"])
    return movimiento


def resumen(organizacion, tasa=None):
    """Artículos activos con su existencia total, si están bajo el mínimo y su valor.

    Devuelve (filas, totales): cada fila es el Articulo con `.existencia`,
    `.bajo_minimo`, `.valor_usd`, `.valor_ves`; totales = {"articulos",
    "bajo_minimo", "usd", "ves", "convertible", "sin_valor"}."""
    cantidades = totales_por_articulo(organizacion)
    filas = list(Articulo.objects.filter(organizacion=organizacion).select_related("categoria", "responsable", "responsable__user"))
    usd = ves = CERO
    bajo = sin_valor = 0
    for a in filas:
        a.existencia = cantidades.get(a.pk, CERO)
        a.bajo_minimo = bool(a.activo and a.es_consumible and a.minimo is not None and a.existencia <= a.minimo)
        a.valor_usd = a.valor_ves = None
        if a.valor_unitario is not None:
            total = a.valor_unitario * a.existencia
            if tasa is not None:
                a.valor_ves, a.valor_usd = convertir(total, a.moneda, tasa.valor)
            elif a.moneda == "USD":
                a.valor_usd = total
            else:
                a.valor_ves = total
        if a.activo:
            bajo += a.bajo_minimo
            usd += a.valor_usd or CERO
            ves += a.valor_ves or CERO
            sin_valor += a.valor_unitario is None and a.existencia > 0
    return filas, {
        "articulos": sum(1 for a in filas if a.activo), "bajo_minimo": bajo, "usd": usd, "ves": ves,
        "convertible": tasa is not None, "sin_valor": sin_valor,
    }
