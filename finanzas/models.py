"""Libro de caja (Fase 3).

- `Caja`: una bolsa de dinero con su propio presupuesto (el Excel lleva dos).
- `Cuenta`: dónde está físicamente el dinero de una caja (efectivo, banco),
  en UNA moneda. El saldo inicial vive aquí.
- `Concepto`: la lista de «cuentas válidas» del Excel, con tipo y dos niveles.
- `Movimiento`: un ingreso o un egreso. Un movimiento, un monto (A-14).

No hay tablas de saldos: se calculan sumando movimientos (finanzas/services.py).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from cambio.models import MontoBimonedaMixin
from organizaciones.models import ModeloDeOrganizacion


class Caja(ModeloDeOrganizacion):
    nombre = models.CharField(max_length=80)
    descripcion = models.CharField("descripción", max_length=200, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "caja"
        verbose_name_plural = "cajas"
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(fields=["organizacion", "nombre"], name="caja_unica_por_organizacion"),
        ]

    def __str__(self):
        return self.nombre


class Cuenta(ModeloDeOrganizacion):
    class Tipo(models.TextChoices):
        EFECTIVO = "efectivo", "Efectivo"
        BANCO = "banco", "Banco"

    class Moneda(models.TextChoices):
        VES = "VES", "Bolívares"
        USD = "USD", "Dólares"

    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name="cuentas")
    nombre = models.CharField(max_length=80, help_text="Ej: Efectivo USD, Banesco, Pago móvil.")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.EFECTIVO)
    moneda = models.CharField(
        max_length=3, choices=Moneda.choices,
        help_text="La moneda en la que está el dinero. No se puede cambiar después del primer movimiento.",
    )
    banco = models.CharField(max_length=80, blank=True)
    saldo_inicial = models.DecimalField(
        max_digits=18, decimal_places=4, default=0,
        help_text="Lo que había en la cuenta antes de empezar a usar Arca, en su moneda.",
    )
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "cuenta"
        verbose_name_plural = "cuentas"
        ordering = ["caja__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["caja", "nombre"], name="cuenta_unica_por_caja"),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.moneda})"

    def clean(self):
        if self.caja_id and self.organizacion_id and self.caja.organizacion_id != self.organizacion_id:
            raise ValidationError({"caja": "Esa caja es de otra organización."})
        if self.pk:
            anterior = Cuenta.objects.filter(pk=self.pk).values("moneda", "caja_id").first()
            if anterior and self.movimientos.exists():
                if anterior["moneda"] != self.moneda:
                    raise ValidationError({"moneda": "La cuenta ya tiene movimientos: no se puede cambiar su moneda."})
                if anterior["caja_id"] != self.caja_id:
                    raise ValidationError({"caja": "La cuenta ya tiene movimientos: no se puede mover de caja."})

    def save(self, *args, **kwargs):
        if self.caja_id and self.caja.organizacion_id != self.organizacion_id:
            raise ValidationError("La caja es de otra organización.")
        super().save(*args, **kwargs)


class Concepto(ModeloDeOrganizacion):
    class Tipo(models.TextChoices):
        INGRESO = "ingreso", "Ingreso"
        EGRESO = "egreso", "Egreso"

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    nombre = models.CharField(max_length=80)
    padre = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="hijos",
        verbose_name="agrupado en",
        help_text="Opcional. Ej: «Luz» y «Agua» agrupados en «Servicios». Solo dos niveles.",
    )
    caja = models.ForeignKey(
        Caja, null=True, blank=True, on_delete=models.PROTECT, related_name="conceptos",
        help_text="Vacío = sirve para cualquier caja.",
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "concepto"
        verbose_name_plural = "conceptos"
        ordering = ["tipo", "padre__nombre", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "tipo", "nombre"], name="concepto_unico_por_organizacion_y_tipo",
            ),
        ]

    def __str__(self):
        return f"{self.padre.nombre} › {self.nombre}" if self.padre_id else self.nombre

    def clean(self):
        if self.padre_id:
            if self.padre_id == self.pk:
                raise ValidationError({"padre": "Un concepto no puede agruparse en sí mismo."})
            if self.padre.organizacion_id != self.organizacion_id:
                raise ValidationError({"padre": "Ese concepto es de otra organización."})
            if self.padre.tipo != self.tipo:
                raise ValidationError({"padre": "El grupo debe ser del mismo tipo (ingreso o egreso)."})
            if self.padre.padre_id:
                raise ValidationError({"padre": "Solo hay dos niveles: elige un concepto que no esté agrupado."})
            if self.pk and self.hijos.exists():
                raise ValidationError({"padre": "Este concepto ya agrupa a otros: no puede agruparse a su vez."})
        if self.caja_id and self.caja.organizacion_id != self.organizacion_id:
            raise ValidationError({"caja": "Esa caja es de otra organización."})

    def save(self, *args, **kwargs):
        if self.padre_id and self.padre.organizacion_id != self.organizacion_id:
            raise ValidationError("El grupo es de otra organización.")
        if self.caja_id and self.caja.organizacion_id != self.organizacion_id:
            raise ValidationError("La caja es de otra organización.")
        super().save(*args, **kwargs)


class Movimiento(MontoBimonedaMixin, ModeloDeOrganizacion):
    """Un ingreso o un egreso del libro.

    La moneda del movimiento es SIEMPRE la de su cuenta: así el saldo de la
    cuenta es una suma exacta, sin conversiones. `monto_ves` y `monto_usd`
    guardan el equivalente con la tasa del día, congelado (D-09), y sirven
    para los reportes y para comparar contra el presupuesto.

    `estado` solo cambia con `transicionar()`. Lo confirmado no se edita: si
    estaba mal, se anula con motivo y se registra de nuevo.
    """

    class Tipo(models.TextChoices):
        INGRESO = "ingreso", "Ingreso"
        EGRESO = "egreso", "Egreso"

    class Estado(models.TextChoices):
        REGISTRADO = "registrado", "Por aprobar"
        CONFIRMADO = "confirmado", "Confirmado"
        ANULADO = "anulado", "Anulado"

    _TRANSICIONES = {
        Estado.REGISTRADO: {Estado.CONFIRMADO, Estado.ANULADO},
        Estado.CONFIRMADO: {Estado.ANULADO},
        Estado.ANULADO: set(),
    }

    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    fecha = models.DateField()
    numero_vale = models.PositiveIntegerField("vale n.º", editable=False)
    caja = models.ForeignKey(Caja, on_delete=models.PROTECT, related_name="movimientos")
    cuenta = models.ForeignKey(Cuenta, on_delete=models.PROTECT, related_name="movimientos")
    ejercicio = models.ForeignKey("organizaciones.Ejercicio", on_delete=models.PROTECT, related_name="movimientos")
    # Vacío = ingreso o egreso libre; entonces `descripcion` es obligatoria.
    concepto = models.ForeignKey(
        Concepto, null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos",
    )
    descripcion = models.CharField("descripción", max_length=200, blank=True)
    # Quién aportó o a quién se le entregó (columna «Nombre» del libro).
    miembro = models.ForeignKey(
        "organizaciones.Membresia", null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos",
    )
    tercero = models.CharField(max_length=120, blank=True, help_text="Proveedor, donante u otra persona externa.")
    referencia = models.CharField(max_length=60, blank=True, help_text="N.º de transferencia, pago móvil o factura.")
    tasa = models.ForeignKey("cambio.TasaCambio", on_delete=models.PROTECT, related_name="movimientos")
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.CONFIRMADO)
    uuid_cliente = models.UUIDField(null=True, blank=True, editable=False)  # idempotencia (doble envío, cola offline)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimientos_registrados",
    )
    aprobado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos_aprobados",
    )
    anulado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos_anulados",
    )
    motivo_anulacion = models.TextField("motivo de la anulación", blank=True)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimiento"
        verbose_name_plural = "movimientos"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "uuid_cliente"], condition=Q(uuid_cliente__isnull=False),
                name="movimiento_uuid_cliente_unico",
            ),
            models.UniqueConstraint(fields=["caja", "ejercicio", "numero_vale"], name="vale_unico_por_caja_y_ejercicio"),
            models.CheckConstraint(condition=Q(monto__gt=0), name="movimiento_monto_positivo"),
            models.CheckConstraint(
                condition=Q(concepto__isnull=False) | ~Q(descripcion=""), name="movimiento_concepto_o_descripcion",
            ),
        ]
        indexes = [
            models.Index(fields=["organizacion", "fecha"]),
            models.Index(fields=["cuenta", "estado"]),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} #{self.numero_vale} — {self.titulo}"

    @property
    def titulo(self):
        return str(self.concepto) if self.concepto_id else self.descripcion

    @property
    def nombre_persona(self):
        if self.miembro_id:
            return self.miembro.nombre
        return self.tercero

    @property
    def es_ingreso(self):
        return self.tipo == self.Tipo.INGRESO

    def clean(self):
        errores = {}
        org = self.organizacion_id
        if self.cuenta_id:
            if self.cuenta.organizacion_id != org:
                errores["cuenta"] = "Esa cuenta es de otra organización."
            elif self.concepto_id and self.concepto.caja_id and self.concepto.caja_id != self.cuenta.caja_id:
                errores["concepto"] = "Ese concepto pertenece a otra caja."
        if self.concepto_id:
            if self.concepto.organizacion_id != org:
                errores["concepto"] = "Ese concepto es de otra organización."
            elif self.concepto.tipo != self.tipo:
                errores["concepto"] = "Ese concepto no corresponde a este tipo de movimiento."
        elif not (self.descripcion or "").strip():
            errores["descripcion"] = "Sin concepto, la descripción es obligatoria."
        if self.miembro_id and self.miembro.organizacion_id != org:
            errores["miembro"] = "Ese miembro es de otra organización."
        if self.monto is not None and self.monto <= 0:
            errores["monto"] = "El monto debe ser mayor que cero."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        # Segunda barrera: nada cruza de organización aunque no venga de un formulario.
        if self.pk is None:
            self.caja = self.cuenta.caja
            self.moneda = self.cuenta.moneda
        for relacionado in (self.cuenta, self.caja, self.ejercicio, self.concepto, self.miembro):
            if relacionado is not None and relacionado.organizacion_id != self.organizacion_id:
                raise ValidationError("El movimiento mezcla datos de dos organizaciones.")
        if self.pk is None:
            self.calcular_montos()
        elif self.estado == self.Estado.REGISTRADO:
            # Aún no está congelado: si corrigen la tasa, se recalcula (D-02).
            self.calcular_montos()
        super().save(*args, **kwargs)

    def transicionar(self, nuevo_estado, usuario, motivo=None):
        """Único método que cambia `estado`."""
        if nuevo_estado not in self._TRANSICIONES.get(self.estado, set()):
            raise ValidationError(
                f"No se puede pasar de «{self.get_estado_display()}» a «{self.Estado(nuevo_estado).label}»."
            )
        campos = ["estado"]
        if nuevo_estado == self.Estado.ANULADO:
            if not (motivo or "").strip():
                raise ValidationError({"motivo": "Indica el motivo de la anulación."})
            self.motivo_anulacion = motivo.strip()
            self.anulado_por = usuario
            self.fecha_anulacion = timezone.now()
            campos += ["motivo_anulacion", "anulado_por", "fecha_anulacion"]
        elif nuevo_estado == self.Estado.CONFIRMADO:
            self.aprobado_por = usuario
            campos.append("aprobado_por")
        self.estado = nuevo_estado
        # update_fields a propósito: no pasa por calcular_montos().
        models.Model.save(self, update_fields=campos)


class Traslado(ModeloDeOrganizacion):
    """Dinero que pasa de una cuenta a otra de la misma organización: del
    banco al efectivo, de una caja a otra, o un cambio de divisas.

    No es un ingreso ni un egreso: mueve los saldos de las dos cuentas y no
    aparece en los totales del mes ni contará contra el presupuesto.

    Guarda dos montos, cada uno en la moneda de su cuenta. Entre cuentas de
    la misma moneda son iguales; entre monedas distintas, `monto_destino` es
    lo que de verdad se recibió (que puede no coincidir con la tasa oficial).
    """

    class Estado(models.TextChoices):
        CONFIRMADO = "confirmado", "Confirmado"
        ANULADO = "anulado", "Anulado"

    fecha = models.DateField()
    cuenta_origen = models.ForeignKey(Cuenta, on_delete=models.PROTECT, related_name="traslados_salientes")
    cuenta_destino = models.ForeignKey(Cuenta, on_delete=models.PROTECT, related_name="traslados_entrantes")
    monto_origen = models.DecimalField(max_digits=18, decimal_places=4)
    monto_destino = models.DecimalField(max_digits=18, decimal_places=4)
    ejercicio = models.ForeignKey("organizaciones.Ejercicio", on_delete=models.PROTECT, related_name="traslados")
    descripcion = models.CharField("descripción", max_length=200, blank=True)
    referencia = models.CharField(max_length=60, blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.CONFIRMADO)
    uuid_cliente = models.UUIDField(null=True, blank=True, editable=False)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="traslados_registrados",
    )
    anulado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="traslados_anulados",
    )
    motivo_anulacion = models.TextField("motivo de la anulación", blank=True)
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "traslado"
        verbose_name_plural = "traslados"
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organizacion", "uuid_cliente"], condition=Q(uuid_cliente__isnull=False),
                name="traslado_uuid_cliente_unico",
            ),
            models.CheckConstraint(
                condition=Q(monto_origen__gt=0) & Q(monto_destino__gt=0), name="traslado_montos_positivos",
            ),
            models.CheckConstraint(
                condition=~Q(cuenta_origen=models.F("cuenta_destino")), name="traslado_cuentas_distintas",
            ),
        ]
        indexes = [models.Index(fields=["organizacion", "fecha"])]

    def __str__(self):
        return f"Traslado {self.cuenta_origen.nombre} → {self.cuenta_destino.nombre}"

    @property
    def es_cambio_de_moneda(self):
        return self.cuenta_origen.moneda != self.cuenta_destino.moneda

    @property
    def tasa_implicita(self):
        """Bs. por USD que resultó del cambio, o None si no hubo cambio de moneda."""
        if not self.es_cambio_de_moneda:
            return None
        ves, usd = (
            (self.monto_origen, self.monto_destino) if self.cuenta_origen.moneda == "VES"
            else (self.monto_destino, self.monto_origen)
        )
        return ves / usd if usd else None

    def clean(self):
        errores = {}
        org = self.organizacion_id
        if self.cuenta_origen_id and self.cuenta_origen.organizacion_id != org:
            errores["cuenta_origen"] = "Esa cuenta es de otra organización."
        if self.cuenta_destino_id and self.cuenta_destino.organizacion_id != org:
            errores["cuenta_destino"] = "Esa cuenta es de otra organización."
        if self.cuenta_origen_id and self.cuenta_origen_id == self.cuenta_destino_id:
            errores["cuenta_destino"] = "Elige una cuenta distinta a la de origen."
        if self.monto_origen is not None and self.monto_origen <= 0:
            errores["monto_origen"] = "El monto debe ser mayor que cero."
        if self.monto_destino is not None and self.monto_destino <= 0:
            errores["monto_destino"] = "El monto debe ser mayor que cero."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        for cuenta in (self.cuenta_origen, self.cuenta_destino):
            if cuenta.organizacion_id != self.organizacion_id:
                raise ValidationError("El traslado mezcla cuentas de dos organizaciones.")
        if self.ejercicio.organizacion_id != self.organizacion_id:
            raise ValidationError("El ejercicio es de otra organización.")
        super().save(*args, **kwargs)

    def anular(self, usuario, motivo):
        if self.estado == self.Estado.ANULADO:
            raise ValidationError("Este traslado ya está anulado.")
        if not (motivo or "").strip():
            raise ValidationError({"motivo": "Indica el motivo de la anulación."})
        self.estado = self.Estado.ANULADO
        self.motivo_anulacion = motivo.strip()
        self.anulado_por = usuario
        self.fecha_anulacion = timezone.now()
        self.save(update_fields=["estado", "motivo_anulacion", "anulado_por", "fecha_anulacion"])


class CuotaMiembro(ModeloDeOrganizacion):
    """Aporte fijo mensual que se espera de un miembro (las «pensiones» del Excel).

    No genera movimientos: solo dice cuánto se espera. Lo pagado sale de los
    ingresos confirmados de ese miembro en ese concepto (finanzas/services.py).
    Sirve igual para miembros con o sin acceso al sistema."""

    class Moneda(models.TextChoices):
        USD = "USD", "Dólares"
        VES = "VES", "Bolívares"

    membresia = models.ForeignKey(
        "organizaciones.Membresia", on_delete=models.PROTECT, related_name="cuotas", verbose_name="miembro",
    )
    concepto = models.ForeignKey(
        Concepto, on_delete=models.PROTECT, related_name="cuotas",
        help_text="El concepto de ingreso con el que se registran sus pagos.",
    )
    monto = models.DecimalField("monto mensual", max_digits=18, decimal_places=4)
    moneda = models.CharField(max_length=3, choices=Moneda.choices, default=Moneda.USD)
    vigente_desde = models.DateField(help_text="Se cuenta desde el mes de esta fecha.")
    vigente_hasta = models.DateField(null=True, blank=True, help_text="Vacío = sigue vigente.")
    nota = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "cuota de miembro"
        verbose_name_plural = "cuotas de miembros"
        ordering = ["membresia__nombre_visible", "concepto__nombre"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="cuota_monto_positivo"),
            models.UniqueConstraint(fields=["membresia", "concepto", "vigente_desde"], name="cuota_unica_por_inicio"),
        ]

    def __str__(self):
        return f"{self.membresia.nombre}: {self.concepto.nombre} {self.moneda} {self.monto}"

    def clean(self):
        errores = {}
        if self.membresia_id and self.membresia.organizacion_id != self.organizacion_id:
            errores["membresia"] = "Ese miembro es de otra organización."
        if self.concepto_id:
            if self.concepto.organizacion_id != self.organizacion_id:
                errores["concepto"] = "Ese concepto es de otra organización."
            elif self.concepto.tipo != Concepto.Tipo.INGRESO:
                errores["concepto"] = "La cuota se cobra con un concepto de ingreso."
        if self.vigente_desde and self.vigente_hasta and self.vigente_hasta < self.vigente_desde:
            errores["vigente_hasta"] = "No puede terminar antes de empezar."
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        if self.membresia.organizacion_id != self.organizacion_id or self.concepto.organizacion_id != self.organizacion_id:
            raise ValidationError("La cuota mezcla datos de dos organizaciones.")
        super().save(*args, **kwargs)


class Arqueo(ModeloDeOrganizacion):
    """Conteo físico de una cuenta contra lo que dice el sistema.

    Guarda las dos cifras tal como estaban ese día (el saldo del sistema se
    congela aquí: si después se registra o anula algo, el arqueo no cambia).
    La diferencia se puede llevar al libro con un movimiento de ajuste."""

    cuenta = models.ForeignKey(Cuenta, on_delete=models.PROTECT, related_name="arqueos")
    fecha = models.DateField(default=timezone.localdate)
    saldo_sistema = models.DecimalField("saldo según el sistema", max_digits=18, decimal_places=4)
    contado = models.DecimalField("contado", max_digits=18, decimal_places=4)
    nota = models.CharField(max_length=200, blank=True)
    realizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="arqueos")
    ajuste = models.OneToOneField(
        "Movimiento", null=True, blank=True, on_delete=models.PROTECT, related_name="arqueo_ajustado",
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "arqueo"
        verbose_name_plural = "arqueos"
        ordering = ["-fecha", "-pk"]

    def __str__(self):
        return f"Arqueo de {self.cuenta} del {self.fecha:%d/%m/%Y}"

    @property
    def diferencia(self):
        """Positiva: sobra dinero. Negativa: falta."""
        return self.contado - self.saldo_sistema

    @property
    def cuadra(self):
        return self.diferencia == 0

    def save(self, *args, **kwargs):
        if self.cuenta.organizacion_id != self.organizacion_id:
            raise ValidationError("La cuenta es de otra organización.")
        super().save(*args, **kwargs)


class Anticipo(ModeloDeOrganizacion):
    """Dinero entregado a alguien para que gaste y luego rinda cuentas.

    Al entregarlo sale de la cuenta con un egreso provisional («anticipo por
    rendir»). Al rendir, ese egreso se anula y en su lugar quedan los gastos
    reales, cada uno con su concepto: lo que sobró vuelve a la cuenta porque
    los gastos suman menos que lo entregado (decisión A-43)."""

    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Por rendir"
        RENDIDO = "rendido", "Rendido"
        ANULADO = "anulado", "Anulado"

    cuenta = models.ForeignKey(Cuenta, on_delete=models.PROTECT, related_name="anticipos")
    fecha = models.DateField(default=timezone.localdate)
    monto = models.DecimalField(max_digits=18, decimal_places=4)
    miembro = models.ForeignKey(
        "organizaciones.Membresia", null=True, blank=True, on_delete=models.PROTECT, related_name="anticipos",
    )
    tercero = models.CharField("otra persona", max_length=120, blank=True)
    motivo = models.CharField("para qué", max_length=200)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    entrega = models.OneToOneField("Movimiento", on_delete=models.PROTECT, related_name="anticipo_entregado")
    gastos = models.ManyToManyField("Movimiento", blank=True, related_name="anticipos_rendidos")
    fecha_rendicion = models.DateField("fecha de rendición", null=True, blank=True)
    gastado = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    entregado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="anticipos_entregados")
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "anticipo"
        verbose_name_plural = "anticipos"
        ordering = ["-fecha", "-pk"]
        constraints = [
            models.CheckConstraint(condition=Q(monto__gt=0), name="anticipo_monto_positivo"),
            models.CheckConstraint(condition=Q(miembro__isnull=False) | ~Q(tercero=""), name="anticipo_con_responsable"),
        ]

    def __str__(self):
        return f"Anticipo a {self.responsable}: {self.motivo}"

    @property
    def responsable(self):
        return self.miembro.nombre if self.miembro_id else self.tercero

    @property
    def moneda(self):
        return self.cuenta.moneda

    @property
    def devuelto(self):
        """Lo que volvió a la cuenta (positivo) o lo que hubo que reponerle (negativo)."""
        return None if self.gastado is None else self.monto - self.gastado

    def save(self, *args, **kwargs):
        if self.cuenta.organizacion_id != self.organizacion_id or (
                self.miembro_id and self.miembro.organizacion_id != self.organizacion_id):
            raise ValidationError("El anticipo mezcla datos de dos organizaciones.")
        super().save(*args, **kwargs)
