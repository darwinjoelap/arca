from decimal import Decimal

from django import template

from cambio.services import formatear

register = template.Library()


@register.filter
def cantidad(valor):
    """12.00 -> '12'; 2.50 -> '2,5'. Las cantidades no llevan ceros de relleno."""
    if valor is None or valor == "":
        return ""
    valor = Decimal(valor)
    if valor == valor.to_integral_value():
        return formatear(valor, 0)
    return formatear(valor, 2).rstrip("0")
