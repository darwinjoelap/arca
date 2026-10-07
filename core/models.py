from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import models
from django.db.models import Q


def normalizar_usuario(username):
    return (username or "").strip().lower()


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, username):
        """Solo cuentas de plataforma (sin organización): lo usan createsuperuser y el admin."""
        return self.get(username=normalizar_usuario(username), organizacion_cuenta__isnull=True)

    def _crear(self, username, password, **extra):
        username = normalizar_usuario(username)
        if not username:
            raise ValueError("El nombre de usuario es obligatorio.")
        extra["email"] = self.normalize_email(extra.get("email") or "")
        usuario = self.model(username=username, **extra)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_user(self, username, email=None, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._crear(username, password, email=email, **extra)

    def create_superuser(self, username, email=None, password=None, **extra):
        extra["is_staff"] = extra["is_superuser"] = True
        extra["organizacion_cuenta"] = None
        return self._crear(username, password, email=email, **extra)


class Usuario(AbstractUser):
    """Cada organización tiene sus propios usuarios (como en Ordo).

    - `organizacion_cuenta` + `username` es único: «maria» puede existir en
      dos organizaciones. Se entra por el enlace de la organización (/<slug>/).
    - Las cuentas de plataforma (superadmin de Arca) no tienen organización y
      entran por la dirección principal.
    - Qué puede hacer cada quien no vive aquí: vive en su `Membresia`."""

    username = models.CharField(
        "usuario", max_length=150, validators=[UnicodeUsernameValidator()],
        help_text="Letras, números y . _ - @ (sin espacios). Se guarda en minúsculas.",
    )
    organizacion_cuenta = models.ForeignKey(
        "organizaciones.Organizacion", null=True, blank=True, on_delete=models.PROTECT, related_name="usuarios_propios",
        verbose_name="organización de la cuenta", help_text="Vacío = cuenta de plataforma (soporte de Arca).",
    )
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    debe_cambiar_clave = models.BooleanField(
        default=False,
        help_text="Se enciende al crear el usuario o restablecer su clave con una temporal; "
        "se apaga cuando la cambia. Mientras esté encendido no puede usar el sistema.",
    )

    objects = UsuarioManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        constraints = [
            models.UniqueConstraint(fields=["organizacion_cuenta", "username"], name="usuario_unico_por_organizacion"),
            models.UniqueConstraint(
                fields=["username"], condition=Q(organizacion_cuenta__isnull=True), name="usuario_plataforma_unico",
            ),
        ]

    def save(self, *args, **kwargs):
        self.username = normalizar_usuario(self.username)
        super().save(*args, **kwargs)

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
        DAR_ACCESO = "dar_acceso", "Acceso al sistema para un miembro"
        CREAR_EJERCICIO = "crear_ejercicio", "Creación de ejercicio"
        ACTIVAR_EJERCICIO = "activar_ejercicio", "Activación de ejercicio"
        CERRAR_EJERCICIO = "cerrar_ejercicio", "Cierre de ejercicio"
        CREAR_CAJA = "crear_caja", "Creación de caja"
        EDITAR_CAJA = "editar_caja", "Edición de caja"
        CREAR_CUENTA = "crear_cuenta", "Creación de cuenta"
        EDITAR_CUENTA = "editar_cuenta", "Edición de cuenta"
        AJUSTAR_SALDO_CUENTA = "ajustar_saldo_cuenta", "Ajuste de saldo inicial de cuenta"
        CREAR_CONCEPTO = "crear_concepto", "Creación de concepto"
        EDITAR_CONCEPTO = "editar_concepto", "Edición de concepto"
        REGISTRAR_MOVIMIENTO = "registrar_movimiento", "Registro de ingreso o egreso"
        APROBAR_MOVIMIENTO = "aprobar_movimiento", "Aprobación de egreso"
        ANULAR_MOVIMIENTO = "anular_movimiento", "Anulación de movimiento"
        REGISTRAR_TRASLADO = "registrar_traslado", "Traslado entre cuentas"
        ANULAR_TRASLADO = "anular_traslado", "Anulación de traslado"
        CREAR_PRESUPUESTO = "crear_presupuesto", "Creación de presupuesto"
        EDITAR_PRESUPUESTO = "editar_presupuesto", "Edición de presupuesto"
        APROBAR_PRESUPUESTO = "aprobar_presupuesto", "Aprobación de presupuesto"
        REABRIR_PRESUPUESTO = "reabrir_presupuesto", "Reapertura de presupuesto"
        ELIMINAR_PRESUPUESTO = "eliminar_presupuesto", "Eliminación de presupuesto"
        EMITIR_REPORTE = "emitir_reporte", "Emisión de reporte"
        CREAR_CUOTA = "crear_cuota", "Creación de cuota"
        EDITAR_CUOTA = "editar_cuota", "Edición de cuota"
        ASIGNAR = "asignar", "Asignación a un miembro"
        REGISTRAR_ARQUEO = "registrar_arqueo", "Arqueo de cuenta"
        AJUSTAR_ARQUEO = "ajustar_arqueo", "Ajuste por diferencia de arqueo"
        ENTREGAR_ANTICIPO = "entregar_anticipo", "Entrega de anticipo"
        RENDIR_ANTICIPO = "rendir_anticipo", "Rendición de anticipo"
        ANULAR_ANTICIPO = "anular_anticipo", "Anulación de anticipo"
        CREAR_ARTICULO = "crear_articulo", "Alta de artículo de inventario"
        EDITAR_ARTICULO = "editar_articulo", "Edición de artículo de inventario"
        MOVER_INVENTARIO = "mover_inventario", "Movimiento de inventario"
        ANULAR_INVENTARIO = "anular_inventario", "Anulación de movimiento de inventario"
        EDITAR_SUSCRIPCION = "editar_suscripcion", "Cambio de suscripción (plataforma)"
        VER_CUENTA_PERSONAL = "ver_cuenta_personal", "Consulta de la cuenta personal de un miembro"
        EXPORTAR_DATOS = "exportar_datos", "Exportación de los datos a Excel"
        IMPORTAR_DATOS = "importar_datos", "Carga de datos desde Excel"

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
