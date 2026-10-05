"""Señales que alimentan la bitácora: login y login fallido son los dos
eventos que no pasan por una vista propia (usan `django.contrib.auth.urls`)."""

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .auditoria import registrar
from .models import RegistroAuditoria


@receiver(user_logged_in)
def _bitacora_login(sender, request, user, **kwargs):
    # Al iniciar sesión todavía no hay organización activa en el request. Si
    # la persona pertenece a una sola, el evento se anota ahí para que su
    # director lo vea en la bitácora; con varias (o ninguna) queda como
    # evento de plataforma.
    from organizaciones.models import Membresia

    organizaciones = list(
        Membresia.objects.filter(user=user, activa=True, organizacion__activa=True)
        .values_list("organizacion", flat=True)[:2]
    )
    organizacion_id = organizaciones[0] if len(organizaciones) == 1 else None
    organizacion = None
    if organizacion_id:
        from organizaciones.models import Organizacion

        organizacion = Organizacion.objects.filter(pk=organizacion_id).first()
    registrar(
        request, RegistroAuditoria.Accion.LOGIN,
        modelo="Usuario", objeto_id=user.pk, descripcion=user.get_username(),
        organizacion=organizacion,
    )


@receiver(user_login_failed)
def _bitacora_login_fallido(sender, credentials, request=None, **kwargs):
    usuario_intentado = credentials.get("username", "") if credentials else ""
    registrar(
        request, RegistroAuditoria.Accion.LOGIN_FALLIDO,
        modelo="Usuario", descripcion=f"Usuario intentado: {usuario_intentado}",
        organizacion=None,
    )
