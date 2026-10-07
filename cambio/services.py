"""Único lugar donde se convierte entre Bs. (VES) y USD en Arca.

Ningún otro módulo debe hacer aritmética de tasa por su cuenta: todo pasa por
obtener_tasa() y convertir(), para que el redondeo y las reglas de "cuál
moneda queda exacta" sean siempre las mismas.
"""

from decimal import ROUND_HALF_UP, Decimal

from .models import TasaCambio

CUATRO_DECIMALES = Decimal("0.0001")


class SinTasaError(Exception):
    """No hay ninguna TasaCambio disponible en la fecha pedida ni antes."""


def obtener_tasa(fecha, fuente=None):
    """Devuelve (TasaCambio, es_exacta), solo entre las tasas GLOBALES.

    Si existe una tasa exactamente en `fecha` (y `fuente`, si se indica), la
    devuelve con es_exacta=True. Si no, devuelve la última tasa anterior a
    `fecha` con es_exacta=False. Si no hay ninguna tasa anterior o igual,
    lanza SinTasaError.
    """
    consulta = TasaCambio.objects.filter(organizacion__isnull=True)
    if fuente:
        consulta = consulta.filter(fuente=fuente)

    exacta = consulta.filter(fecha=fecha).order_by("-creada_en").first()
    if exacta is not None:
        return exacta, True

    anterior = consulta.filter(fecha__lt=fecha).order_by("-fecha", "-creada_en").first()
    if anterior is not None:
        return anterior, False

    detalle = f" para la fuente '{fuente}'" if fuente else ""
    raise SinTasaError(f"No hay ninguna tasa de cambio registrada en o antes de {fecha}{detalle}.")


def tasa_propia(organizacion, fecha):
    """La última tasa que la organización cargó para `fecha` o antes, o None."""
    return (
        TasaCambio.objects.filter(organizacion=organizacion, fecha__lte=fecha).order_by("-fecha").first()
    )


def convertir(monto, moneda, tasa_valor):
    """(monto_ves, monto_usd), ambos Decimal a 4 decimales, ROUND_HALF_UP.

    La moneda de origen (`moneda`) queda exacta (solo se le ajustan los
    decimales); la otra se deriva multiplicando o dividiendo por `tasa_valor`.
    """
    monto = Decimal(monto)
    tasa_valor = Decimal(tasa_valor)

    if moneda == "USD":
        monto_usd = monto.quantize(CUATRO_DECIMALES, rounding=ROUND_HALF_UP)
        monto_ves = (monto * tasa_valor).quantize(CUATRO_DECIMALES, rounding=ROUND_HALF_UP)
    elif moneda == "VES":
        monto_ves = monto.quantize(CUATRO_DECIMALES, rounding=ROUND_HALF_UP)
        monto_usd = (monto / tasa_valor).quantize(CUATRO_DECIMALES, rounding=ROUND_HALF_UP)
    else:
        raise ValueError(f"Moneda no soportada: {moneda!r} (se espera 'VES' o 'USD').")

    return monto_ves, monto_usd


def formatear(monto, decimales=2):
    """Cadena en formato es-VE ('1.234,56') para mostrar en pantalla."""
    monto = Decimal(monto)
    paso = Decimal(1).scaleb(-decimales) if decimales else Decimal(1)
    monto = monto.quantize(paso, rounding=ROUND_HALF_UP)
    cadena = f"{monto:,.{decimales}f}"
    return cadena.replace(",", "X").replace(".", ",").replace("X", ".")
