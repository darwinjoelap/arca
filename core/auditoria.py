"""Bitácora de auditoría: un solo punto de entrada para registrar un evento
en `RegistroAuditoria`.

Se llama siempre con el `request` a mano (nunca desde los modelos): así se
saca el usuario, la IP y la organización activa sin que los modelos tengan
que saber nada de HTTP. Regla heredada de Edumia (D-28): la llamada a
`registrar()` se escribe en el mismo cambio que crea el flujo, no después."""

_SIN_INDICAR = object()


def obtener_ip(request):
    """IP real del cliente. Railway hace de proxy: `REMOTE_ADDR` sería la IP
    interna de la plataforma, así que se prefiere `X-Forwarded-For`."""
    if request is None:
        return None
    adelante = request.META.get("HTTP_X_FORWARDED_FOR")
    if adelante:
        return adelante.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def registrar(request, accion, *, modelo="", objeto_id="", descripcion="", organizacion=_SIN_INDICAR):
    """Crea una fila en la bitácora. No lanza si algo falla: una auditoría
    que rompe el flujo normal sería peor que no tenerla.

    `organizacion`: por defecto la activa del request (`request.organizacion`).
    Se pasa explícita cuando el evento ocurre fuera de ese contexto (el panel
    de plataforma, el login)."""
    from .models import RegistroAuditoria

    usuario = getattr(request, "user", None)
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    if organizacion is _SIN_INDICAR:
        organizacion = getattr(request, "organizacion", None)

    try:
        RegistroAuditoria.objects.create(
            organizacion=organizacion,
            usuario=usuario,
            accion=accion,
            modelo=modelo,
            objeto_id=str(objeto_id) if objeto_id else "",
            descripcion=descripcion,
            ip=obtener_ip(request),
        )
    except Exception:
        pass
