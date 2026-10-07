"""Producción (Railway + PostgreSQL)."""

from .base import *  # noqa: F401,F403

DEBUG = False

# Railway entrega su dominio público en RAILWAY_PUBLIC_DOMAIN: se acepta solo,
# sin tener que copiarlo a ALLOWED_HOSTS ni a CSRF_TRUSTED_ORIGINS. Un dominio
# propio sí hay que agregarlo a mano a las dos variables.
_dominio_railway = env("RAILWAY_PUBLIC_DOMAIN", default="")  # noqa: F405
if _dominio_railway:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, _dominio_railway]  # noqa: F405
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{_dominio_railway}"]  # noqa: F405
# El health check de Railway llega con este Host; sin él /salud/ responde 400
# y el despliegue nunca se da por bueno.
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "healthcheck.railway.app"]  # noqa: F405

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
