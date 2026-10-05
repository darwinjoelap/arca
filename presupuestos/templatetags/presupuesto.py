from decimal import Decimal

from django import template
from django.utils.html import format_html

from cambio.services import formatear

register = template.Library()


@register.filter
def tono(linea, variacion):
    """Clase CSS de una variación: favorable, desfavorable o ninguna."""
    bien = linea.favorable(variacion)
    return "" if bien is None else ("tono-bien" if bien else "tono-mal")


@register.simple_tag
def total(comparativo, tipo, atributo):
    return formatear(comparativo.total(tipo, atributo))


@register.simple_tag
def medidor(linea):
    """Barra de ejecución acumulada con su porcentaje al lado (nunca solo color)."""
    pct = linea.pct_acumulado
    if pct is None:
        texto = "Sin presupuesto" if linea.real_acumulado else "—"
        return format_html('<span class="text-muted small">{}</span>', texto)
    ancho = max(Decimal("0"), min(pct, Decimal("100")))
    clase = ""
    if linea.tipo == "egreso" and pct > 100:
        clase = "excedido"
    elif linea.tipo == "ingreso" and pct >= 100:
        clase = "cumplido"
    aviso = " Excedido" if clase == "excedido" else ""
    return format_html(
        '<div class="medidor"><div class="medidor-pista" role="img" aria-label="{} % ejecutado.{}">'
        '<div class="medidor-relleno {}" style="width: {}%;"></div></div>'
        '<span class="medidor-valor{}">{} %</span></div>',
        formatear(pct, 0), aviso, clase, f"{float(ancho):.1f}", " tono-mal fw-semibold" if clase == "excedido" else "", formatear(pct, 0),
    )
