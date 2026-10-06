"""Inventario de recursos físicos (Fase 7).

Dos clases de artículo en el mismo catálogo:

- BIEN: lo que se conserva (sillas, equipos). Tiene estado y puede tener un
  responsable.
- CONSUMIBLE: lo que se gasta (comida, limpieza). Tiene un mínimo que avisa.

Las existencias NO se guardan: son la suma de los movimientos vigentes, por
artículo y ubicación (inventario/services.py). Un movimiento no se edita: se
anula con motivo y se registra de nuevo, igual que en el libro de caja.

El inventario no toca el dinero (decisión A-39): el valor de cada artículo es
informativo, para saber cuánto vale lo que hay.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from organizaciones.models import ModeloDeOrganizacion


class Ubicacion(ModeloDeOrganizacion):
    nombre = models.CharField(max_length=80)
    descripcion = models.CharField("descripción", max_length=200, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "ubicación"
        verbose_name_plural = "ubicaciones"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["organizacion", "nombre"], name="ubicacion_unica_por_organizacion"),
        ]

    def __str__(self):
        return self.nombre


class CategoriaArticulo(ModeloDeOrganizacion):
    nombre = models.CharField(max_length=80)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["organizacion", "nombre"], name="categoria_articulo_unica_por_organizacion"),
        ]

    def __str__(self):
        return self.nombre


class Articulo(ModeloDeOrganizacion):
    class Clase(models.TextChoices):
        BIEN = "bien", "Bien"
        CONSUMIBLE = "consumible", "Consumible"

    class Estado(models.TextChoices):
        BUENO = "bueno", "Bueno"
        REGULAR = "regular", "Regular"
        MALO = "malo", "Malo"

    class Moneda(models.TextChoices):
        USD = "USD", "Dólares"
        VES = "VES", "Bolívares"

    clase = models.CharField(max_length=12, choices=Clase.choices, default=Clase.BIEN)
    nombre = models.CharField(max_length=120)
    codigo = models.CharField("código", max_length=40, blank=True, help_text="Opcional: serial, etiqueta o código propio.")
    categoria = models.ForeignKey(
        CategoriaArticulo, null=True, blank=True, on_delete=models.PROTECT, related_name="articulos",
        verbose_name="categoría",
    )
    unidad = models.CharField(max_length=20, default="unidad", help_text="Cómo se cuenta: unidad, kg, litro, caja…")
    minimo = models.DecimalField(
        "mínimo", max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Solo consumibles: por debajo de esta cantidad total, avisa.",
    )
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BUENO, help_text="Solo bienes.")
    responsable = models.ForeignKey(
        "organizaciones.Membresia", null=True, blank=True, on_delete=models.PROTECT, related_name="articulos_a_cargo",
        help_text="Opcional: el miembro que lo tiene a su cargo.",
    )
    valor_unitario = models.DecimalField(
        "valor por unidad", max_digits=18, decimal_places=2, null=True, blank=True,
        help_text="Opcional. Sirve para saber cuánto vale lo que hay; no toca el libro de caja.",
    )
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.USD)
    nota = models.CharField(max_length=200, blank=True)
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "artículo"
        verbose_name_plural = "artículos"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["organizacion", "nombre"], name="articulo_unico_por_organizacion"),
            models.CheckConstraint(condition=Q(minimo__isnull=True) | Q(minimo__gte=0), name="articulo_minimo_no_negativo"),
            models.CheckConstraint(
                condition=Q(valor_unitario__isnull=True) | Q(valor_unitario__gte=0), name="articulo_valor_no_negativo",
            ),
        ]

    def __str__(self):
        return self.nombre

    @property
    def es_consumible(self):
        return self.clase == self.Clase.CONSUMIBLE

    def clean(self):
        errores = {}
        if self.categoria_id and self.categoria.organizacion_id != self.organizacion_id:
            errores["categoria"] = "Esa categoría es de otra organización."
        if self.responsable_id and self.responsable.organizacion_id != self.organizacion_id:
            errores["responsable"] = "Ese miembro es de otra organización."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        if (self.categoria_id and self.categoria.organizacion_id != self.organizacion_id) or (
                self.responsable_id and self.responsable.organizacion_id != self.organizacion_id):
            raise ValidationError("El artículo mezcla datos de dos organizaciones.")
        if not self.es_consumible:
            self.minimo = None
        super().save(*args, **kwargs)


class MovimientoInventario(ModeloDeOrganizacion):
    class Tipo(models.TextChoices):
        ENTRADA = "entrada", "Entrada"
        SALIDA = "salida", "Salida"
        TRASLADO = "traslado", "Traslado"

    class Motivo(models.TextChoices):
        INICIAL = "inicial", "Existencia inicial"
        COMPRA = "compra", "Compra"
        DONACION = "donacion", "Donación recibida"
        CONSUMO = "consumo", "Consumo / uso"
        ENTREGA = "entrega", "Entrega o donación a terceros"
        BAJA = "baja", "Baja por daño o desuso"
        PERDIDA = "perdida", "Pérdida"
        AJUSTE = "ajuste", "Ajuste por conteo"
        TRASLADO = "traslado", "Cambio de ubicación"

    MOTIVOS_POR_TIPO = {
        "entrada": ["inicial", "compra", "donacion", "ajuste"],
        "salida": ["consumo", "entrega", "baja", "perdida", "ajuste"],
        "traslado": ["traslado"],
    }

    articulo = models.ForeignKey(Articulo, on_delete=models.PROTECT, related_name="movimientos", verbose_name="artículo")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    motivo = models.CharField(max_length=12, choices=Motivo.choices)
    fecha = models.DateField(default=timezone.localdate)
    cantidad = models.DecimalField(max_digits=12, decimal_places=2)
    origen = models.ForeignKey(
        Ubicacion, null=True, blank=True, on_delete=models.PROTECT, related_name="salidas", verbose_name="sale de",
    )
    destino = models.ForeignKey(
        Ubicacion, null=True, blank=True, on_delete=models.PROTECT, related_name="entradas", verbose_name="entra a",
    )
    nota = models.CharField(max_length=200, blank=True)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimientos_inventario",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    anulado = models.BooleanField(default=False)
    motivo_anulacion = models.CharField("motivo de la anulación", max_length=200, blank=True)
    anulado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="anulaciones_inventario",
    )

    class Meta:
        verbose_name = "movimiento de inventario"
        verbose_name_plural = "movimientos de inventario"
        ordering = ["-fecha", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(cantidad__gt=0), name="inventario_cantidad_positiva"),
            # Entrada: solo destino. Salida: solo origen. Traslado: los dos y distintos.
            models.CheckConstraint(
                condition=(
                    Q(tipo="entrada", origen__isnull=True, destino__isnull=False)
                    | Q(tipo="salida", origen__isnull=False, destino__isnull=True)
                    | (Q(tipo="traslado", origen__isnull=False, destino__isnull=False) & ~Q(origen=models.F("destino")))
                ),
                name="inventario_ubicaciones_segun_tipo",
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} de {self.cantidad.normalize():f} {self.articulo.nombre}"

    def clean(self):
        errores = {}
        org = self.organizacion_id
        if self.articulo_id and self.articulo.organizacion_id != org:
            errores["articulo"] = "Ese artículo es de otra organización."
        for campo in ("origen", "destino"):
            ubicacion = getattr(self, campo, None)
            if ubicacion is not None and ubicacion.organizacion_id != org:
                errores[campo] = "Esa ubicación es de otra organización."
        if self.cantidad is not None and self.cantidad <= Decimal("0"):
            errores["cantidad"] = "La cantidad debe ser mayor que cero."
        if self.tipo and self.motivo and self.motivo not in self.MOTIVOS_POR_TIPO.get(self.tipo, []):
            errores["motivo"] = "Ese motivo no corresponde a este tipo de movimiento."
        if self.tipo == self.Tipo.TRASLADO and self.origen_id and self.origen_id == self.destino_id:
            errores["destino"] = "Elige una ubicación distinta a la de origen."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        ids = {self.articulo.organizacion_id}
        ids.update(u.organizacion_id for u in (self.origen, self.destino) if u is not None)
        if ids != {self.organizacion_id}:
            raise ValidationError("El movimiento mezcla datos de dos organizaciones.")
        super().save(*args, **kwargs)
