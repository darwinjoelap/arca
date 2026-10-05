"""Presupuestos (Fase 4).

Un presupuesto por caja y ejercicio, en una moneda, con un monto MENSUAL por
concepto (así trabajan los Excel: el anual es el mensual por doce).

Lo ejecutado no se guarda: es la suma de los movimientos confirmados de ese
concepto, en la moneda del presupuesto, con el equivalente congelado de cada
movimiento (presupuestos/services.py).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from organizaciones.models import ModeloDeOrganizacion


class Presupuesto(ModeloDeOrganizacion):
    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        APROBADO = "aprobado", "Aprobado"

    class Moneda(models.TextChoices):
        USD = "USD", "Dólares"
        VES = "VES", "Bolívares"

    caja = models.ForeignKey("finanzas.Caja", on_delete=models.PROTECT, related_name="presupuestos")
    ejercicio = models.ForeignKey("organizaciones.Ejercicio", on_delete=models.PROTECT, related_name="presupuestos")
    moneda = models.CharField(
        max_length=3, choices=Moneda.choices, default=Moneda.USD,
        help_text="La moneda en la que se planifica. Lo ejecutado se compara en esta misma moneda.",
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    nota = models.TextField(blank=True)
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="presupuestos_aprobados",
    )
    fecha_aprobacion = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "presupuesto"
        verbose_name_plural = "presupuestos"
        ordering = ["-ejercicio__fecha_inicio", "caja__nombre"]
        constraints = [
            models.UniqueConstraint(fields=["caja", "ejercicio"], name="un_presupuesto_por_caja_y_ejercicio"),
        ]

    def __str__(self):
        return f"Presupuesto {self.caja.nombre} {self.ejercicio.nombre}"

    @property
    def editable(self):
        return self.estado == self.Estado.BORRADOR and not self.ejercicio.cerrado

    def clean(self):
        errores = {}
        if self.caja_id and self.caja.organizacion_id != self.organizacion_id:
            errores["caja"] = "Esa caja es de otra organización."
        if self.ejercicio_id and self.ejercicio.organizacion_id != self.organizacion_id:
            errores["ejercicio"] = "Ese ejercicio es de otra organización."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        if self.caja.organizacion_id != self.organizacion_id or self.ejercicio.organizacion_id != self.organizacion_id:
            raise ValidationError("El presupuesto mezcla datos de dos organizaciones.")
        super().save(*args, **kwargs)


class PartidaPresupuestaria(ModeloDeOrganizacion):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name="partidas")
    concepto = models.ForeignKey("finanzas.Concepto", on_delete=models.PROTECT, related_name="partidas")
    monto_mensual = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    requiere_solicitud = models.BooleanField(
        "se pide con antelación", default=False,
        help_text="Partidas que no tienen un monto fijo y se solicitan indicando el monto exacto.",
    )
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "partida presupuestaria"
        verbose_name_plural = "partidas presupuestarias"
        ordering = ["concepto__tipo", "concepto__nombre"]
        constraints = [
            models.UniqueConstraint(fields=["presupuesto", "concepto"], name="una_partida_por_concepto"),
            models.CheckConstraint(condition=Q(monto_mensual__gte=0), name="partida_monto_no_negativo"),
        ]

    def __str__(self):
        return f"{self.concepto} — {self.monto_mensual}"

    def save(self, *args, **kwargs):
        if self.presupuesto.organizacion_id != self.organizacion_id or self.concepto.organizacion_id != self.organizacion_id:
            raise ValidationError("La partida mezcla datos de dos organizaciones.")
        if self.concepto.caja_id and self.concepto.caja_id != self.presupuesto.caja_id:
            raise ValidationError("Ese concepto pertenece a otra caja.")
        super().save(*args, **kwargs)
