"""Multi-organización: una sola base de datos y una FK `organizacion` en cada
tabla con datos de una organización (decisión A-01, docs/DECISIONES.md).

Todo modelo que guarde datos de una organización hereda de
`ModeloDeOrganizacion`. El test de aislamiento (organizaciones/tests.py)
recorre esos modelos, así que heredar de aquí es lo que los mete en la prueba.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

# Los permisos que una organización puede encender en un tipo de miembro.
# Es la única lista: formularios, plantillas y `Membresia.tiene_permiso` leen de aquí.
PERMISOS = [
    ("puede_registrar_ingresos", "Registrar ingresos", "Registrar ingresos de la organización."),
    ("puede_registrar_egresos", "Registrar egresos", "Registrar egresos de la organización."),
    ("puede_ver_presupuesto", "Ver presupuesto", "Ver partidas, topes y lo ejecutado."),
    ("puede_ver_movimientos", "Ver movimientos", "Ver el libro completo, no solo lo propio."),
    ("puede_gestionar_inventario", "Gestionar inventario", "Altas, bajas y traslados de bienes."),
    ("puede_ver_reportes", "Ver reportes", "Reportes y análisis de la organización, con Excel y PDF."),
    ("tiene_cuenta_personal", "Cuenta personal", "Recibir asignaciones y llevar su propio control."),
]
NOMBRES_PERMISOS = [nombre for nombre, _, _ in PERMISOS]


class Organizacion(models.Model):
    class Moneda(models.TextChoices):
        VES = "VES", "Bolívares"
        USD = "USD", "Dólares"

    class Plan(models.TextChoices):
        PRUEBA = "prueba", "Prueba"
        BASICO = "basico", "Básico"
        PRO = "pro", "Pro"

    nombre = models.CharField(max_length=200)
    slug = models.SlugField(max_length=60, unique=True)
    rif = models.CharField("RIF", max_length=20, blank=True)
    direccion = models.TextField("dirección", blank=True)
    telefono = models.CharField("teléfono", max_length=30, blank=True)
    email = models.EmailField("correo", blank=True)
    moneda_base = models.CharField(
        max_length=3, choices=Moneda.choices, default=Moneda.USD,
        help_text="Moneda en la que se muestran primero los saldos y se arman los presupuestos.",
    )
    requiere_aprobacion_egresos = models.BooleanField(
        "requiere aprobación de egresos", default=False,
        help_text="Si está encendido, un egreso registrado queda pendiente hasta que "
        "el director o un administrador lo apruebe.",
    )
    director_ve_cuentas_personales = models.BooleanField(
        "el director ve las cuentas personales", default=False,
        help_text="Lo decide el superadmin de la plataforma, no la organización. Apagado: el "
        "director solo ve cuánto asignó a cada miembro. Encendido: ve además sus saldos y "
        "movimientos personales, en solo lectura. Cada cambio queda en la bitácora.",
    )
    activa = models.BooleanField(
        default=True, help_text="Apagada, nadie de la organización puede entrar.",
    )
    # --- Suscripción: lo maneja solo el superadmin, desde /plataforma/ ---
    plan = models.CharField(max_length=10, choices=Plan.choices, default=Plan.PRUEBA)
    activa_hasta = models.DateField(
        "activa hasta", null=True, blank=True, help_text="Vacío = sin vencimiento. Pasada la fecha, nadie entra.",
    )
    limite_usuarios = models.PositiveSmallIntegerField(
        "límite de usuarios con acceso", null=True, blank=True,
        help_text="Vacío = sin límite. Los miembros sin acceso al sistema no cuentan.",
    )
    notas = models.TextField("notas internas", blank=True, help_text="Solo las ve la plataforma.")
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "organización"
        verbose_name_plural = "organizaciones"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    @staticmethod
    def q_vigente(prefijo=""):
        """Filtro de organizaciones que dejan entrar hoy: no suspendidas ni vencidas.
        `prefijo` para usarlo desde otro modelo: q_vigente("organizacion__")."""
        return Q(**{f"{prefijo}activa": True}) & (
            Q(**{f"{prefijo}activa_hasta__isnull": True}) | Q(**{f"{prefijo}activa_hasta__gte": timezone.localdate()})
        )

    @property
    def dias_para_vencer(self):
        if not self.activa_hasta:
            return None
        return (self.activa_hasta - timezone.localdate()).days

    @property
    def vencida(self):
        return self.activa_hasta is not None and self.activa_hasta < timezone.localdate()

    @property
    def esta_vigente(self):
        return self.activa and not self.vencida

    @property
    def estado_texto(self):
        return "Suspendida" if not self.activa else "Vencida" if self.vencida else "Activa"

    def usuarios_con_acceso(self):
        """Membresías activas que pueden entrar: es lo que cuenta para el límite del plan."""
        return self.membresias.filter(activa=True, user__isnull=False).count()

    @property
    def director(self):
        """La membresía dueña (hay una sola por organización), o None."""
        return self.membresias.filter(es_dueno=True).select_related("user").first()


class ModeloDeOrganizacion(models.Model):
    """Abstracto: todo dato que pertenece a una organización."""

    organizacion = models.ForeignKey(
        Organizacion, on_delete=models.PROTECT, related_name="%(class)ss",
        verbose_name="organización",
    )

    class Meta:
        abstract = True


class TipoMiembro(ModeloDeOrganizacion):
    """Un tipo de usuario con nombre libre y permisos que la organización
    enciende o apaga. Reemplaza los roles fijos de Edumia."""

    nombre = models.CharField(max_length=60)
    puede_registrar_ingresos = models.BooleanField("registrar ingresos", default=False)
    puede_registrar_egresos = models.BooleanField("registrar egresos", default=False)
    puede_ver_presupuesto = models.BooleanField("ver presupuesto", default=False)
    puede_ver_movimientos = models.BooleanField("ver movimientos", default=False)
    puede_gestionar_inventario = models.BooleanField("gestionar inventario", default=False)
    puede_ver_reportes = models.BooleanField("ver reportes", default=False)
    tiene_cuenta_personal = models.BooleanField("cuenta personal", default=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "tipo de miembro"
        verbose_name_plural = "tipos de miembro"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["organizacion", "nombre"], name="tipo_unico_por_organizacion"),
        ]

    def __str__(self):
        return self.nombre

    def permisos_activos(self):
        return [etiqueta for nombre, etiqueta, _ in PERMISOS if getattr(self, nombre)]


class Membresia(ModeloDeOrganizacion):
    """La pertenencia de un usuario a una organización.

    Hay un único rol fijo: el director, que es el dueño (`es_dueno`) y tiene
    control total. Puede nombrar administradores (`es_administrador`), con los
    mismos permisos salvo tocar al dueño o nombrar a otros. Todo lo demás lo
    decide el `tipo`."""

    # Vacío = miembro de la comunidad que no entra al sistema (aporta, recibe,
    # tiene cuotas), pero figura en el libro y en los reportes. Se le puede
    # dar acceso después sin perder su historia.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="membresias",
        verbose_name="usuario",
    )
    tipo = models.ForeignKey(
        TipoMiembro, null=True, blank=True, on_delete=models.PROTECT, related_name="membresias",
        help_text="Obligatorio salvo para el director y los administradores.",
    )
    es_dueno = models.BooleanField("es el director (dueño)", default=False)
    es_administrador = models.BooleanField("es administrador", default=False)
    nombre_visible = models.CharField(
        max_length=120, blank=True,
        help_text="Cómo aparece esta persona dentro de la organización. Vacío: su nombre de usuario.",
    )
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "membresía"
        verbose_name_plural = "membresías"
        ordering = ["-es_dueno", "-es_administrador", "nombre_visible", "user__username"]
        constraints = [
            models.UniqueConstraint(fields=["user", "organizacion"], name="una_membresia_por_usuario_y_organizacion"),
            models.UniqueConstraint(
                fields=["organizacion"], condition=Q(es_dueno=True), name="un_solo_dueno_por_organizacion",
            ),
            models.CheckConstraint(
                condition=Q(es_dueno=True) | Q(es_administrador=True) | Q(tipo__isnull=False),
                name="miembro_comun_con_tipo",
            ),
            # Sin usuario no hay de dónde sacar el nombre, ni puede administrar.
            models.CheckConstraint(
                condition=Q(user__isnull=False) | (~Q(nombre_visible="") & Q(es_dueno=False) & Q(es_administrador=False)),
                name="miembro_sin_usuario_con_nombre_y_sin_mando",
            ),
        ]

    def __str__(self):
        return f"{self.nombre} — {self.organizacion}"

    @property
    def nombre(self):
        if self.nombre_visible or not self.user_id:
            return self.nombre_visible
        return self.user.nombre_para_mostrar()

    @property
    def tiene_acceso(self):
        """True si la persona puede entrar al sistema con esta membresía."""
        return self.user_id is not None

    @property
    def usuario_texto(self):
        return self.user.username if self.user_id else "sin acceso"

    @property
    def puede_administrar(self):
        return self.es_dueno or self.es_administrador

    @property
    def rol_visible(self):
        if self.es_dueno:
            return "Director"
        if self.es_administrador:
            return "Administrador"
        return self.tipo.nombre if self.tipo_id else "—"

    def tiene_permiso(self, permiso):
        """`permiso` es "administrar" o uno de NOMBRES_PERMISOS."""
        if not self.activa:
            return False
        if self.puede_administrar:
            return True
        if permiso not in NOMBRES_PERMISOS or not self.tipo_id or not self.tipo.activo:
            return False
        return bool(getattr(self.tipo, permiso))

    def clean(self):
        if self.tipo_id and self.organizacion_id and self.tipo.organizacion_id != self.organizacion_id:
            raise ValidationError({"tipo": "Ese tipo de miembro es de otra organización."})
        if not (self.es_dueno or self.es_administrador or self.tipo_id):
            raise ValidationError({"tipo": "Elige un tipo de miembro."})
        if not self.user_id:
            if not (self.nombre_visible or "").strip():
                raise ValidationError({"nombre_visible": "Un miembro sin acceso necesita un nombre."})
            if self.es_dueno or self.es_administrador:
                raise ValidationError("El director y los administradores necesitan un usuario para entrar.")

    def save(self, *args, **kwargs):
        # Segunda barrera además de clean(): el tipo nunca cruza de organización,
        # aunque el guardado no venga de un formulario.
        if self.tipo_id and self.tipo.organizacion_id != self.organizacion_id:
            raise ValidationError("El tipo de miembro es de otra organización.")
        # Cada organización tiene sus propias cuentas: una cuenta no cruza a otra.
        if self.user_id:
            cuenta = self.user
            if cuenta.is_superuser:
                raise ValidationError("Una cuenta de plataforma no puede ser miembro de una organización.")
            if cuenta.organizacion_cuenta_id is None:
                cuenta.organizacion_cuenta_id = self.organizacion_id     # cuenta suelta: queda como propia
                cuenta.save(update_fields=["organizacion_cuenta"])
            elif cuenta.organizacion_cuenta_id != self.organizacion_id:
                raise ValidationError("Ese usuario es de otra organización.")
        super().save(*args, **kwargs)


class Ejercicio(ModeloDeOrganizacion):
    """Período contable (normalmente un año). Adaptado de PeriodoEscolar de Edumia."""

    nombre = models.CharField(max_length=30, help_text="Ej: 2026")
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    activo = models.BooleanField(default=False)
    cerrado = models.BooleanField(default=False)
    cerrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="ejercicios_cerrados",
    )
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "ejercicio"
        verbose_name_plural = "ejercicios"
        ordering = ["-fecha_inicio"]
        constraints = [
            models.UniqueConstraint(fields=["organizacion", "nombre"], name="ejercicio_unico_por_organizacion"),
            models.UniqueConstraint(
                fields=["organizacion"], condition=Q(activo=True), name="un_solo_ejercicio_activo_por_organizacion",
            ),
            models.CheckConstraint(
                condition=Q(fecha_inicio__lt=models.F("fecha_fin")), name="ejercicio_inicio_antes_de_fin",
            ),
        ]

    def __str__(self):
        return self.nombre

    def clean(self):
        if self.fecha_inicio and self.fecha_fin and self.fecha_inicio >= self.fecha_fin:
            raise ValidationError("La fecha de inicio debe ser anterior a la fecha de fin.")
        if self.fecha_inicio and self.fecha_fin and self.organizacion_id:
            traslapes = Ejercicio.objects.filter(
                organizacion_id=self.organizacion_id,
                fecha_inicio__lte=self.fecha_fin,
                fecha_fin__gte=self.fecha_inicio,
            ).exclude(pk=self.pk)
            if traslapes.exists():
                raise ValidationError("Las fechas se traslapan con otro ejercicio existente.")
