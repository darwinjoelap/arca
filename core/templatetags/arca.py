from django import template

from cambio.services import formatear

register = template.Library()


@register.filter
def monto(valor, decimales=2):
    """1234.5 -> '1.234,50' (formato es-VE). Vacío si no hay valor."""
    if valor is None or valor == "":
        return ""
    return formatear(valor, int(decimales))


@register.filter
def simbolo(moneda):
    return {"USD": "$", "VES": "Bs."}.get(moneda, moneda)
