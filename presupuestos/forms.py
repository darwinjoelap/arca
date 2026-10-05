from django import forms

from finanzas.models import Caja
from organizaciones.forms import _EstiloBootstrapMixin
from organizaciones.models import Ejercicio

from .models import Presupuesto


class PresupuestoForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = Presupuesto
        fields = ["caja", "ejercicio", "moneda", "nota"]
        widgets = {"nota": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, organizacion, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        self.instance.organizacion = organizacion
        self.fields["caja"].queryset = Caja.objects.filter(organizacion=organizacion, activa=True)
        self.fields["ejercicio"].queryset = Ejercicio.objects.filter(organizacion=organizacion, cerrado=False)
        activo = self.fields["ejercicio"].queryset.filter(activo=True).first()
        if activo:
            self.fields["ejercicio"].initial = activo.pk
        self.fields["moneda"].initial = organizacion.moneda_base
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        caja, ejercicio = datos.get("caja"), datos.get("ejercicio")
        if caja and ejercicio and Presupuesto.objects.filter(caja=caja, ejercicio=ejercicio).exists():
            raise forms.ValidationError("Esa caja ya tiene un presupuesto para ese ejercicio.")
        return datos
