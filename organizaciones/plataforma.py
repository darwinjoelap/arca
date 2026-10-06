"""Panel de plataforma (/plataforma/), solo para el superadmin de Arca.

Alta de organizaciones con su director, y control de la suscripción: plan,
vencimiento, límite de usuarios, suspensión. Estructura tomada de Ordo.

Diferencia deliberada con Ordo: aquí NO existe «entrar como soporte». El
superadmin administra la suscripción pero no ve el dinero de la organización
(decisión A-03); lo único que decide sobre sus datos es el interruptor
`director_ve_cuentas_personales`.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.auditoria import registrar
from core.models import RegistroAuditoria

from .forms import EditarOrganizacionForm, NuevaOrganizacionForm
from .models import Membresia, Organizacion
from .services import asignar_clave_temporal, clave_temporal, crear_organizacion

Accion = RegistroAuditoria.Accion
SUSCRIPCION = ["plan", "activa_hasta", "limite_usuarios", "activa", "slug"]


def solo_plataforma(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not (request.user.is_active and request.user.is_superuser):
            raise PermissionDenied("Esta pantalla es del soporte de Arca.")
        return vista(request, *args, **kwargs)
    return login_required(envoltura)


def _credenciales(request, organizacion, membresia, clave, titulo):
    respuesta = render(request, "organizaciones/credenciales.html", {
        "titulo": titulo, "nombre": membresia.nombre, "usuario": membresia.user.username, "clave": clave,
        "organizacion_nombre": organizacion.nombre, "enlace": request.build_absolute_uri(f"/{organizacion.slug}/"),
        "volver": reverse("plataforma:editar", args=[organizacion.pk]), "volver_texto": organizacion.nombre,
    })
    respuesta["Cache-Control"] = "no-store"
    return respuesta


@solo_plataforma
def lista(request):
    q = request.GET.get("q", "").strip()
    organizaciones = Organizacion.objects.annotate(
        n_acceso=Count("membresias", filter=Q(membresias__activa=True, membresias__user__isnull=False)),
        n_miembros=Count("membresias", filter=Q(membresias__activa=True)),
    ).order_by("nombre")
    if q:
        organizaciones = organizaciones.filter(Q(nombre__icontains=q) | Q(rif__icontains=q) | Q(slug__icontains=q))
    organizaciones = list(organizaciones)
    return render(request, "plataforma/lista.html", {
        "organizaciones": organizaciones, "q": q,
        "por_vencer": sum(1 for o in organizaciones if o.esta_vigente and o.dias_para_vencer is not None and o.dias_para_vencer <= 7),
        "sin_acceso": sum(1 for o in organizaciones if not o.esta_vigente),
    })


@solo_plataforma
def nueva(request):
    form = NuevaOrganizacionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        datos = dict(form.cleaned_data)
        usuario_director, nombre_director = datos.pop("usuario_director"), datos.pop("nombre_director")
        nombre, moneda, slug = datos.pop("nombre"), datos.pop("moneda_base"), datos.pop("slug") or None
        clave = clave_temporal()
        organizacion, membresia, _ = crear_organizacion(
            nombre=nombre, usuario_director=usuario_director, clave=clave, nombre_director=nombre_director,
            moneda_base=moneda, slug=slug, **datos)
        registrar(request, Accion.CREAR_ORGANIZACION, modelo="Organizacion", objeto_id=organizacion.pk,
                  descripcion=f"{organizacion.nombre} (/{organizacion.slug}/) — director: {membresia.user.username} · "
                  f"plan {organizacion.get_plan_display()}", organizacion=organizacion)
        return _credenciales(request, organizacion, membresia, clave, "Organización creada")
    return render(request, "plataforma/form.html", {"form": form, "o": None})


@solo_plataforma
def editar(request, pk):
    organizacion = get_object_or_404(Organizacion, pk=pk)
    antes = {c: getattr(organizacion, c) for c in [*SUSCRIPCION, "director_ve_cuentas_personales"]}
    form = EditarOrganizacionForm(request.POST or None, instance=organizacion)
    if request.method == "POST" and form.is_valid():
        organizacion = form.save()
        cambios = [f"{c}: {antes[c]} → {getattr(organizacion, c)}" for c in SUSCRIPCION if antes[c] != getattr(organizacion, c)]
        if cambios:
            registrar(request, Accion.EDITAR_SUSCRIPCION, modelo="Organizacion", objeto_id=organizacion.pk,
                      descripcion="; ".join(cambios), organizacion=organizacion)
        if antes["director_ve_cuentas_personales"] != organizacion.director_ve_cuentas_personales:
            registrar(request, Accion.VISIBILIDAD_CUENTAS, modelo="Organizacion", objeto_id=organizacion.pk,
                      descripcion="Visibilidad de cuentas personales para el director: "
                      + ("ENCENDIDA" if organizacion.director_ve_cuentas_personales else "APAGADA"), organizacion=organizacion)
        messages.success(request, f"{organizacion.nombre}: cambios guardados.")
        return redirect("plataforma:editar", pk=pk)
    # Del equipo se muestra quién es y su rol, nunca montos.
    miembros = Membresia.objects.filter(organizacion=organizacion).select_related("user", "tipo").order_by(
        "-activa", "-es_dueno", "-es_administrador", "nombre_visible")
    return render(request, "plataforma/form.html", {
        "form": form, "o": organizacion, "miembros": miembros, "director": organizacion.director,
        "n_acceso": organizacion.usuarios_con_acceso(), "enlace": request.build_absolute_uri(f"/{organizacion.slug}/"),
    })


@solo_plataforma
@require_POST
def restablecer_clave_director(request, pk):
    """Para cuando el director pierde su clave: nadie dentro de la organización puede restablecérsela."""
    organizacion = get_object_or_404(Organizacion, pk=pk)
    director = organizacion.director
    if director is None or director.user is None:
        messages.error(request, "Esta organización no tiene director con acceso.")
        return redirect("plataforma:editar", pk=pk)
    if director.user.is_superuser:
        raise PermissionDenied("La clave de una cuenta de plataforma no se restablece desde aquí.")
    clave = asignar_clave_temporal(director.user)
    registrar(request, Accion.RESTABLECER_CLAVE, modelo="Usuario", objeto_id=director.user_id,
              descripcion=f"{director.user.username} (director, desde la plataforma)", organizacion=organizacion)
    return _credenciales(request, organizacion, director, clave, "Contraseña temporal")
