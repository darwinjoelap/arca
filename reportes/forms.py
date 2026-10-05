from django import forms
from django.utils import timezone

from finanzas.models import Caja, Cuenta
from organizaciones.models import Ejercicio


class FiltroReporteForm(forms.Form):
    """Filtros comunes: período, caja y moneda de presentación. Todo tiene
    un valor por defecto, así que un reporte siempre se puede abrir sin nada."""

    desde = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hasta = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    caja = forms.ModelChoiceField(queryset=Caja.objects.none(), required=False, empty_label="Todas las cajas")
    moneda = forms.ChoiceField(choices=[("USD", "Dólares ($)"), ("VES", "Bolívares (Bs.)")], required=False)
    cuenta = forms.ModelChoiceField(queryset=Cuenta.objects.none(), required=False, empty_label=None)
    ejercicio = forms.ModelChoiceField(queryset=Ejercicio.objects.none(), required=False, empty_label=None)

    def __init__(self, datos, *, organizacion):
        super().__init__(datos or None)
        self.organizacion = organizacion
        self.fields["caja"].queryset = Caja.objects.filter(organizacion=organizacion)
        self.fields["cuenta"].queryset = Cuenta.objects.filter(organizacion=organizacion).select_related("caja")
        self.fields["cuenta"].label_from_instance = lambda c: f"{c.caja.nombre} · {c.nombre} ({c.moneda})"
        self.fields["ejercicio"].queryset = Ejercicio.objects.filter(organizacion=organizacion)
        for field in self.fields.values():
            clase = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
            field.widget.attrs["class"] = f"{clase} {clase}-sm"

    def valores(self):
        """Los filtros ya resueltos, con sus valores por defecto."""
        datos = self.cleaned_data if self.is_bound and self.is_valid() else {}
        hoy = timezone.localdate()
        ejercicios = self.fields["ejercicio"].queryset
        ejercicio = datos.get("ejercicio") or ejercicios.filter(activo=True).first() or ejercicios.filter(
            fecha_inicio__lte=hoy, fecha_fin__gte=hoy).first() or ejercicios.first()
        desde = datos.get("desde") or hoy.replace(day=1)
        hasta = datos.get("hasta") or hoy
        if hasta < desde:
            desde, hasta = hasta, desde
        return {
            "desde": desde, "hasta": hasta, "caja": datos.get("caja"),
            "moneda": datos.get("moneda") or self.organizacion.moneda_base,
            "cuenta": datos.get("cuenta") or self.fields["cuenta"].queryset.first(),
            "ejercicio": ejercicio,
        }
