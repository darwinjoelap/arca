"""Pruebas: `python manage.py test --settings=config.settings.test`.

Usa la misma DATABASE_URL del .env (Django crea aparte la base test_<nombre>),
con un hasher rápido y sin el almacenamiento con manifiesto, que exigiría
correr collectstatic antes de cada prueba.
"""

from .base import *  # noqa: F401,F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
