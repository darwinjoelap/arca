"""Datos de la organización en Excel: descargar todo y cargar desde una
plantilla. Solo el director (dueño): es quien responde por los datos."""

import base64
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.models import RegistroAuditoria

from . import datos

Accion = RegistroAuditoria.Accion
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CLAVE_ARCHIVO = "arca_carga_excel"


def solo_director(vista):
    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        membresia = getattr(request, "membresia", None)
        if membresia is None or not membresia.activa or not membresia.es_dueno:
            raise PermissionDenied("Solo el director puede descargar o cargar los datos de la organización.")
        return vista(request, *args, **kwargs)

    return envoltura


def _descarga(contenido, nombre):
    respuesta = HttpResponse(contenido, content_type=XLSX)
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}.xlsx"'
    return respuesta


@solo_director
def inicio(request):
    return render(request, "organizaciones/datos.html", {"hojas": datos.HOJAS})


@solo_director
def exportar(request):
    organizacion = request.organizacion
    contenido = datos.exportar(organizacion)
    registrar(request, Accion.EXPORTAR_DATOS, modelo="Organizacion", objeto_id=organizacion.pk,
              descripcion="Todo en Excel")
    return _descarga(contenido, f"arca-{organizacion.slug}-{timezone.localdate():%Y%m%d}")


@solo_director
def plantilla(request):
    return _descarga(datos.plantilla(), "arca-plantilla-de-carga")


@solo_director
@require_POST
def cargar(request):
    """Dos pasos con el mismo archivo: primero se simula (no guarda nada) y se
    muestra qué pasaría; al confirmar, se carga. El archivo viaja entre un paso
    y otro en la sesión, para no pedirlo dos veces."""
    confirmar = request.POST.get("confirmar") == "1"
    if confirmar:
        guardado = request.session.pop(CLAVE_ARCHIVO, None)
        if not guardado:
            messages.error(request, "La revisión venció. Sube el archivo otra vez.")
            return redirect("organizaciones:datos")
        nombre, contenido = guardado["nombre"], base64.b64decode(guardado["contenido"])
    else:
        archivo = request.FILES.get("archivo")
        if archivo is None:
            messages.error(request, "Elige el archivo de Excel.")
            return redirect("organizaciones:datos")
        if archivo.size > datos.MAX_BYTES:
            messages.error(request, "El archivo pesa más de 2 MB. Divídelo en varios.")
            return redirect("organizaciones:datos")
        nombre, contenido = archivo.name, archivo.read()

    try:
        resultado = datos.importar(request.organizacion, contenido, membresia=request.membresia, simular=not confirmar)
    except datos.ArchivoInvalido as e:
        messages.error(request, str(e))
        return redirect("organizaciones:datos")

    if resultado.guardado:
        detalle = ", ".join(f"{n} {hoja.lower()}" for hoja, n in resultado.creados.items())
        registrar(request, Accion.IMPORTAR_DATOS, modelo="Organizacion", objeto_id=request.organizacion.pk,
                  descripcion=f"{nombre}: {detalle}"[:500])
        messages.success(request, f"Carga completa: {detalle}.")
        return redirect("organizaciones:datos")

    # Simulación (o confirmación que falló): se guarda el archivo solo si se puede confirmar.
    puede_confirmar = not resultado.errores and resultado.total > 0
    if puede_confirmar:
        request.session[CLAVE_ARCHIVO] = {"nombre": nombre, "contenido": base64.b64encode(contenido).decode()}
    return render(request, "organizaciones/datos_revision.html", {
        "resultado": resultado, "nombre": nombre, "puede_confirmar": puede_confirmar,
    })
