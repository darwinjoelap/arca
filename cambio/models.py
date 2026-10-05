from django.conf import settings
from django.db import models
from simple_history.models import HistoricalRecords


class TasaCambio(models.Model):
    """Tasa de cambio Bs./USD de un día y una fuente.

    Es GLOBAL: una sola fila por día y fuente sirve a todas las organizaciones
    (no hereda de ModeloDeOrganizacion). Por eso solo la carga el superadmin o,
    desde la Fase 2, el comando que consulta el BCV.

    Regla heredada de Edumia (D-02 revisado): `valor` se puede corregir. Al
    hacerlo, `save()` recalcula las transacciones que usan la tasa y todavía
    no están congeladas; las ya aprobadas o anuladas no se tocan (D-09)."""

    class Fuente(models.TextChoices):
        BCV = "bcv", "BCV"
        PARALELO = "paralelo", "Paralelo"
        MANUAL = "manual", "Manual"

    fecha = models.DateField()
    valor = models.DecimalField(max_digits=18, decimal_places=4, help_text="Bs. por 1 USD.")
    fuente = models.CharField(max_length=10, choices=Fuente.choices)
    cargada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasas_cargadas"
    )
    creada_en = models.DateTimeField(auto_now_add=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "tasa de cambio"
        verbose_name_plural = "tasas de cambio"
        constraints = [
            models.UniqueConstraint(fields=["fecha", "fuente"], name="tasa_unica_por_fecha_y_fuente"),
            models.CheckConstraint(condition=models.Q(valor__gt=0), name="tasa_valor_positivo"),
        ]
        indexes = [
            models.Index(fields=["fuente", "-fecha"]),
        ]
        ordering = ["-fecha", "fuente"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._valor_original = self.valor

    def __str__(self):
        return f"{self.fecha} · {self.get_fuente_display()}: {self.valor}"

    def _transacciones_recalculables(self):
        """Conjuntos de transacciones que se recalculan si `valor` cambia:
        solo las que todavía no están congeladas (D-09). Hoy, los movimientos
        del libro que esperan aprobación; la cuenta personal se suma en su fase."""
        from finanzas.models import Movimiento

        return [self.movimientos.filter(estado=Movimiento.Estado.REGISTRADO)]

    def tiene_transacciones(self):
        """True si algún movimiento quedó registrado con esta tasa."""
        return self.movimientos.exists()

    def save(self, *args, **kwargs):
        valor_cambio = self.pk and self.valor != self._valor_original
        super().save(*args, **kwargs)
        if valor_cambio:
            for conjunto in self._transacciones_recalculables():
                for transaccion in conjunto:
                    transaccion.save()  # dispara calcular_montos() con el nuevo valor
        self._valor_original = self.valor


class MontoBimonedaMixin(models.Model):
    """Abstracto: campos de dinero bimoneda. Toda la aritmética pasa por
    `cambio/services.py`; nada aquí redondea por su cuenta.

    El modelo concreto debe tener una FK `tasa` a TasaCambio."""

    class Moneda(models.TextChoices):
        VES = "VES", "Bolívares"
        USD = "USD", "Dólares"

    monto = models.DecimalField(max_digits=18, decimal_places=4)
    moneda = models.CharField(max_length=3, choices=Moneda.choices)
    tasa_aplicada = models.DecimalField(max_digits=18, decimal_places=4, editable=False)
    monto_ves = models.DecimalField(max_digits=18, decimal_places=4, editable=False)
    monto_usd = models.DecimalField(max_digits=18, decimal_places=4, editable=False)

    class Meta:
        abstract = True

    def calcular_montos(self):
        """Fija `tasa_aplicada` y ambos equivalentes a partir de `self.tasa`.
        Lo llama el `save()` del modelo concreto, salvo que el registro ya
        esté aprobado: lo aprobado no se recalcula (D-09)."""
        from .services import convertir  # import diferido: evita el ciclo models <-> services

        self.tasa_aplicada = self.tasa.valor
        self.monto_ves, self.monto_usd = convertir(self.monto, self.moneda, self.tasa.valor)
