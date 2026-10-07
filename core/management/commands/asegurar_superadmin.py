"""Crea la cuenta de plataforma en el primer arranque de producción.

Railway no da una consola interactiva cómoda para `createsuperuser`, así que
el arranque llama a este comando: si están definidas ARCA_ADMIN_USUARIO y
ARCA_ADMIN_CLAVE y todavía no existe NINGÚN superusuario, lo crea con esa
clave como temporal (obliga a cambiarla al entrar). Si ya hay uno, no hace
nada: no cambia claves ni crea cuentas de más, así que es seguro dejarlo en
cada arranque. Tras el primer ingreso conviene borrar ARCA_ADMIN_CLAVE.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea el superadmin de la plataforma si no existe ninguno (usa ARCA_ADMIN_USUARIO y ARCA_ADMIN_CLAVE)."

    def handle(self, *args, **opciones):
        Usuario = get_user_model()
        if Usuario.objects.filter(is_superuser=True).exists():
            self.stdout.write("Ya existe un superadmin: no se hace nada.")
            return
        usuario, clave = os.environ.get("ARCA_ADMIN_USUARIO", "").strip(), os.environ.get("ARCA_ADMIN_CLAVE", "")
        if not usuario or not clave:
            self.stdout.write(self.style.WARNING(
                "No hay superadmin y faltan ARCA_ADMIN_USUARIO / ARCA_ADMIN_CLAVE: nadie puede entrar a /plataforma/."))
            return
        if len(clave) < 12:
            self.stdout.write(self.style.ERROR("ARCA_ADMIN_CLAVE debe tener al menos 12 caracteres: no se creó nada."))
            return
        Usuario.objects.create_superuser(usuario, password=clave, debe_cambiar_clave=True)
        self.stdout.write(self.style.SUCCESS(f"Superadmin «{usuario.lower()}» creado. Se le pedirá cambiar la clave al entrar."))
