"""Endpoint que recibe ingresos y egresos en JSON (Fase 3, parte 2).

Lo usan dos caminos, con el mismo código en el cliente (static/js/offline-*.js):

- Con conexión: el formulario se envía aquí en vez de con un POST normal, para
  poder notar a tiempo si la red falla a mitad de camino.
- Sin conexión: lo capturado se guarda en el teléfono (IndexedDB) y se envía
  aquí cuando vuelve la señal.

Valida con el MISMO `MovimientoForm` de la pantalla normal: no hay un segundo
juego de reglas que mantener.

Contrato de respuestas. El cliente decide qué hacer solo con esto, así que
cambiarlo aquí obliga a cambiar `enviarUno()` en offline-sync-core.js:

- 201 {"resultado": "creado"}       se guardó.
- 200 {"resultado": "ya_existia"}   ese `uuid_cliente` ya estaba: no se duplica.
- 422 {"detalle", "errores"}        datos inválidos. NO se reintenta solo.
- 403 {"detalle"}                   sin permiso. NO se reintenta solo.
- 401 / 409 {"codigo"}              no hay sesión, o la sesión es de otra persona
                                    u otra organización: el pendiente se conserva
                                    intacto hasta que entre quien lo capturó.

Nunca responde con una redirección al login: `fetch` la seguiría, recibiría
un 200 con el HTML del login y el cliente creería que se guardó. Edumia tenía
ese hueco (usaba @login_required aquí); por eso este endpoint revisa la
sesión a mano y el cliente exige además que la respuesta sea JSON con
`resultado`.
"""

import json

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.mixins import tiene_permiso
from core.models import RegistroAuditoria
from finanzas.forms import MovimientoForm
from finanzas.models import Movimiento
from finanzas.services import registrar_movimiento
from finanzas.views import PERMISO_POR_TIPO


def _rechazo(estado, detalle, **extra):
    return JsonResponse({"detalle": detalle, **extra}, status=estado)


def _resumen_errores(errores):
    """Un texto corto para mostrar en el teléfono: «Monto: ...; Fecha: ...»."""
    partes = []
    for campo, mensajes in errores.items():
        etiqueta = "" if campo == "__all__" else f"{campo.replace('_', ' ').capitalize()}: "
        partes.append(etiqueta + " ".join(str(m) for m in mensajes))
    return "; ".join(partes)


@require_POST
def api_movimiento(request):
    if not request.user.is_authenticated:
        return _rechazo(401, "Tu sesión se cerró. Inicia sesión para enviar lo pendiente.", codigo="sin_sesion")
    if request.user.debe_cambiar_clave:
        return _rechazo(401, "Cambia tu contraseña temporal para enviar lo pendiente.", codigo="sin_sesion")
    organizacion = request.organizacion
    if organizacion is None:
        return _rechazo(409, "Elige una organización para enviar lo pendiente.", codigo="otra_sesion")

    try:
        datos = json.loads(request.body.decode("utf-8"))
        if not isinstance(datos, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return _rechazo(422, "El envío no se pudo leer.")

    # Lo capturó otra persona, o esta misma en otra organización, en este
    # mismo teléfono: no se guarda a nombre de quien tiene la sesión ahora.
    if str(datos.get("_usuario") or request.user.pk) != str(request.user.pk) or \
            str(datos.get("_organizacion") or organizacion.pk) != str(organizacion.pk):
        return _rechazo(
            409, "Esto se registró con otro usuario u otra organización. Se enviará cuando esa sesión esté abierta.",
            codigo="otra_sesion",
        )

    tipo = datos.get("tipo")
    if tipo not in PERMISO_POR_TIPO:
        return _rechazo(422, "Falta indicar si es un ingreso o un egreso.")
    if not tiene_permiso(request, PERMISO_POR_TIPO[tipo]):
        return _rechazo(403, "No tienes permiso para registrar este tipo de movimiento.")
    if not datos.get("uuid_cliente"):
        return _rechazo(422, "Falta el identificador del envío.")

    form = MovimientoForm(datos, organizacion=organizacion, tipo=tipo)
    if not form.is_valid():
        return _rechazo(422, _resumen_errores(form.errors), errores=form.errors)

    movimiento = form.save(commit=False)
    movimiento.uuid_cliente = form.cleaned_data["uuid_cliente"]
    try:
        movimiento, creado = registrar_movimiento(movimiento, membresia=request.membresia)
    except ValidationError as error:
        errores = error.message_dict if hasattr(error, "message_dict") else {"__all__": error.messages}
        return _rechazo(422, _resumen_errores(errores), errores=errores)

    if creado:
        origen = " (capturado sin conexión)" if datos.get("_offline") else ""
        registrar(
            request, RegistroAuditoria.Accion.REGISTRAR_MOVIMIENTO, modelo="Movimiento", objeto_id=movimiento.pk,
            descripcion=f"{movimiento.get_tipo_display()} #{movimiento.numero_vale} · {movimiento.titulo} · "
            f"{movimiento.moneda} {movimiento.monto:.2f} · {movimiento.cuenta}{origen}",
        )
    return JsonResponse(
        {
            "resultado": "creado" if creado else "ya_existia",
            "id": movimiento.pk,
            "numero_vale": movimiento.numero_vale,
            "tipo": movimiento.get_tipo_display(),
            "por_aprobar": movimiento.estado == Movimiento.Estado.REGISTRADO,
            "url": reverse("finanzas:movimiento_detalle", args=[movimiento.pk]),
        },
        status=201 if creado else 200,
    )
