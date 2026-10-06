"""Pantallas del inventario. Todo exige el permiso «Gestionar inventario»
(el director y los administradores lo tienen siempre) y se filtra por
`request.organizacion`: un pk de otra organización responde 404."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.mixins import requiere_permiso, tiene_permiso
from core.models import RegistroAuditoria
from core.utils import eliminar_protegido
from finanzas.services import tasa_vigente

from . import services
from .forms import AnularInventarioForm, ArticuloForm, CategoriaForm, MovimientoInventarioForm, UbicacionForm
from .models import Articulo, CategoriaArticulo, MovimientoInventario, Ubicacion

Accion = RegistroAuditoria.Accion
GESTIONAR = "puede_gestionar_inventario"
TITULOS = {"entrada": "Registrar entrada", "salida": "Registrar salida", "traslado": "Cambiar de ubicación"}


def _errores_al_form(form, error):
    if hasattr(error, "message_dict"):
        for campo, mensajes in error.message_dict.items():
            form.add_error(campo if campo in form.fields else None, mensajes)
    else:
        form.add_error(None, error.messages)


@requiere_permiso(GESTIONAR)
def inicio(request):
    organizacion = request.organizacion
    tasa, _ = tasa_vigente()
    filas, totales = services.resumen(organizacion, tasa)

    clase, categoria, ubicacion = request.GET.get("clase", ""), request.GET.get("categoria", ""), request.GET.get("ubicacion", "")
    q, solo = request.GET.get("q", "").strip().lower(), request.GET.get("solo", "")
    if solo != "inactivos":
        filas = [a for a in filas if a.activo]
    else:
        filas = [a for a in filas if not a.activo]
    if clase in Articulo.Clase.values:
        filas = [a for a in filas if a.clase == clase]
    if categoria.isdigit():
        filas = [a for a in filas if a.categoria_id == int(categoria)]
    if q:
        filas = [a for a in filas if q in a.nombre.lower() or q in a.codigo.lower()]
    if solo == "minimo":
        filas = [a for a in filas if a.bajo_minimo]
    if ubicacion.isdigit():
        # En una ubicación concreta se muestra lo que hay ahí, no el total.
        aqui = {art: cant for (art, ubi), cant in services.existencias(organizacion).items() if ubi == int(ubicacion)}
        filas = [a for a in filas if aqui.get(a.pk)]
        for a in filas:
            a.existencia = aqui[a.pk]
    return render(request, "inventario/inicio.html", {
        "articulos": filas, "totales": totales, "tasa": tasa,
        "categorias": CategoriaArticulo.objects.filter(organizacion=organizacion),
        "ubicaciones": Ubicacion.objects.filter(organizacion=organizacion),
        "f": {"clase": clase, "categoria": categoria, "ubicacion": ubicacion, "q": request.GET.get("q", ""), "solo": solo},
        "hay_ubicaciones": Ubicacion.objects.filter(organizacion=organizacion, activa=True).exists(),
    })


def _articulo(request, pk):
    return get_object_or_404(
        Articulo.objects.select_related("categoria", "responsable", "responsable__user"),
        pk=pk, organizacion=request.organizacion)


@requiere_permiso(GESTIONAR)
def articulo_form(request, pk=None):
    articulo = _articulo(request, pk) if pk else None
    form = ArticuloForm(request.POST or None, instance=articulo, organizacion=request.organizacion)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                articulo = form.save()
                cantidad = form.cleaned_data.get("cantidad_inicial")
                if cantidad:
                    services.registrar(MovimientoInventario(
                        organizacion=request.organizacion, articulo=articulo, tipo="entrada", motivo="inicial",
                        cantidad=cantidad, destino=form.cleaned_data["ubicacion_inicial"],
                    ), usuario=request.user)
        except ValidationError as error:
            _errores_al_form(form, error)
        else:
            registrar(request, Accion.EDITAR_ARTICULO if pk else Accion.CREAR_ARTICULO, modelo="Articulo",
                      objeto_id=articulo.pk, descripcion=f"{articulo.get_clase_display()}: {articulo.nombre}"
                      + (" · campos: " + ", ".join(form.changed_data) if pk and form.changed_data else ""))
            messages.success(request, f"«{articulo.nombre}» guardado.")
            if "otro" in request.POST:
                return redirect("inventario:articulo_crear")
            return redirect("inventario:articulo_detalle", pk=articulo.pk)
    return render(request, "inventario/articulo_form.html", {
        "form": form, "articulo": articulo,
        "hay_ubicaciones": Ubicacion.objects.filter(organizacion=request.organizacion, activa=True).exists(),
    })


@requiere_permiso(GESTIONAR)
def articulo_detalle(request, pk):
    articulo = _articulo(request, pk)
    por_ubicacion = services.existencias(request.organizacion, articulo=articulo)
    nombres = dict(Ubicacion.objects.filter(organizacion=request.organizacion).values_list("pk", "nombre"))
    donde = sorted(((nombres.get(u, "—"), c) for (_, u), c in por_ubicacion.items() if c), key=lambda x: x[0].lower())
    total = sum((c for _, c in donde), services.CERO)
    return render(request, "inventario/articulo_detalle.html", {
        "a": articulo, "donde": donde, "total": total,
        "bajo_minimo": articulo.es_consumible and articulo.minimo is not None and total <= articulo.minimo,
        "valor": articulo.valor_unitario * total if articulo.valor_unitario is not None else None,
        "movimientos": articulo.movimientos.select_related("origen", "destino", "registrado_por")[:60],
    })


@requiere_permiso(GESTIONAR)
@require_POST
def articulo_eliminar(request, pk):
    return eliminar_protegido(request, _articulo(request, pk), "inventario:inicio")


@requiere_permiso(GESTIONAR)
def movimiento_nuevo(request, tipo):
    organizacion = request.organizacion
    inicial = {}
    if request.GET.get("articulo", "").isdigit():
        inicial["articulo"] = request.GET["articulo"]
    form = MovimientoInventarioForm(request.POST or None, organizacion=organizacion, tipo=tipo, initial=inicial)
    if request.method == "POST" and form.is_valid():
        try:
            movimiento = services.registrar(form.save(commit=False), usuario=request.user)
        except ValidationError as error:
            _errores_al_form(form, error)
        else:
            a = movimiento.articulo
            registrar(request, Accion.MOVER_INVENTARIO, modelo="MovimientoInventario", objeto_id=movimiento.pk,
                      descripcion=f"{movimiento.get_tipo_display()} · {movimiento.get_motivo_display()} · "
                      f"{movimiento.cantidad.normalize():f} {a.unidad} de {a.nombre} · "
                      f"{movimiento.origen or ''}{' → ' if movimiento.origen_id and movimiento.destino_id else ''}{movimiento.destino or ''}")
            messages.success(request, f"{movimiento.get_tipo_display()} registrada: {movimiento.cantidad.normalize():f} "
                             f"{a.unidad} de «{a.nombre}»." if tipo != "traslado" else f"«{a.nombre}» cambiado de ubicación.")
            if "otro" in request.POST:
                return redirect(request.path)
            return redirect("inventario:articulo_detalle", pk=a.pk)
    # Para que el formulario diga cuánto hay en cada ubicación del artículo elegido.
    hay = {}
    for (articulo_id, ubicacion_id), cantidad in services.existencias(organizacion).items():
        if cantidad:
            hay.setdefault(str(articulo_id), {})[str(ubicacion_id)] = float(cantidad)
    unidades = {str(pk): u for pk, u in Articulo.objects.filter(organizacion=organizacion).values_list("pk", "unidad")}
    return render(request, "inventario/movimiento_form.html", {
        "form": form, "tipo": tipo, "titulo": TITULOS[tipo], "hay": hay, "unidades": unidades,
        "sin_articulos": not form.fields["articulo"].queryset.exists(),
        "sin_ubicaciones": not Ubicacion.objects.filter(organizacion=organizacion, activa=True).exists(),
    })


@requiere_permiso(GESTIONAR)
def movimiento_anular(request, pk):
    movimiento = get_object_or_404(
        MovimientoInventario.objects.select_related("articulo", "origen", "destino"), pk=pk, organizacion=request.organizacion)
    if movimiento.anulado:
        messages.info(request, "Ese movimiento ya está anulado.")
        return redirect("inventario:articulo_detalle", pk=movimiento.articulo_id)
    form = AnularInventarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.anular(movimiento, usuario=request.user, motivo=form.cleaned_data["motivo"])
        except ValidationError as error:
            _errores_al_form(form, error)
        else:
            registrar(request, Accion.ANULAR_INVENTARIO, modelo="MovimientoInventario", objeto_id=movimiento.pk,
                      descripcion=f"{movimiento} · Motivo: {movimiento.motivo_anulacion}")
            messages.success(request, "Movimiento anulado.")
            return redirect("inventario:articulo_detalle", pk=movimiento.articulo_id)
    return render(request, "inventario/movimiento_anular.html", {"form": form, "m": movimiento})


@requiere_permiso(GESTIONAR)
def movimientos(request):
    """Historial general, del más reciente al más antiguo."""
    qs = MovimientoInventario.objects.filter(organizacion=request.organizacion).select_related(
        "articulo", "origen", "destino", "registrado_por")
    tipo, q = request.GET.get("tipo", ""), request.GET.get("q", "").strip()
    if tipo in MovimientoInventario.Tipo.values:
        qs = qs.filter(tipo=tipo)
    if q:
        qs = qs.filter(Q(articulo__nombre__icontains=q) | Q(nota__icontains=q))
    return render(request, "inventario/movimientos.html", {"movimientos": qs[:200], "tipo": tipo, "q": q})


# --- Ubicaciones y categorías ------------------------------------------------

CATALOGOS = {
    "ubicacion": (Ubicacion, UbicacionForm, "ubicación"),
    "categoria": (CategoriaArticulo, CategoriaForm, "categoría"),
}


@requiere_permiso(GESTIONAR)
def catalogos(request):
    organizacion = request.organizacion
    cantidades = {}
    for (_, ubicacion_id), cantidad in services.existencias(organizacion).items():
        if cantidad:
            cantidades[ubicacion_id] = cantidades.get(ubicacion_id, 0) + 1
    ubicaciones = list(Ubicacion.objects.filter(organizacion=organizacion))
    for u in ubicaciones:
        u.n_articulos = cantidades.get(u.pk, 0)
    return render(request, "inventario/catalogos.html", {
        "ubicaciones": ubicaciones, "categorias": CategoriaArticulo.objects.filter(organizacion=organizacion),
    })


@requiere_permiso(GESTIONAR)
def catalogo_form(request, cual, pk=None):
    if cual not in CATALOGOS:
        raise Http404
    modelo, clase_form, nombre = CATALOGOS[cual]
    objeto = get_object_or_404(modelo, pk=pk, organizacion=request.organizacion) if pk else None
    form = clase_form(request.POST or None, instance=objeto, organizacion=request.organizacion)
    if request.method == "POST" and form.is_valid():
        objeto = form.save()
        messages.success(request, f"«{objeto}» guardado.")
        return redirect("inventario:catalogos")
    return render(request, "finanzas/catalogo_form.html", {
        "form": form, "titulo": (f"Editar {nombre}" if pk else f"Nueva {nombre}"), "volver": "/inventario/catalogos/",
    })


@requiere_permiso(GESTIONAR)
@require_POST
def catalogo_eliminar(request, cual, pk):
    if cual not in CATALOGOS:
        raise Http404
    modelo = CATALOGOS[cual][0]
    return eliminar_protegido(request, get_object_or_404(modelo, pk=pk, organizacion=request.organizacion), "inventario:catalogos")


# --- Reportes ---------------------------------------------------------------


@login_required
def reportes(request, clave=None):
    """Reportes del inventario en pantalla, Excel o PDF. Los ve quien gestiona
    el inventario o quien tiene «Ver reportes»."""
    from datetime import date

    from django.utils import timezone

    from reportes.views import _archivo, _consulta_sin_formato

    from . import reportes as rep

    if not (tiene_permiso(request, GESTIONAR) or tiene_permiso(request, "puede_ver_reportes")):
        raise PermissionDenied("No tienes permiso para ver los reportes del inventario.")
    if clave is None:
        return render(request, "inventario/reportes.html", {
            "catalogo": [{"clave": k, "titulo": t, "descripcion": d, "icono": i} for k, (t, d, i, _) in rep.CATALOGO.items()],
            "gestiona": tiene_permiso(request, GESTIONAR),
        })
    if clave not in rep.CATALOGO:
        raise Http404
    organizacion, hoy = request.organizacion, timezone.localdate()
    tasa, _ = tasa_vigente()
    g = request.GET

    def fecha(nombre, defecto):
        try:
            return date.fromisoformat(g.get(nombre, ""))
        except ValueError:
            return defecto

    v = {
        "clase": g.get("clase", "") if g.get("clase", "") in Articulo.Clase.values else "",
        "moneda": g.get("moneda") if g.get("moneda") in ("USD", "VES") else organizacion.moneda_base,
        "ubicacion": Ubicacion.objects.filter(organizacion=organizacion, pk=g["ubicacion"]).first() if g.get("ubicacion", "").isdigit() else None,
        "articulo": Articulo.objects.filter(organizacion=organizacion, pk=g["articulo"]).first() if g.get("articulo", "").isdigit() else None,
        "desde": fecha("desde", hoy.replace(day=1)), "hasta": fecha("hasta", hoy),
    }
    if clave == "existencias":
        resultado = rep.existencias(organizacion, hoy, v["clase"], v["ubicacion"], v["moneda"], tasa)
    elif clave == "ubicaciones":
        resultado = rep.por_ubicacion(organizacion, hoy, v["clase"], v["ubicacion"], v["moneda"], tasa)
    elif clave == "reponer":
        resultado = rep.por_reponer(organizacion, hoy)
    else:
        resultado = rep.movimientos(organizacion, v["desde"], v["hasta"], v["articulo"])
    if g.get("formato"):
        return _archivo(request, resultado, g["formato"])
    return render(request, "inventario/reporte.html", {
        "reporte": resultado, "clave": clave, "usa": rep.CATALOGO[clave][3], "v": v,
        "consulta": _consulta_sin_formato(request),
        "ubicaciones": Ubicacion.objects.filter(organizacion=organizacion),
        "articulos": Articulo.objects.filter(organizacion=organizacion),
    })
