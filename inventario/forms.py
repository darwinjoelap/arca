from decimal import Decimal

from django import forms
from django.utils import timezone

from organizaciones.models import Membresia

from .models import Articulo, CategoriaArticulo, MovimientoInventario, Ubicacion


class _Estilo:
    def _aplicar_estilo(self):
        for field in self.fields.values():
            w = field.widget
            if isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, forms.Select):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")


class _UnicoPorNombre(_Estilo, forms.ModelForm):
    """Catálogos simples: nombre único dentro de la organización."""

    def __init__(self, *args, organizacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        if organizacion is not None and not self.instance.pk:
            self.instance.organizacion = organizacion
        self._aplicar_estilo()

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        repetido = type(self.instance).objects.filter(organizacion_id=self.instance.organizacion_id, nombre__iexact=nombre)
        if self.instance.pk:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Ya existe uno con ese nombre.")
        return nombre


class UbicacionForm(_UnicoPorNombre):
    class Meta:
        model = Ubicacion
        fields = ["nombre", "descripcion", "activa"]


class CategoriaForm(_UnicoPorNombre):
    class Meta:
        model = CategoriaArticulo
        fields = ["nombre"]


class ArticuloForm(_UnicoPorNombre):
    cantidad_inicial = forms.DecimalField(
        label="Cantidad que hay ahora", required=False, min_value=Decimal("0.01"), max_digits=12, decimal_places=2,
        help_text="Opcional. Se anota como existencia inicial en la ubicación que elijas.",
    )
    ubicacion_inicial = forms.ModelChoiceField(
        label="¿Dónde está?", queryset=Ubicacion.objects.none(), required=False, empty_label="— Elige una ubicación —",
    )

    class Meta:
        model = Articulo
        fields = ["clase", "nombre", "codigo", "categoria", "unidad", "minimo", "estado", "responsable",
                  "valor_unitario", "moneda", "nota", "activo"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        org = self.organizacion
        self.fields["categoria"].queryset = CategoriaArticulo.objects.filter(organizacion=org)
        self.fields["categoria"].empty_label = "— Sin categoría —"
        self.fields["responsable"].queryset = Membresia.objects.filter(organizacion=org, activa=True).select_related("user")
        self.fields["responsable"].label_from_instance = lambda m: m.nombre
        self.fields["responsable"].empty_label = "— Nadie en particular —"
        self.fields["ubicacion_inicial"].queryset = Ubicacion.objects.filter(organizacion=org, activa=True)
        for campo in ("minimo", "valor_unitario", "cantidad_inicial"):
            self.fields[campo].widget.attrs.update({"step": "0.01", "min": "0", "inputmode": "decimal"})
        if self.instance.pk:
            # La existencia de un artículo que ya existe se cambia con movimientos, no aquí.
            del self.fields["cantidad_inicial"], self.fields["ubicacion_inicial"]
        else:
            del self.fields["activo"]
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        if datos.get("cantidad_inicial") and not datos.get("ubicacion_inicial"):
            self.add_error("ubicacion_inicial", "Indica dónde está esa cantidad.")
        if datos.get("clase") != Articulo.Clase.CONSUMIBLE:
            datos["minimo"] = None
        return datos


class MovimientoInventarioForm(_Estilo, forms.ModelForm):
    class Meta:
        model = MovimientoInventario
        fields = ["articulo", "fecha", "cantidad", "origen", "destino", "motivo", "nota"]
        widgets = {"fecha": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, organizacion, tipo, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.organizacion, self.instance.tipo = organizacion, tipo
        self.tipo = tipo
        self.fields["fecha"].initial = timezone.localdate()
        self.fields["articulo"].queryset = Articulo.objects.filter(organizacion=organizacion, activo=True)
        self.fields["articulo"].empty_label = "— Elige un artículo —"
        ubicaciones = Ubicacion.objects.filter(organizacion=organizacion, activa=True)
        for campo in ("origen", "destino"):
            self.fields[campo].queryset = ubicaciones
            self.fields[campo].empty_label = "— Elige una ubicación —"
            self.fields[campo].required = True
        if tipo == "entrada":
            del self.fields["origen"]
        elif tipo == "salida":
            del self.fields["destino"]
        permitidos = MovimientoInventario.MOTIVOS_POR_TIPO[tipo]
        self.fields["motivo"].choices = [(v, e) for v, e in MovimientoInventario.Motivo.choices if v in permitidos]
        if len(permitidos) == 1:
            self.fields["motivo"].initial = permitidos[0]
            self.fields["motivo"].widget = forms.HiddenInput()
        self.fields["cantidad"].widget.attrs.update({"step": "0.01", "min": "0.01", "inputmode": "decimal"})
        self.fields["nota"].help_text = "Opcional: proveedor, a quién se entregó, por qué se dio de baja…"
        self._aplicar_estilo()
        if ubicaciones.count() == 1 and tipo != "traslado":
            campo = "destino" if tipo == "entrada" else "origen"
            self.fields[campo].initial = ubicaciones.first().pk


class AnularInventarioForm(_Estilo, forms.Form):
    motivo = forms.CharField(label="Motivo de la anulación", max_length=200, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilo()
