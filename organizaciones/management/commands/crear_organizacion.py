from django.core.management.base import BaseCommand, CommandError

from core.models import RegistroAuditoria
from organizaciones.services import crear_organizacion


class Command(BaseCommand):
    help = "Da de alta una organización con su director (dueño)."

    def add_arguments(self, parser):
        parser.add_argument("nombre", help='Nombre de la organización, entre comillas. Ej: "Club Los Samanes"')
        parser.add_argument("--director", required=True, help="Nombre de usuario del director.")
        parser.add_argument("--clave", help="Clave temporal. Obligatoria si el usuario no existe todavía.")
        parser.add_argument("--nombre-director", default="", help="Nombre visible del director.")
        parser.add_argument("--moneda", default="USD", choices=["USD", "VES"])

    def handle(self, *args, **opciones):
        try:
            organizacion, membresia, creado = crear_organizacion(
                nombre=opciones["nombre"],
                usuario_director=opciones["director"],
                clave=opciones["clave"],
                nombre_director=opciones["nombre_director"],
                moneda_base=opciones["moneda"],
            )
        except ValueError as error:
            raise CommandError(str(error))

        RegistroAuditoria.objects.create(
            organizacion=organizacion,
            accion=RegistroAuditoria.Accion.CREAR_ORGANIZACION,
            modelo="Organizacion",
            objeto_id=str(organizacion.pk),
            descripcion=f"{organizacion.nombre} — director: {membresia.usuario_texto} (por comando)",
        )
        self.stdout.write(self.style.SUCCESS(f"Organización «{organizacion.nombre}» creada (slug: {organizacion.slug})."))
        if creado:
            self.stdout.write(
                f"Usuario «{membresia.user.username}» creado con clave temporal; se le pedirá cambiarla al entrar."
            )
        else:
            self.stdout.write(f"El usuario «{membresia.user.username}» ya existía: se le agregó como director.")
