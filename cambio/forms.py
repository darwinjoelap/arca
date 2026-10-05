from django import forms
from django.utils import timezone

from .models import TasaCambio


class TasaCambioForm(forms.ModelForm):
    """Carga o corrección de la tasa del día. Si `valor` cambia en una tasa
    en uso, `TasaCambio.save()` recalcula las transacciones no congeladas."""

    class Meta:
        model = TasaCambio
        fields = ["fecha", "valor", "fuente"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk and not self.initial.get("fecha"):
            self.fields["fecha"].initial = timezone.localdate()
        if self.instance.pk:
            # Al editar solo se corrige el valor: fecha y fuente identifican
            # la fila (única por día+fuente) y no tiene sentido cambiarlas
            # aquí; para eso se carga una tasa nueva.
            self.fields["fecha"].disabled = True
            self.fields["fuente"].disabled = True
        for field in self.fields.values():
            css = "form-select" if field == self.fields["fuente"] else "form-control"
            field.widget.attrs.setdefault("class", css)
