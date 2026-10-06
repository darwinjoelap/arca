from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from .models import NOMBRES_PERMISOS, Ejercicio, Membresia, Organizacion, TipoMiembro
from .services import asignar_clave_temporal, validar_enlace, validar_limite_usuarios

Usuario = get_user_model()


class _EstiloBootstrapMixin:
    """Pone las clases de Bootstrap según el tipo de widget."""

    def _aplicar_estilo(self):
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class OrganizacionForm(_EstiloBootstrapMixin, forms.ModelForm):
    """Datos que el director puede cambiar. `director_ve_cuentas_personales`
    y `activa` NO están aquí a propósito: son del superadmin (/admin/)."""

    class Meta:
        model = Organizacion
        fields = ["nombre", "rif", "direccion", "telefono", "email", "moneda_base", "requiere_aprobacion_egresos"]
        widgets = {"direccion": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aplicar_estilo()


class TipoMiembroForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = TipoMiembro
        fields = ["nombre", *NOMBRES_PERMISOS, "activo"]

    def __init__(self, *args, organizacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        self._aplicar_estilo()

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        repetido = TipoMiembro.objects.filter(organizacion=self.organizacion, nombre__iexact=nombre)
        if self.instance.pk:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Ya existe un tipo de miembro con ese nombre.")
        return nombre


class EjercicioForm(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = Ejercicio
        fields = ["nombre", "fecha_inicio", "fecha_fin"]
        widgets = {
            "fecha_inicio": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "fecha_fin": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, organizacion=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Se asigna antes de validar para que Ejercicio.clean() revise los
        # traslapes y la unicidad dentro de la organización correcta.
        if organizacion is not None and not self.instance.pk:
            self.instance.organizacion = organizacion
        self._aplicar_estilo()

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        repetido = Ejercicio.objects.filter(organizacion_id=self.instance.organizacion_id, nombre__iexact=nombre)
        if self.instance.pk:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Ya existe un ejercicio con ese nombre.")
        return nombre


class _MiembroBase(_EstiloBootstrapMixin, forms.Form):
    nombre_visible = forms.CharField(
        label="Nombre", max_length=120,
        help_text="Cómo aparece esta persona dentro de la organización.",
    )
    tipo = forms.ModelChoiceField(
        label="Tipo de miembro", queryset=TipoMiembro.objects.none(), required=False,
        empty_label="— Sin tipo (solo administradores) —",
    )
    es_administrador = forms.BooleanField(
        label="Es administrador", required=False,
        help_text="Tiene los mismos permisos que el director, salvo modificar al director "
        "o nombrar a otros administradores.",
    )

    def __init__(self, *args, organizacion, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion = organizacion
        self.actor = actor  # la Membresia de quien usa el formulario
        self.fields["tipo"].queryset = TipoMiembro.objects.filter(organizacion=organizacion, activo=True)
        if not actor.es_dueno:
            # Solo el director nombra o quita administradores.
            del self.fields["es_administrador"]
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        es_admin = datos.get("es_administrador", self._es_administrador_actual())
        if not es_admin and not datos.get("tipo"):
            self.add_error("tipo", "Elige un tipo de miembro.")
        return datos

    def _tiene_acceso_actual(self):
        return True

    def _es_administrador_actual(self):
        return False


class _AccesoMixin(forms.Form):
    """Usuario para entrar al sistema. La contraseña no se escribe: la genera
    el sistema (`clave_temporal`) y se muestra una sola vez tras guardar."""

    username = forms.CharField(
        label="Usuario", max_length=150, required=False,
        help_text="Con este nombre entra por el enlace de la organización. Sin espacios. La contraseña temporal la genera "
        "Arca y te la muestra una sola vez al guardar.",
    )
    clave_generada = None

    def _validar_acceso(self, datos, organizacion, excluir=None):
        username = (datos.get("username") or "").strip()
        if not username:
            self.add_error("username", "Escribe el nombre de usuario.")
        else:
            try:
                Usuario.username_validator(username)
            except forms.ValidationError as error:
                self.add_error("username", error)
            else:
                # Único dentro de la organización: «maria» puede existir en otra.
                if Usuario.objects.filter(organizacion_cuenta=organizacion, username=username.lower()).exists():
                    self.add_error("username", "Ya hay alguien con ese usuario en la organización. Si está "
                                   "inactivo, reactívalo; si no, prueba con otro.")
        try:
            validar_limite_usuarios(organizacion, excluir=excluir)
        except forms.ValidationError as error:
            self.add_error(None, error)
        datos["username"] = username.lower()

    def _crear_usuario(self, datos, nombre, organizacion, telefono=""):
        usuario = Usuario(username=datos["username"], first_name=nombre[:150], telefono=telefono,
                          organizacion_cuenta=organizacion)
        self.clave_generada = asignar_clave_temporal(usuario)
        return usuario


class MiembroCrearForm(_AccesoMixin, _MiembroBase):
    con_acceso = forms.BooleanField(
        label="Puede entrar al sistema", required=False, initial=True,
        help_text="Apágalo para alguien de la comunidad que aporta o recibe, pero no va a usar Arca. "
        "Se le puede dar acceso después.",
    )
    telefono = forms.CharField(label="Teléfono", max_length=20, required=False)

    field_order = ["nombre_visible", "tipo", "es_administrador", "telefono", "con_acceso", "username"]

    def clean(self):
        datos = super().clean()
        if datos.get("con_acceso"):
            self._validar_acceso(datos, self.organizacion)
        elif datos.get("es_administrador"):
            self.add_error("con_acceso", "Un administrador necesita poder entrar al sistema.")
        return datos

    def save(self):
        datos = self.cleaned_data
        usuario = None
        if datos.get("con_acceso"):
            usuario = self._crear_usuario(datos, datos["nombre_visible"], self.organizacion, datos.get("telefono", ""))
        membresia = Membresia(
            organizacion=self.organizacion, user=usuario, tipo=datos.get("tipo"),
            es_administrador=datos.get("es_administrador", False),
            nombre_visible=datos["nombre_visible"],
        )
        membresia.full_clean()
        membresia.save()
        return membresia


class DarAccesoForm(_EstiloBootstrapMixin, _AccesoMixin):
    """Crea el usuario de un miembro que hasta ahora no entraba al sistema."""

    def __init__(self, *args, organizacion, membresia, **kwargs):
        super().__init__(*args, **kwargs)
        self.organizacion, self.membresia = organizacion, membresia
        self._aplicar_estilo()

    def clean(self):
        datos = super().clean()
        # Si la membresía está inactiva no ocupa cupo todavía.
        self._validar_acceso(datos, self.organizacion, excluir=None if self.membresia.activa else self.membresia.pk)
        return datos

    def save(self):
        membresia = self.membresia
        membresia.user = self._crear_usuario(self.cleaned_data, membresia.nombre, self.organizacion)
        membresia.full_clean()
        membresia.save(update_fields=["user"])
        return membresia


class MiembroEditarForm(_MiembroBase):
    def __init__(self, *args, membresia, **kwargs):
        self.membresia = membresia
        kwargs.setdefault("initial", {
            "nombre_visible": membresia.nombre,
            "tipo": membresia.tipo_id,
            "es_administrador": membresia.es_administrador,
        })
        super().__init__(*args, **kwargs)
        # Si el tipo actual quedó inactivo, se sigue ofreciendo para no forzar un cambio.
        if membresia.tipo_id:
            self.fields["tipo"].queryset = TipoMiembro.objects.filter(organizacion=self.organizacion).filter(
                Q(activo=True) | Q(pk=membresia.tipo_id)
            )

    def _es_administrador_actual(self):
        return self.membresia.es_administrador

    def clean(self):
        datos = super().clean()
        if datos.get("es_administrador") and not self.membresia.tiene_acceso:
            self.add_error("es_administrador", "Primero dale acceso al sistema.")
        return datos

    def save(self):
        datos = self.cleaned_data
        m = self.membresia
        m.nombre_visible = datos["nombre_visible"]
        m.tipo = datos.get("tipo")
        if "es_administrador" in datos:
            m.es_administrador = datos["es_administrador"]
        m.full_clean()
        m.save()
        return m


# --- Panel de plataforma (solo superadmin) ---------------------------------


class _OrganizacionPlataformaBase(_EstiloBootstrapMixin, forms.ModelForm):
    class Meta:
        model = Organizacion
        fields = ["nombre", "slug", "rif", "telefono", "email", "moneda_base", "plan", "activa_hasta", "limite_usuarios",
                  "director_ve_cuentas_personales", "notas"]
        widgets = {
            "activa_hasta": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notas": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {"nombre": "Nombre de la organización", "moneda_base": "Moneda base", "slug": "Enlace"}
        help_texts = {"slug": "La dirección por la que entra su gente: /enlace/. Vacío al crear: se arma del nombre."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = bool(self.instance.pk)
        self.fields["slug"].validators = []     # lo valida clean_slug, con mensajes propios
        self._aplicar_estilo()

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip().lower()
        if not slug and not self.instance.pk:
            return ""
        return validar_enlace(slug, excluir_pk=self.instance.pk)

    def clean_limite_usuarios(self):
        limite = self.cleaned_data.get("limite_usuarios")
        if limite is not None and limite < 1:
            raise forms.ValidationError("Debe permitir al menos un usuario (el director). Vacío = sin límite.")
        return limite


class NuevaOrganizacionForm(_OrganizacionPlataformaBase):
    usuario_director = forms.CharField(
        label="Usuario del director", max_length=150, validators=[Usuario.username_validator],
        help_text="Es una cuenta propia de esta organización: puede repetirse en otra.",
    )
    nombre_director = forms.CharField(label="Nombre del director", max_length=120, required=False)


class EditarOrganizacionForm(_OrganizacionPlataformaBase):
    class Meta(_OrganizacionPlataformaBase.Meta):
        fields = [*_OrganizacionPlataformaBase.Meta.fields, "activa"]
        labels = {**_OrganizacionPlataformaBase.Meta.labels, "activa": "Acceso habilitado"}
        help_texts = {**_OrganizacionPlataformaBase.Meta.help_texts, "activa": "Apagado = suspendida: nadie de la organización puede entrar. No borra nada."}
