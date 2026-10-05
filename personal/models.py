"""La cuenta personal de un miembro (Fase 5).

Es SU herramienta de autocontrol: anota lo que le asignan y lo que gasta. Vive
en tablas aparte del libro de la organización para que ningún reporte de la
organización la incluya por accidente.

Quién la ve: su dueño siempre. El director, solo si el superadmin encendió
`Organizacion.director_ve_cuentas_personales`, y entonces en solo lectura
(A-06). Sin eso, el director ve únicamente cuánto asignó.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from cambio.models import MontoBimonedaMixin
from organizaciones.models import ModeloDeOrganizacion


class ConceptoPersonal(ModeloDeOrganizacion):
    class Tipo(models.TextChoices):
        INGRESO = "ingreso", "Ingreso"
        EGRESO = "egreso", "Egreso"

    # Vacío = sugerido por la organización para todos sus miembros.
    membresia = models.ForeignKey(
        "organizaciones.Membresia", null=True, blank=True, on_delete=models.CASCADE, related_name="conceptos_personales",
    )
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    nombre = models.CharField(max_length=80)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "concepto personal"
        verbose_name_plural = "conceptos personales"
        ordering = ["tipo", "nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if self.membresia_id and self.membresia.organizacion_id != self.organizacion_id:
            raise ValidationError("El concepto es de otra organización.")
        super().save(*args, **kwargs)


class MovimientoPersonal(MontoBimonedaMixin, ModeloDeOrganizacion):
    class Tipo(models.TextChoices):
        INGRESO = "ingreso", "Ingreso"
        EGRESO = "egreso", "Egreso"

    membresia = models.ForeignKey(
        "organizaciones.Membresia", on_delete=models.PROTECT, related_name="movimientos_personales",
    )
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    fecha = models.DateField()
    concepto = models.ForeignKey(
        ConceptoPersonal, null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos",
    )
    descripcion = models.CharField("descripción", max_length=200, blank=True)
    tasa = models.ForeignKey("cambio.TasaCambio", on_delete=models.PROTECT, related_name="movimientos_personales")
    # Si viene de una asignación: el egreso de la organización que la originó.
    # Solo cuenta mientras ese egreso esté confirmado, y su dueño no la edita.
    origen = models.OneToOneField(
        "finanzas.Movimiento", null=True, blank=True, on_delete=models.PROTECT, related_name="asignacion_personal",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento personal"
        verbose_name_plural = "movimientos personales"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="personal_monto_positivo"),
            models.CheckConstraint(
                condition=Q(concepto__isnull=False) | ~Q(descripcion=""), name="personal_concepto_o_descripcion",
            ),
        ]
        indexes = [models.Index(fields=["membresia", "fecha"])]

    def __str__(self):
        return f"{self.get_tipo_display()} personal — {self.titulo}"

    @property
    def titulo(self):
        return self.concepto.nombre if self.concepto_id else self.descripcion

    @property
    def es_ingreso(self):
        return self.tipo == self.Tipo.INGRESO

    @property
    def es_asignacion(self):
        return self.origen_id is not None

    def clean(self):
        errores = {}
        if self.concepto_id:
            c = self.concepto
            if c.organizacion_id != self.organizacion_id or (c.membresia_id and c.membresia_id != self.membresia_id):
                errores["concepto"] = "Ese concepto no es tuyo."
            elif c.tipo != self.tipo:
                errores["concepto"] = "Ese concepto no corresponde a este tipo de movimiento."
        elif not (self.descripcion or "").strip():
            errores["descripcion"] = "Sin concepto, la descripción es obligatoria."
        if self.monto is not None and self.monto <= 0:
            errores["monto"] = "El monto debe ser mayor que cero."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        if self.membresia.organizacion_id != self.organizacion_id:
            raise ValidationError("El movimiento es de otra organización.")
        if self.concepto_id and self.concepto.membresia_id and self.concepto.membresia_id != self.membresia_id:
            raise ValidationError("El concepto es de otro miembro.")
        self.calcular_montos()
        super().save(*args, **kwargs)
