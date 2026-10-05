from django import forms
from django.utils import timezone

from finanzas.models import Concepto, Cuenta
from organizaciones.forms import _EstiloBootstrapMixin
from organizaciones.models import Membresia

from .models import ConceptoPersonal, MovimientoPersonal
from .services import conceptos_disponibles


class MovimientoPersonalForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = MovimientoPersonal
        fields = ["fecha", "monto", "moneda", "concepto", "descripcion"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, membresia, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.organizacion = membresia.organizacion
        self.instance.membresia = membresia
        self.instance.tipo = tipo
        if not self.instance.pk:
            self.fields["fecha"].initial = timezone.localdate()
            self.fields["moneda"].initial = membresia.organizacion.moneda_base
        self.fields["concepto"].queryset = conceptos_disponibles(membresia, tipo)
        self.fields["concepto"].empty_label = "— Otro (escríbelo en la descripción) —"
        self.fields["descripcion"].help_text = "Obligatoria si no eliges un concepto."
        self.fields["monto"].widget.attrs.update({"step": "0.01", "min": "0.01", "inputmode": "decimal"})
        self._aplicar_estilo()


class ConceptoPersonalForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = ConceptoPersonal
        fields = ["tipo", "nombre"]

    def __init__(self, *args, membresia, **kwargs):
        super().__init__(*args, **kwargs)
        self.membresia = membresia
        self.instance.organizacion = membresia.organizacion
        self.instance.membresia = membresia
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        tipo, nombre = datos.get("tipo"), (datos.get("nombre") or "").strip()
        if tipo and nombre and conceptos_disponibles(self.membresia, tipo).filter(nombre__iexact=nombre).exists():
            self.add_error("nombre", "Ya tienes un concepto con ese nombre.")
        return datos


class AsignacionForm(_EstiloBootstrapMixin, forms.Form):
    destino = forms.ModelChoiceField(label="Miembro", queryset=Membresia.objects.none(), empty_label="— Elige un miembro —")
    cuenta = forms.ModelChoiceField(label="Sale de la cuenta", queryset=Cuenta.objects.none(), empty_label="— Elige una cuenta —")
    monto = forms.DecimalField(max_digits=18, decimal_places=4, min_value=0, help_text="En la moneda de la cuenta elegida.")
    fecha = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    concepto = forms.ModelChoiceField(
        label="Concepto de egreso", queryset=Concepto.objects.none(), required=False, empty_label="— Sin concepto —",
        help_text="Cómo queda en el libro de la organización.",
    )
    nota = forms.CharField(max_length=200, required=False, help_text="La ve el miembro en su cuenta.")

    def __init__(self, *args, organizacion, **kwargs):
        super().__init__(*args, **kwargs)
        con_cuenta = [
            m.pk for m in Membresia.objects.filter(organizacion=organizacion, activa=True, user__isnull=False).select_related("tipo")
            if m.tiene_permiso("tiene_cuenta_personal")
        ]
        self.fields["destino"].queryset = Membresia.objects.filter(pk__in=con_cuenta).select_related("user")
        self.fields["destino"].label_from_instance = lambda m: m.nombre
        self.fields["cuenta"].queryset = Cuenta.objects.filter(organizacion=organizacion, activa=True, caja__activa=True).select_related("caja")
        self.fields["cuenta"].label_from_instance = lambda c: f"{c.caja.nombre} · {c.nombre} ({c.moneda})"
        self.fields["concepto"].queryset = Concepto.objects.filter(organizacion=organizacion, tipo="egreso", activo=True)
        self.fields["fecha"].initial = timezone.localdate()
        self.fields["monto"].widget.attrs.update({"step": "0.01", "min": "0.01", "inputmode": "decimal"})
        self._aplicar_estilo()

    def clean_monto(self):
        monto = self.cleaned_data["monto"]
        if monto <= 0:
            raise forms.ValidationError("El monto debe ser mayor que cero.")
        return monto

    def clean(self):
        datos = super().clean()
        cuenta, concepto = datos.get("cuenta"), datos.get("concepto")
        if cuenta and concepto and concepto.caja_id and concepto.caja_id != cuenta.caja_id:
            self.add_error("concepto", "Ese concepto pertenece a otra caja.")
        return datos
