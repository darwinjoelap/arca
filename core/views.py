from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone

from cambio.services import SinTasaError, obtener_tasa
from organizaciones.models import Ejercicio, Membresia

from .auditoria import registrar
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
    """Panel principal. Por ahora muestra el contexto de la organización; los
    saldos y accesos de ingreso/egreso entran con el libro de caja (Fase 3)."""
    organizacion = request.organizacion
    if organizacion is None:
        tiene_varias = Membresia.objects.filter(
            user=request.user, activa=True, organizacion__activa=True
        ).exists()
        if tiene_varias:
            return redirect("organizaciones:seleccionar")
        # Sin ninguna organización: el superadmin ve el acceso a la plataforma;
        # cualquier otro, un aviso de que su acceso está desactivado.
        return render(request, "core/sin_organizacion.html")

    try:
        tasa, tasa_exacta = obtener_tasa(timezone.localdate())
    except SinTasaError:
        tasa, tasa_exacta = None, False

    contexto = {
        "ejercicio_activo": Ejercicio.objects.filter(organizacion=organizacion, activo=True).first(),
        "tasa": tasa,
        "tasa_exacta": tasa_exacta,
        "total_miembros": Membresia.objects.filter(organizacion=organizacion, activa=True).count(),
    }
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
