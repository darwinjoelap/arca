"""Normalización de datos que se repite en varias apps (cédulas, teléfonos),
más el helper de borrado seguro de catálogos (Fase 8, D-33).

Un solo lugar para esta lógica: si cambia la regla, cambia aquí y no en
cada modelo o formulario que la use.
"""

import re

from django.contrib import messages
from django.db.models import ProtectedError
from django.shortcuts import redirect


def normalizar_cedula(valor: str | None) -> str | None:
    """Quita puntos, guiones y espacios; deja el prefijo (V/E/J) en mayúscula.

    'V-12.345.678' -> 'V12345678'
    '12345678'     -> '12345678'
    None o ''      -> None (para que los campos nullable queden NULL, no '')
    """
    if not valor:
        return None
    limpio = re.sub(r"[.\-\s]", "", valor).upper()
    return limpio or None


def normalizar_telefono(valor: str | None) -> str:
    """Deja solo dígitos. No fuerza longitud aquí: cada modelo valida la suya."""
    if not valor:
        return ""
    return re.sub(r"\D", "", valor)


def eliminar_protegido(request, objeto, url_lista):
    """Borra `objeto` dentro de una vista POST-only de catálogo (Fase 8,
    D-33: Darwin pidió poder borrar secciones, productos, formas de pago,
    etc. cuando no tienen nada asociado, no solo poder editarlas).

    Todas las relaciones a estos catálogos usan on_delete=PROTECT (nunca
    CASCADE) — así que si el objeto está en uso, `.delete()` levanta
    `ProtectedError` en vez de arrastrar registros reales (aportes, gastos,
    inscripciones...) a un borrado en cascada. Se captura esa excepción y se
    muestra un mensaje claro con qué lo está usando, en vez de un error 500;
    la pantalla ya tiene un toggle Activo/Inactivo para ese caso.

    Devuelve el `redirect` a `url_lista` — la vista que llama a esto solo
    tiene que hacer `return eliminar_protegido(request, objeto, "app:lista")`
    dentro de su rama `if request.method == "POST":`.
    """
    etiqueta = str(objeto)
    try:
        objeto.delete()
    except ProtectedError as error:
        modelos = sorted({obj._meta.verbose_name for obj in error.protected_objects})
        messages.error(
            request,
            f"No se puede eliminar «{etiqueta}»: está en uso ({', '.join(modelos)}). "
            "Desactívalo en su lugar si ya no se usa.",
        )
    else:
        messages.success(request, f"«{etiqueta}» eliminado.")
    return redirect(url_lista)
