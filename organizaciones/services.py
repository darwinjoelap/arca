"""Operaciones que tocan más de un modelo. Las usan las vistas, el panel de
plataforma y el comando `crear_organizacion`."""

import re
import secrets

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.text import slugify

from .models import Membresia, Organizacion


# Sin 0/O, 1/l/I: la clave se dicta por teléfono o se copia a mano.
_ALFABETO = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def clave_temporal():
    """Contraseña de un solo uso: la genera el sistema, se muestra una vez y
    quien la recibe debe cambiarla al entrar (`debe_cambiar_clave`)."""
    return "Arca-" + "".join(secrets.choice(_ALFABETO) for _ in range(10))


def asignar_clave_temporal(usuario):
    """Le pone al usuario una clave temporal nueva y la devuelve en claro."""
    clave = clave_temporal()
    usuario.set_password(clave)
    usuario.debe_cambiar_clave = True
    usuario.save()
    return clave


def validar_limite_usuarios(organizacion, excluir=None):
    """Lanza ValidationError si la organización ya llegó al tope de su plan."""
    if organizacion.limite_usuarios is None:
        return
    activos = Membresia.objects.filter(organizacion=organizacion, activa=True, user__isnull=False)
    if excluir is not None:
        activos = activos.exclude(pk=excluir)
    if activos.count() >= organizacion.limite_usuarios:
        raise ValidationError(
            f"El plan de la organización permite {organizacion.limite_usuarios} usuarios con acceso. "
            "Desactiva a alguien o pide al soporte de Arca ampliar el plan."
        )


# Primeros segmentos de URL que usa Arca: no pueden ser el enlace de una organización.
RESERVADOS = {
    "admin", "api", "cuentas", "cuenta", "organizacion", "organizaciones", "cambio", "libro", "personal",
    "presupuestos", "reportes", "inventario", "sync", "plataforma", "salud", "sin-conexion", "static", "media",
    "favicon.ico", "manifest.json", "sw.js", "arca", "www", "app", "soporte", "ayuda", "login", "entrar", "instalar",
}
_PATRON_ENLACE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validar_enlace(slug, excluir_pk=None):
    """El enlace (/slug/) de una organización: limpio, no reservado y sin repetir."""
    slug = (slug or "").strip().lower()
    if not 3 <= len(slug) <= 40 or not _PATRON_ENLACE.match(slug):
        raise ValidationError("Usa de 3 a 40 letras minúsculas, números o guiones (ej. casa-los-samanes).")
    if slug in RESERVADOS:
        raise ValidationError(f"«{slug}» está reservado por Arca. Elige otro.")
    if Organizacion.objects.filter(slug=slug).exclude(pk=excluir_pk).exists():
        raise ValidationError("Ese enlace ya lo usa otra organización.")
    return slug


def slug_disponible(nombre):
    base = slugify(nombre)[:36].strip("-") or "organizacion"
    if len(base) < 3:
        base = f"org-{base}"
    slug, n = base, 2
    while slug in RESERVADOS or Organizacion.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


@transaction.atomic
def crear_organizacion(*, nombre, usuario_director, clave, nombre_director="", moneda_base="USD", slug=None, **extra):
    """Crea la organización y su director (dueño), que es un usuario PROPIO de
    la organización: se crea siempre, con `clave` como contraseña temporal.

    Devuelve (organizacion, membresia, True); el tercer valor se conserva por
    compatibilidad. `extra`: otros campos de la organización (rif, plan,
    activa_hasta, limite_usuarios, notas...)."""
    if not clave:
        raise ValueError("Hace falta una clave temporal para crear al director.")
    organizacion = Organizacion.objects.create(
        nombre=nombre, slug=slug or slug_disponible(nombre), moneda_base=moneda_base, **extra,
    )
    usuario = get_user_model().objects.create_user(
        usuario_director, password=clave, organizacion_cuenta=organizacion, debe_cambiar_clave=True,
    )
    membresia = Membresia.objects.create(
        organizacion=organizacion, user=usuario, es_dueno=True, nombre_visible=nombre_director,
    )
    return organizacion, membresia, True


def usuario_es_exclusivo(usuario, organizacion):
    """True si la cuenta es propia de `organizacion` y no es de plataforma.

    Es la condición para que un director pueda restablecerle la clave: nunca
    la de un superadmin ni la de una cuenta de otra organización."""
    if usuario.is_superuser or usuario.is_staff:
        return False
    return usuario.organizacion_cuenta_id == organizacion.pk
