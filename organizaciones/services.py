"""Operaciones que tocan más de un modelo. Las usan las vistas, el panel de
plataforma y el comando `crear_organizacion`."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from .models import Membresia, Organizacion


def slug_disponible(nombre):
    base = slugify(nombre)[:50] or "organizacion"
    slug, n = base, 2
    while Organizacion.objects.filter(slug=slug).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


@transaction.atomic
def crear_organizacion(*, nombre, usuario_director, clave=None, nombre_director="", moneda_base="USD"):
    """Crea la organización y su director (dueño).

    `usuario_director` es un username. Si el usuario no existe se crea con
    `clave` como contraseña temporal; si ya existe se le agrega la membresía
    y su contraseña no se toca."""
    Usuario = get_user_model()
    organizacion = Organizacion.objects.create(
        nombre=nombre, slug=slug_disponible(nombre), moneda_base=moneda_base,
    )
    usuario = Usuario.objects.filter(username=usuario_director).first()
    creado = usuario is None
    if creado:
        if not clave:
            raise ValueError("Hace falta una clave temporal para crear al director.")
        usuario = Usuario(username=usuario_director, debe_cambiar_clave=True)
        usuario.set_password(clave)
        usuario.save()
    membresia = Membresia.objects.create(
        organizacion=organizacion, user=usuario, es_dueno=True, nombre_visible=nombre_director,
    )
    return organizacion, membresia, creado


def usuario_es_exclusivo(usuario, organizacion):
    """True si el usuario solo pertenece a `organizacion` y no es de plataforma.

    Es la condición para que un director pueda restablecerle la clave: de lo
    contrario un director podría tomar la cuenta de alguien que también
    pertenece a otra organización, o la de un superadmin."""
    if usuario.is_superuser or usuario.is_staff:
        return False
    return not Membresia.objects.filter(user=usuario).exclude(organizacion=organizacion).exists()
