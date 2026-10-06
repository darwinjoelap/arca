"""Libro de caja: catálogos (cajas, cuentas, conceptos) y movimientos.

Como en `organizaciones`, todo objeto se busca filtrando por
`request.organizacion`; un pk de otra organización responde 404.

Quién ve qué en el libro:
- Director y administradores, y quien tenga `puede_ver_movimientos`: todo.
- Quien solo registra (ingresos o egresos): lo que registró él mismo.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView

from cambio.services import formatear
from core.auditoria import registrar
from core.mixins import ADMINISTRAR, DeLaOrganizacionMixin, PermisoRequeridoMixin, requiere_permiso, tiene_permiso
from core.models import RegistroAuditoria
from core.utils import eliminar_protegido

from .forms import (
    AnularForm, CajaForm, ConceptoForm, CuentaForm, CuotaForm, FiltroMovimientosForm, MovimientoForm, TrasladoForm,
)
from .models import Caja, Concepto, Cuenta, CuotaMiembro, Movimiento, Traslado
from .services import _sumas_por_cuenta, estado_cuotas, registrar_movimiento, registrar_traslado, tasa_vigente

Accion = RegistroAuditoria.Accion

PERMISO_POR_TIPO = {
    Movimiento.Tipo.INGRESO: "puede_registrar_ingresos",
    Movimiento.Tipo.EGRESO: "puede_registrar_egresos",
}


def ve_todo_el_libro(request):
    return tiene_permiso(request, "puede_ver_movimientos")  # director y administradores incluidos


def entra_al_libro(request):
    return any(
        tiene_permiso(request, p)
        for p in ("puede_ver_movimientos", "puede_registrar_ingresos", "puede_registrar_egresos")
    )


def movimientos_visibles(request):
    """El queryset base de TODA pantalla de movimientos."""
    qs = Movimiento.objects.filter(organizacion=request.organizacion)
    if not ve_todo_el_libro(request):
        qs = qs.filter(registrado_por=request.user)
    return qs


# --- Movimientos -----------------------------------------------------------


class MovimientoListView(ListView):
    template_name = "finanzas/movimiento_lista.html"
    context_object_name = "movimientos"
    paginate_by = 40

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        if not entra_al_libro(request):
            raise PermissionDenied("No tienes permiso para ver el libro de caja.")
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        self.filtro = FiltroMovimientosForm(self.request.GET or None, organizacion=self.request.organizacion)
        qs = movimientos_visibles(self.request).select_related(
            "cuenta", "caja", "concepto", "concepto__padre", "miembro", "miembro__user", "registrado_por"
        )
        return self.filtro.aplicar(qs) if self.request.GET else qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        consulta = self.request.GET.copy()
        consulta.pop("page", None)
        ctx.update(
            filtro=self.filtro,
            consulta=consulta.urlencode(),
            ve_todo=ve_todo_el_libro(self.request),
            puede_ingresos=tiene_permiso(self.request, "puede_registrar_ingresos"),
            puede_egresos=tiene_permiso(self.request, "puede_registrar_egresos"),
            por_aprobar=(
                Movimiento.objects.filter(
                    organizacion=self.request.organizacion, estado=Movimiento.Estado.REGISTRADO
                ).count()
                if tiene_permiso(self.request, ADMINISTRAR) else 0
            ),
        )
        return ctx


def _avisar_si_excede_partida(request, movimiento):
    """Aviso (no bloqueo) cuando un egreso deja su partida del mes en rojo."""
    from presupuestos.services import estado_de_partida

    if movimiento.tipo != Movimiento.Tipo.EGRESO:
        return
    estado = estado_de_partida(
        request.organizacion, movimiento.caja_id, movimiento.concepto_id, movimiento.fecha, excluir=movimiento.pk)
    if estado is None:
        return
    este = movimiento.monto_usd if estado["moneda"] == "USD" else movimiento.monto_ves
    exceso = este - estado["disponible"]
    if exceso > 0:
        simbolo = "$" if estado["moneda"] == "USD" else "Bs."
        messages.warning(
            request,
            f"Con este egreso, la partida «{estado['concepto']}» de {estado['mes']} queda excedida en "
            f"{simbolo} {formatear(exceso, 2)} (presupuesto: {simbolo} {formatear(estado['presupuesto'], 2)}).",
        )


@login_required
def movimiento_registrar(request, tipo):
    if not tiene_permiso(request, PERMISO_POR_TIPO[tipo]):
        raise PermissionDenied("No tienes permiso para registrar este tipo de movimiento.")
    organizacion = request.organizacion

    form = MovimientoForm(request.POST or None, organizacion=organizacion, tipo=tipo)
    if request.method == "POST" and form.is_valid():
        movimiento = form.save(commit=False)
        movimiento.uuid_cliente = form.cleaned_data.get("uuid_cliente")
        try:
            movimiento, creado = registrar_movimiento(movimiento, membresia=request.membresia)
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for campo, mensajes in error.message_dict.items():
                    form.add_error(campo if campo in form.fields else None, mensajes)
            else:
                form.add_error(None, error.messages)
        else:
            if creado:
                registrar(
                    request, Accion.REGISTRAR_MOVIMIENTO, modelo="Movimiento", objeto_id=movimiento.pk,
                    descripcion=f"{movimiento.get_tipo_display()} #{movimiento.numero_vale} · {movimiento.titulo} · "
                    f"{movimiento.moneda} {movimiento.monto:.2f} · {movimiento.cuenta}",
                )
                if movimiento.estado == Movimiento.Estado.REGISTRADO:
                    messages.info(request, f"Egreso #{movimiento.numero_vale} registrado. Queda por aprobar.")
                else:
                    messages.success(request, f"{movimiento.get_tipo_display()} #{movimiento.numero_vale} registrado.")
                _avisar_si_excede_partida(request, movimiento)
            else:
                messages.info(request, "Ese movimiento ya estaba registrado; no se duplicó.")
            if "otro" in request.POST:
                return redirect(request.path)
            return redirect("finanzas:movimiento_detalle", pk=movimiento.pk)

    tasa, tasa_exacta = tasa_vigente()
    contexto = {
        "form": form,
        "tipo": tipo,
        "es_ingreso": tipo == Movimiento.Tipo.INGRESO,
        "tasa": tasa,
        "tasa_exacta": tasa_exacta,
        "monedas_por_cuenta": form.cuentas_para_js(),
        "sin_cuentas": not form.fields["cuenta"].queryset.exists(),
    }
    return render(request, "finanzas/movimiento_form.html", contexto)


@login_required
def movimiento_detalle(request, pk):
    if not entra_al_libro(request):
        raise PermissionDenied("No tienes permiso para ver el libro de caja.")
    movimiento = get_object_or_404(
        movimientos_visibles(request).select_related(
            "cuenta", "caja", "concepto", "concepto__padre", "miembro", "miembro__user",
            "registrado_por", "aprobado_por", "anulado_por", "tasa", "ejercicio",
        ),
        pk=pk,
    )
    return render(request, "finanzas/movimiento_detalle.html", {
        "m": movimiento, "puede_administrar_libro": tiene_permiso(request, ADMINISTRAR),
    })


@requiere_permiso()
@require_POST
def movimiento_aprobar(request, pk):
    movimiento = get_object_or_404(Movimiento, pk=pk, organizacion=request.organizacion)
    try:
        movimiento.transicionar(Movimiento.Estado.CONFIRMADO, request.user)
    except ValidationError as error:
        messages.error(request, " ".join(error.messages))
    else:
        registrar(request, Accion.APROBAR_MOVIMIENTO, modelo="Movimiento", objeto_id=movimiento.pk,
                  descripcion=f"{movimiento.get_tipo_display()} #{movimiento.numero_vale} · {movimiento.titulo}")
        messages.success(request, f"Egreso #{movimiento.numero_vale} aprobado.")
    if request.POST.get("volver") == "lista":
        return redirect("finanzas:movimiento_lista")
    return redirect("finanzas:movimiento_detalle", pk=pk)


@requiere_permiso()
def movimiento_anular(request, pk):
    movimiento = get_object_or_404(Movimiento, pk=pk, organizacion=request.organizacion)
    if movimiento.estado == Movimiento.Estado.ANULADO:
        messages.info(request, "Ese movimiento ya está anulado.")
        return redirect("finanzas:movimiento_detalle", pk=pk)
    anticipo = getattr(movimiento, "anticipo_entregado", None)
    if anticipo is not None:
        # Anularlo aquí dejaría el anticipo «por rendir» sin su dinero.
        messages.info(request, "Este egreso es la entrega de un anticipo: se rinde o se anula desde el anticipo.")
        return redirect("finanzas:anticipo_detalle", pk=anticipo.pk)
    form = AnularForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            movimiento.transicionar(Movimiento.Estado.ANULADO, request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            registrar(request, Accion.ANULAR_MOVIMIENTO, modelo="Movimiento", objeto_id=movimiento.pk,
                      descripcion=f"{movimiento.get_tipo_display()} #{movimiento.numero_vale} · "
                      f"{movimiento.moneda} {movimiento.monto:.2f} · Motivo: {movimiento.motivo_anulacion}")
            messages.success(request, f"{movimiento.get_tipo_display()} #{movimiento.numero_vale} anulado.")
            return redirect("finanzas:movimiento_detalle", pk=pk)
    return render(request, "finanzas/movimiento_anular.html", {"form": form, "m": movimiento})


# --- Traslados entre cuentas -----------------------------------------------
# Solo director y administradores: mueven dinero entre cuentas y cajas.


class TrasladoListView(PermisoRequeridoMixin, DeLaOrganizacionMixin, ListView):
    model = Traslado
    template_name = "finanzas/traslado_lista.html"
    context_object_name = "traslados"
    paginate_by = 40

    def get_queryset(self):
        return super().get_queryset().select_related(
            "cuenta_origen", "cuenta_origen__caja", "cuenta_destino", "cuenta_destino__caja", "registrado_por"
        )


@requiere_permiso()
def traslado_registrar(request):
    form = TrasladoForm(request.POST or None, organizacion=request.organizacion)
    if request.method == "POST" and form.is_valid():
        traslado = form.save(commit=False)
        traslado.uuid_cliente = form.cleaned_data.get("uuid_cliente")
        traslado.monto_destino = form.cleaned_data.get("monto_recibido")
        try:
            traslado, creado = registrar_traslado(traslado, usuario=request.user)
        except ValidationError as error:
            if hasattr(error, "message_dict"):
                for campo, mensajes in error.message_dict.items():
                    campo = "monto_recibido" if campo == "monto_destino" else campo
                    form.add_error(campo if campo in form.fields else None, mensajes)
            else:
                form.add_error(None, error.messages)
        else:
            if creado:
                o, d = traslado.cuenta_origen, traslado.cuenta_destino
                registrar(
                    request, Accion.REGISTRAR_TRASLADO, modelo="Traslado", objeto_id=traslado.pk,
                    descripcion=f"{o.caja.nombre} · {o.nombre}: {o.moneda} {traslado.monto_origen:.2f} → "
                    f"{d.caja.nombre} · {d.nombre}: {d.moneda} {traslado.monto_destino:.2f}",
                )
                messages.success(request, "Traslado registrado.")
            else:
                messages.info(request, "Ese traslado ya estaba registrado; no se duplicó.")
            return redirect("finanzas:traslado_lista")

    tasa, tasa_exacta = tasa_vigente()
    return render(request, "finanzas/traslado_form.html", {
        "form": form, "tasa": tasa, "tasa_exacta": tasa_exacta,
        "monedas_por_cuenta": form.cuentas_para_js(),
        "pocas_cuentas": form.fields["cuenta_origen"].queryset.count() < 2,
    })


@requiere_permiso()
def traslado_anular(request, pk):
    traslado = get_object_or_404(
        Traslado.objects.select_related("cuenta_origen", "cuenta_destino"), pk=pk, organizacion=request.organizacion
    )
    if traslado.estado == Traslado.Estado.ANULADO:
        messages.info(request, "Ese traslado ya está anulado.")
        return redirect("finanzas:traslado_lista")
    form = AnularForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        traslado.anular(request.user, form.cleaned_data["motivo"])
        registrar(request, Accion.ANULAR_TRASLADO, modelo="Traslado", objeto_id=traslado.pk,
                  descripcion=f"{traslado} · Motivo: {traslado.motivo_anulacion}")
        messages.success(request, "Traslado anulado.")
        return redirect("finanzas:traslado_lista")
    return render(request, "finanzas/traslado_anular.html", {"form": form, "t": traslado})


# --- Cajas y cuentas -------------------------------------------------------


@requiere_permiso()
def cajas(request):
    organizacion = request.organizacion
    sumas = _sumas_por_cuenta(organizacion)
    lista = list(Caja.objects.filter(organizacion=organizacion).prefetch_related("cuentas"))
    for caja in lista:
        caja.cuentas_con_saldo = [
            (cuenta, cuenta.saldo_inicial + sumas.get(cuenta.pk, 0)) for cuenta in caja.cuentas.all()
        ]
    return render(request, "finanzas/caja_lista.html", {"cajas": lista})


class _CatalogoMixin(PermisoRequeridoMixin, DeLaOrganizacionMixin):
    form_con_organizacion = True
    template_name = "finanzas/catalogo_form.html"
    accion_crear = accion_editar = None
    titulo_nuevo = titulo_editar = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["titulo"] = self.titulo_editar.format(self.object) if self.object else self.titulo_nuevo
        ctx["volver"] = self.success_url
        return ctx

    def form_valid(self, form):
        nuevo = form.instance.pk is None
        respuesta = super().form_valid(form)
        detalle = str(self.object)
        if form.changed_data and not nuevo:
            detalle += " · campos: " + ", ".join(form.changed_data)
        registrar(self.request, self.accion_crear if nuevo else self.accion_editar,
                  modelo=self.model.__name__, objeto_id=self.object.pk, descripcion=detalle)
        messages.success(self.request, f"«{self.object}» guardado.")
        return respuesta


class _CajaMixin(_CatalogoMixin):
    model = Caja
    form_class = CajaForm
    success_url = reverse_lazy("finanzas:caja_lista")
    accion_crear, accion_editar = Accion.CREAR_CAJA, Accion.EDITAR_CAJA
    titulo_nuevo, titulo_editar = "Nueva caja", "Editar la caja «{}»"


class CajaCreateView(_CajaMixin, CreateView):
    pass


class CajaUpdateView(_CajaMixin, UpdateView):
    pass


class _CuentaMixin(_CatalogoMixin):
    model = Cuenta
    form_class = CuentaForm
    success_url = reverse_lazy("finanzas:caja_lista")
    accion_crear, accion_editar = Accion.CREAR_CUENTA, Accion.EDITAR_CUENTA
    titulo_nuevo, titulo_editar = "Nueva cuenta", "Editar la cuenta «{}»"


class CuentaCreateView(_CuentaMixin, CreateView):
    def get_initial(self):
        inicial = super().get_initial()
        caja = self.request.GET.get("caja", "")
        if caja.isdigit() and Caja.objects.filter(pk=caja, organizacion=self.request.organizacion).exists():
            inicial["caja"] = int(caja)
        inicial.setdefault("moneda", self.request.organizacion.moneda_base)
        return inicial


class CuentaUpdateView(_CuentaMixin, UpdateView):
    def form_valid(self, form):
        if "saldo_inicial" in form.changed_data:
            # Mover el saldo inicial cambia el saldo sin un movimiento: se anota aparte.
            registrar(self.request, Accion.AJUSTAR_SALDO_CUENTA, modelo="Cuenta", objeto_id=form.instance.pk,
                      descripcion=f"{form.instance}: saldo inicial de {form.initial.get('saldo_inicial')} "
                      f"a {form.cleaned_data['saldo_inicial']}")
        return super().form_valid(form)


@requiere_permiso()
@require_POST
def caja_eliminar(request, pk):
    return eliminar_protegido(request, get_object_or_404(Caja, pk=pk, organizacion=request.organizacion), "finanzas:caja_lista")


@requiere_permiso()
@require_POST
def cuenta_eliminar(request, pk):
    return eliminar_protegido(request, get_object_or_404(Cuenta, pk=pk, organizacion=request.organizacion), "finanzas:caja_lista")


# --- Conceptos -------------------------------------------------------------


class ConceptoListView(PermisoRequeridoMixin, DeLaOrganizacionMixin, ListView):
    model = Concepto
    template_name = "finanzas/concepto_lista.html"
    context_object_name = "conceptos"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        todos = list(self.get_queryset().select_related("padre", "caja"))
        grupos = {"ingreso": [], "egreso": []}
        hijos = {}
        for c in todos:
            if c.padre_id:
                hijos.setdefault(c.padre_id, []).append(c)
        for c in todos:
            if not c.padre_id:
                grupos[c.tipo].append((c, sorted(hijos.get(c.pk, []), key=lambda h: h.nombre.lower())))
        for lista in grupos.values():
            lista.sort(key=lambda par: par[0].nombre.lower())
        ctx["grupos"] = [("Ingresos", "ingreso", grupos["ingreso"]), ("Egresos", "egreso", grupos["egreso"])]
        return ctx


class _ConceptoMixin(_CatalogoMixin):
    model = Concepto
    form_class = ConceptoForm
    success_url = reverse_lazy("finanzas:concepto_lista")
    accion_crear, accion_editar = Accion.CREAR_CONCEPTO, Accion.EDITAR_CONCEPTO
    titulo_nuevo, titulo_editar = "Nuevo concepto", "Editar el concepto «{}»"


class ConceptoCreateView(_ConceptoMixin, CreateView):
    def get_initial(self):
        inicial = super().get_initial()
        if self.request.GET.get("tipo") in Concepto.Tipo.values:
            inicial["tipo"] = self.request.GET["tipo"]
        return inicial


class ConceptoUpdateView(_ConceptoMixin, UpdateView):
    pass


@requiere_permiso()
@require_POST
def concepto_eliminar(request, pk):
    return eliminar_protegido(
        request, get_object_or_404(Concepto, pk=pk, organizacion=request.organizacion), "finanzas:concepto_lista"
    )


# --- Cuotas de miembros -----------------------------------------------------


def _ejercicio_actual(organizacion):
    from organizaciones.models import Ejercicio

    hoy = timezone.localdate()
    qs = Ejercicio.objects.filter(organizacion=organizacion)
    return qs.filter(activo=True).first() or qs.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy).first() or qs.first()


@requiere_permiso()
def cuotas(request):
    """Lo que se espera de cada miembro y cuánto lleva pagado en el ejercicio."""
    ejercicio = _ejercicio_actual(request.organizacion)
    filas = estado_cuotas(request.organizacion, ejercicio) if ejercicio else []
    totales = {}
    for fila in filas:
        t = totales.setdefault(fila["cuota"].moneda, {"esperado": 0, "pagado": 0, "pendiente": 0})
        for clave in t:
            t[clave] += fila[clave]
    sin_aplicar = CuotaMiembro.objects.filter(organizacion=request.organizacion).exclude(
        pk__in=[f["cuota"].pk for f in filas]).select_related("membresia", "membresia__user", "concepto")
    return render(request, "finanzas/cuota_lista.html", {
        "filas": filas, "totales": totales, "ejercicio": ejercicio, "sin_aplicar": sin_aplicar,
    })


class _CuotaMixin(_CatalogoMixin):
    model = CuotaMiembro
    form_class = CuotaForm
    success_url = reverse_lazy("finanzas:cuota_lista")
    accion_crear, accion_editar = Accion.CREAR_CUOTA, Accion.EDITAR_CUOTA
    titulo_nuevo, titulo_editar = "Nueva cuota", "Editar la cuota «{}»"


class CuotaCreateView(_CuotaMixin, CreateView):
    pass


class CuotaUpdateView(_CuotaMixin, UpdateView):
    pass


@requiere_permiso()
@require_POST
def cuota_eliminar(request, pk):
    return eliminar_protegido(
        request, get_object_or_404(CuotaMiembro, pk=pk, organizacion=request.organizacion), "finanzas:cuota_lista"
    )
