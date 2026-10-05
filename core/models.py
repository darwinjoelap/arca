from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models


class Usuario(AbstractUser):
    """Usuario de la plataforma. Es global: una misma persona puede tener una
    `Membresia` en varias organizaciones (app `organizaciones`), y es la
    membresía —no el usuario— la que dice qué puede hacer en cada una."""

    telefono = models.CharField("teléfono", max_length=20, blank=True)
    debe_cambiar_clave = models.BooleanField(
        default=False,
        help_text="Se enciende al crear el usuario o restablecer su clave con una temporal; "
        "se apaga cuando la cambia. Mientras esté encendido no puede usar el sistema.",
    )

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    def nombre_para_mostrar(self):
        return self.get_full_name() or self.get_username()


class RegistroAuditoria(models.Model):
    """Bitácora de eventos que importan. Solo inserción: nunca se edita ni se borra.

    `organizacion` queda vacía en los eventos de plataforma (un login de alguien
    con varias organizaciones, la carga de una tasa de cambio)."""

    class Accion(models.TextChoices):
        LOGIN = "login", "Inicio de sesión"
        LOGIN_FALLIDO = "login_fallido", "Inicio de sesión fallido"
        CAMBIAR_CLAVE = "cambiar_clave", "Cambio de contraseña"
        CARGAR_TASA = "cargar_tasa", "Carga de tasa de cambio"
        EDITAR_TASA = "editar_tasa", "Corrección de tasa de cambio"
        CREAR_ORGANIZACION = "crear_organizacion", "Alta de organización"
        EDITAR_ORGANIZACION = "editar_organizacion", "Edición de datos de la organización"
        VISIBILIDAD_CUENTAS = "visibilidad_cuentas", "Cambio de visibilidad de cuentas personales"
        CREAR_TIPO = "crear_tipo", "Creación de tipo de miembro"
        EDITAR_TIPO = "editar_tipo", "Edición de tipo de miembro"
        ELIMINAR_TIPO = "eliminar_tipo", "Eliminación de tipo de miembro"
        CREAR_MIEMBRO = "crear_miembro", "Alta de miembro"
        EDITAR_MIEMBRO = "editar_miembro", "Edición de miembro"
        ACTIVAR_MIEMBRO = "activar_miembro", "Activación de miembro"
        DESACTIVAR_MIEMBRO = "desactivar_miembro", "Desactivación de miembro"
        RESTABLECER_CLAVE = "restablecer_clave", "Restablecimiento de contraseña"
        CREAR_EJERCICIO = "crear_ejercicio", "Creación de ejercicio"
        ACTIVAR_EJERCICIO = "activar_ejercicio", "Activación de ejercicio"
        CERRAR_EJERCICIO = "cerrar_ejercicio", "Cierre de ejercicio"

    organizacion = models.ForeignKey(
        "organizaciones.Organizacion", null=True, blank=True,
        on_delete=models.PROTECT, related_name="registros_auditoria",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
    )
    accion = models.CharField(max_length=30, choices=Accion.choices)
    modelo = models.CharField(max_length=60, blank=True)
    objeto_id = models.CharField(max_length=64, blank=True)
    descripcion = models.TextField(blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "registro de auditoría"
        verbose_name_plural = "bitácora de auditoría"
        indexes = [
            models.Index(fields=["organizacion", "-fecha"]),
            models.Index(fields=["modelo", "objeto_id"]),
            models.Index(fields=["usuario", "fecha"]),
            models.Index(fields=["accion", "fecha"]),
        ]
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.get_accion_display()} — {self.fecha:%Y-%m-%d %H:%M}"
