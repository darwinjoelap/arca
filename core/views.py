from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from finanzas.models import Movimiento
from finanzas.services import resumen_saldos, tasa_vigente, totales_periodo, totales_por_caja
from organizaciones.models import Ejercicio, Membresia, Organizacion

from .auditoria import registrar
from .middleware import CLAVE_SESION
from .models import RegistroAuditoria


def service_worker(request):
    """Sirve el service worker en la raíz del sitio (no en /static/) para que
    su scope por defecto cubra todo el origen."""
    return render(request, "core/sw.js", content_type="application/javascript")


def sin_conexion(request):
    """Página de respaldo que el service worker muestra cuando no hay red."""
    return render(request, "core/sin_conexion.html")


def salud(request):
    """Health check de la plataforma. Sin base de datos ni sesión a propósito."""
    return HttpResponse("ok", content_type="text/plain")


@login_required
def inicio(request):
    """Panel principal: fondos disponibles (en Bs. o USD), lo que entró y
    salió en el mes y los últimos movimientos. Los saldos solo los ve quien
    puede ver el libro completo."""
    organizacion = request.organizacion
    if organizacion is None:
        if request.user.is_superuser:
            return redirect("plataforma:lista")
        propias = Membresia.objects.filter(user=request.user, activa=True)
        if propias.filter(Organizacion.q_vigente("organizacion__")).exists():
            return redirect("organizaciones:seleccionar")
        # Sin ninguna organización vigente: se distingue «suspendida» de «sin acceso».
        suspendida = propias.select_related("organizacion").first()
        return render(request, "core/sin_organizacion.html", {"suspendida": suspendida.organizacion if suspendida else None})

    tasa, tasa_exacta = tasa_vigente()
    hoy = timezone.localdate()
    membresia = request.membresia
    ve_saldos = membresia.tiene_permiso("puede_ver_movimientos")  # director y administradores incluidos

    contexto = {
        "ejercicio_activo": Ejercicio.objects.filter(organizacion=organizacion, activo=True).first(),
        "tasa": tasa,
        "tasa_exacta": tasa_exacta,
        "total_miembros": Membresia.objects.filter(organizacion=organizacion, activa=True).count(),
        "ve_saldos": ve_saldos,
        "moneda_inicial": organizacion.moneda_base,
    }
    if ve_saldos:
        contexto["saldos"] = resumen_saldos(organizacion, tasa)
        contexto["mes"] = totales_periodo(organizacion, hoy.replace(day=1), hoy)
        # Con más de una caja, el total general no basta: cada una es un fondo aparte.
        if len(contexto["saldos"]["cajas"]) > 1:
            del_mes = totales_por_caja(organizacion, hoy.replace(day=1), hoy)
            vacio = {"ingreso": {"ves": 0, "usd": 0}, "egreso": {"ves": 0, "usd": 0}}
            for bloque in contexto["saldos"]["cajas"]:
                bloque["mes"] = del_mes.get(bloque["caja"].pk, vacio)
            contexto["por_caja"] = contexto["saldos"]["cajas"]
        contexto["ultimos"] = (
            Movimiento.objects.filter(organizacion=organizacion)
            .exclude(estado=Movimiento.Estado.ANULADO)
            .select_related("concepto", "concepto__padre", "cuenta", "miembro", "miembro__user")[:8]
        )
        if membresia.puede_administrar:
            contexto["por_aprobar"] = Movimiento.objects.filter(
                organizacion=organizacion, estado=Movimiento.Estado.REGISTRADO
            ).count()
    return render(request, "core/dashboard.html", contexto)


class CambiarClaveView(auth_views.PasswordChangeView):
    """Igual que la de Django, pero apaga `debe_cambiar_clave` y lo anota."""

    success_url = reverse_lazy("inicio")

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        usuario = self.request.user
        if usuario.debe_cambiar_clave:
            usuario.debe_cambiar_clave = False
            usuario.save(update_fields=["debe_cambiar_clave"])
        registrar(self.request, RegistroAuditoria.Accion.CAMBIAR_CLAVE, modelo="Usuario",
                  objeto_id=usuario.pk, descripcion=usuario.get_username())
        messages.success(self.request, "Contraseña actualizada.")
        return respuesta


# --- Entrada -----------------------------------------------------------------
# Cada organización entra por su enlace (/<slug>/), con sus propios usuarios.
# La dirección principal queda para las cuentas de plataforma.

COOKIE_ORGANIZACION = "arca_organizacion"


class EntrarPrincipal(auth_views.LoginView):
    """Login de la dirección principal: cuentas de plataforma. Si este equipo
    ya entró antes por el enlace de una organización, se le lleva a ese login
    (así la app instalada y «cerrar sesión» vuelven al lugar correcto)."""

    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        slug = request.COOKIES.get(COOKIE_ORGANIZACION)
        if (request.method == "GET" and slug and "plataforma" not in request.GET
                and not request.user.is_authenticated and Organizacion.objects.filter(slug=slug).exists()):
            return redirect("entrada_organizacion", slug=slug)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["login_plataforma"] = True
        return ctx


class EntradaOrganizacion(auth_views.LoginView):
    def dispatch(self, request, *args, **kwargs):
        self.organizacion = get_object_or_404(Organizacion, slug=kwargs["slug"])
        if not self.organizacion.esta_vigente:
            return render(request, "registration/suspendida.html", {"organizacion_marca": self.organizacion}, status=403)
        request.organizacion_login = self.organizacion     # el backend busca el usuario dentro de esta organización
        if request.user.is_authenticated:
            if request.user.organizacion_cuenta_id == self.organizacion.pk:
                request.session[CLAVE_SESION] = self.organizacion.pk
            return redirect("inicio")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["organizacion_marca"] = self.organizacion
        return ctx

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        self.request.session[CLAVE_SESION] = self.organizacion.pk
        respuesta.set_cookie(COOKIE_ORGANIZACION, self.organizacion.slug, max_age=60 * 60 * 24 * 365,
                             samesite="Lax", secure=self.request.is_secure(), httponly=True)
        return respuesta

    def get_success_url(self):
        return "/"


def entrada_organizacion(request, slug):
    if slug != slug.lower():
        raise Http404
    return EntradaOrganizacion.as_view()(request, slug=slug)
