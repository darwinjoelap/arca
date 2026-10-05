"""Desarrollo en tu máquina."""

from .base import *  # noqa: F401,F403

DEBUG = True

# Sin HTTPS ni cookies seguras en local
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
