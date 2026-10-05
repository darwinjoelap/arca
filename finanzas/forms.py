import uuid
from decimal import Decimal

from django import forms
from django.db.models import Q
from django.utils import timezone

from organizaciones.forms import _EstiloBootstrapMixin
from organizaciones.models import Membresia

from .models import Caja, Concepto, Cuenta, Movimiento, Traslado


class CajaForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = Caja
        fields = ["nombre", "descripcion", "activa"]

    def __init__(self, *args, organizacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        self._aplicar_estilo()

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        repetida = Caja.objects.filter(organizacion=self.organizacion, nombre__iexact=nombre)
        if self.instance.pk:
            repetida = repetida.exclude(pk=self.instance.pk)
        if repetida.exists():
            raise forms.ValidationError("Ya existe una caja con ese nombre.")
        return nombre


class CuentaForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = Cuenta
        fields = ["caja", "nombre", "tipo", "moneda", "banco", "saldo_inicial", "activa"]

    def __init__(self, *args, organizacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        if not self.instance.pk:
            self.instance.organizacion = organizacion
        self.fields["caja"].queryset = Caja.objects.filter(organizacion=organizacion)
        self.fields["saldo_inicial"].widget.attrs.update({"step": "0.01", "inputmode": "decimal"})
        if self.instance.pk and self.instance.movimientos.exists():
            # Con movimientos, la moneda y la caja quedan fijas.
            self.fields["moneda"].disabled = True
            self.fields["caja"].disabled = True
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        caja, nombre = datos.get("caja"), (datos.get("nombre") or "").strip()
        if caja and nombre:
            repetida = Cuenta.objects.filter(caja=caja, nombre__iexact=nombre)
            if self.instance.pk:
                repetida = repetida.exclude(pk=self.instance.pk)
            if repetida.exists():
                self.add_error("nombre", "Esa caja ya tiene una cuenta con ese nombre.")
        return datos


class ConceptoForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = Concepto
        fields = ["tipo", "nombre", "padre", "caja", "activo"]

    def __init__(self, *args, organizacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        if not self.instance.pk:
            self.instance.organizacion = organizacion
        grupos = Concepto.objects.filter(organizacion=organizacion, padre__isnull=True)
        if self.instance.pk:
            grupos = grupos.exclude(pk=self.instance.pk)
            if self.instance.movimientos.exists() or self.instance.hijos.exists():
                self.fields["tipo"].disabled = True  # cambiarlo descuadraría lo ya registrado
        self.fields["padre"].queryset = grupos
        self.fields["padre"].empty_label = "— Sin agrupar —"
        self.fields["padre"].label_from_instance = lambda c: f"{c.nombre} ({c.get_tipo_display().lower()})"
        self.fields["caja"].queryset = Caja.objects.filter(organizacion=organizacion)
        self.fields["caja"].empty_label = "— Cualquier caja —"
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        tipo, nombre = datos.get("tipo"), (datos.get("nombre") or "").strip()
        if tipo and nombre:
            repetido = Concepto.objects.filter(organizacion=self.organizacion, tipo=tipo, nombre__iexact=nombre)
            if self.instance.pk:
                repetido = repetido.exclude(pk=self.instance.pk)
            if repetido.exists():
                self.add_error("nombre", "Ya existe un concepto de ese tipo con ese nombre.")
        return datos


class MovimientoForm(_EstiloBootstrapMixin, forms.ModelForm):
    """Registro de un ingreso o un egreso. El tipo lo fija la vista, no el
    usuario. Ejercicio, tasa, vale y estado los completa `registrar_movimiento`."""

    uuid_cliente = forms.UUIDField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Movimiento
        fields = ["fecha", "cuenta", "concepto", "descripcion", "monto", "miembro", "tercero", "referencia"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, organizacion, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        self.tipo = tipo
        self.instance.organizacion = organizacion
        self.instance.tipo = tipo

        es_ingreso = tipo == Movimiento.Tipo.INGRESO
        self.fields["fecha"].initial = timezone.localdate()
        self.fields["uuid_cliente"].initial = uuid.uuid4()

        self.fields["cuenta"].queryset = (
            Cuenta.objects.filter(organizacion=organizacion, activa=True, caja__activa=True).select_related("caja")
        )
        self.fields["cuenta"].label = "Entra a la cuenta" if es_ingreso else "Sale de la cuenta"
        self.fields["cuenta"].label_from_instance = lambda c: f"{c.caja.nombre} · {c.nombre} ({c.moneda})"
        self.fields["cuenta"].empty_label = "— Elige una cuenta —"
        if self.fields["cuenta"].queryset.count() == 1:
            # Con una sola cuenta no hay nada que elegir.
            self.fields["cuenta"].initial = self.fields["cuenta"].queryset.first().pk

        self.fields["concepto"].queryset = Concepto.objects.filter(
            organizacion=organizacion, tipo=tipo, activo=True
        ).select_related("padre")
        self.fields["concepto"].empty_label = "— Otro (escríbelo en la descripción) —"
        self.fields["descripcion"].help_text = "Obligatoria si no eliges un concepto."

        self.fields["miembro"].queryset = Membresia.objects.filter(
            organizacion=organizacion, activa=True
        ).select_related("user")
        self.fields["miembro"].label = "Miembro que aporta" if es_ingreso else "Miembro que recibe"
        self.fields["miembro"].label_from_instance = lambda m: m.nombre
        self.fields["miembro"].empty_label = "— Ninguno —"
        self.fields["tercero"].label = "Otra persona o entidad"

        self.fields["monto"].widget.attrs.update({"step": "0.01", "min": "0.01", "inputmode": "decimal"})
        self.fields["monto"].help_text = "En la moneda de la cuenta elegida."
        self._aplicar_estilo()

    def cuentas_para_js(self):
        """{id: moneda} para que el formulario muestre el símbolo correcto."""
        return {str(c.pk): c.moneda for c in self.fields["cuenta"].queryset}


class TrasladoForm(_EstiloBootstrapMixin, forms.ModelForm):
    uuid_cliente = forms.UUIDField(widget=forms.HiddenInput, required=False)
    monto_recibido = forms.DecimalField(
        label="Monto que entra", required=False, min_value=Decimal("0.01"), max_digits=18, decimal_places=4,
        help_text="Solo si las cuentas tienen monedas distintas: lo que de verdad se recibió. "
        "Vacío, se calcula con la tasa del día.",
    )

    field_order = ["fecha", "cuenta_origen", "cuenta_destino", "monto_origen", "monto_recibido", "descripcion", "referencia"]

    class Meta:
        model = Traslado
        # `monto_destino` no va aquí: llega por `monto_recibido`, que puede venir vacío.
        fields = ["fecha", "cuenta_origen", "cuenta_destino", "monto_origen", "descripcion", "referencia"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, organizacion, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.organizacion = organizacion
        self.fields["fecha"].initial = timezone.localdate()
        self.fields["uuid_cliente"].initial = uuid.uuid4()
        cuentas = Cuenta.objects.filter(organizacion=organizacion, activa=True, caja__activa=True).select_related("caja")
        for nombre, etiqueta in (("cuenta_origen", "Sale de"), ("cuenta_destino", "Entra a")):
            self.fields[nombre].queryset = cuentas
            self.fields[nombre].label = etiqueta
            self.fields[nombre].label_from_instance = lambda c: f"{c.caja.nombre} · {c.nombre} ({c.moneda})"
            self.fields[nombre].empty_label = "— Elige una cuenta —"
        self.fields["monto_origen"].label = "Monto que sale"
        for nombre in ("monto_origen", "monto_recibido"):
            self.fields[nombre].widget.attrs.update({"step": "0.01", "min": "0.01", "inputmode": "decimal"})
        self.fields["descripcion"].required = False
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        origen, destino = datos.get("cuenta_origen"), datos.get("cuenta_destino")
        if origen and destino and origen == destino:
            self.add_error("cuenta_destino", "Elige una cuenta distinta a la de origen.")
        return datos

    def cuentas_para_js(self):
        return {str(c.pk): c.moneda for c in self.fields["cuenta_origen"].queryset}


class AnularForm(_EstiloBootstrapMixin, forms.Form):
    motivo = forms.CharField(
        label="Motivo de la anulación", widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Queda guardado en el movimiento y en la bitácora.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilo()


class FiltroMovimientosForm(forms.Form):
    """Filtros de la lista. Todo opcional; lo inválido se ignora."""

    tipo = forms.ChoiceField(choices=[("", "Todos")] + list(Movimiento.Tipo.choices), required=False)
    estado = forms.ChoiceField(choices=[("", "Todos")] + list(Movimiento.Estado.choices), required=False)
    cuenta = forms.ModelChoiceField(queryset=Cuenta.objects.none(), required=False, empty_label="Todas")
    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    q = forms.CharField(required=False)

    def __init__(self, *args, organizacion, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cuenta"].queryset = Cuenta.objects.filter(organizacion=organizacion).select_related("caja")
        self.fields["cuenta"].label_from_instance = lambda c: f"{c.caja.nombre} · {c.nombre}"
        for nombre, field in self.fields.items():
            clase = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs.setdefault("class", clase + " form-select-sm" if "select" in clase else clase + " form-control-sm")
        self.fields["q"].widget.attrs["placeholder"] = "Concepto, descripción, persona…"

    def aplicar(self, qs):
        if not self.is_valid():
            return qs
        d = self.cleaned_data
        if d.get("tipo"):
            qs = qs.filter(tipo=d["tipo"])
        if d.get("estado"):
            qs = qs.filter(estado=d["estado"])
        if d.get("cuenta"):
            qs = qs.filter(cuenta=d["cuenta"])
        if d.get("desde"):
            qs = qs.filter(fecha__gte=d["desde"])
        if d.get("hasta"):
            qs = qs.filter(fecha__lte=d["hasta"])
        if d.get("q"):
            q = d["q"].strip()
            qs = qs.filter(
                Q(descripcion__icontains=q) | Q(concepto__nombre__icontains=q) | Q(tercero__icontains=q)
                | Q(miembro__nombre_visible__icontains=q) | Q(referencia__icontains=q)
            )
        return qs
