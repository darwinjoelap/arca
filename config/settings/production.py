"""Producción (Railway + PostgreSQL)."""

from .base import *  # noqa: F401,F403

DEBUG = False

# Railway termina el HTTPS en su proxy y reenvía por HTTP al contenedor.
# Sin esta cabecera, SECURE_SSL_REDIRECT entra en bucle de redirecciones.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
# El health check de la plataforma llega por HTTP plano: no se redirige.
SECURE_REDIRECT_EXEMPT = [r"^salud/$"]

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True

# Empezar con una hora; subir a 1 año cuando el dominio esté estable.
SECURE_HSTS_SECONDS = 3600
