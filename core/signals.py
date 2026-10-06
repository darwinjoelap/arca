"""Señales que alimentan la bitácora: login y login fallido son los dos
eventos que no pasan por una vista propia (usan `django.contrib.auth.urls`)."""

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .auditoria import registrar
from .models import RegistroAuditoria


@receiver(user_logged_in)
def _bitacora_login(sender, request, user, **kwargs):
    # La cuenta es de una organización: el evento se anota ahí para que su
    # director lo vea. Las de plataforma quedan sin organización.
    organizacion = user.organizacion_cuenta
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
        organizacion=getattr(request, "organizacion_login", None),
    )
