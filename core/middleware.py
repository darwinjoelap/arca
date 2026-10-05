"""Resuelve, en cada petición, en nombre de qué organización actúa el usuario.

Deja dos atributos en el request:

- `request.membresia`: la `Membresia` activa del usuario, o None.
- `request.organizacion`: su organización, o None.

Todo el aislamiento entre organizaciones parte de aquí: las vistas filtran
siempre por `request.organizacion` (ver `core/mixins.py`) y nunca aceptan
un id de organización que venga del cliente.
"""

from django.shortcuts import redirect
from django.urls import reverse

CLAVE_SESION = "organizacion_id"

# Rutas que funcionan sin organización activa. /cambio/ es de plataforma: la
# tasa es global y la maneja el superadmin, que no pertenece a ninguna.
# /sync/ contesta siempre en JSON y revisa la sesión por su cuenta: una
# redirección aquí haría creer al teléfono que el envío se guardó.
_PREFIJOS_LIBRES = (
    "/admin/", "/cuentas/", "/cambio/", "/sync/", "/static/", "/salud/", "/sw.js", "/sin-conexion/", "/favicon.ico",
)


class OrganizacionActivaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.membresia = None
        request.organizacion = None

        usuario = getattr(request, "user", None)
        if usuario is None or not usuario.is_authenticated:
            return self.get_response(request)

        libre = request.path.startswith(_PREFIJOS_LIBRES)

        # Clave temporal: no se usa el sistema hasta cambiarla.
        if usuario.debe_cambiar_clave and not libre:
            return redirect("password_change")

        self._resolver(request, usuario)

        if request.organizacion is None and not libre:
            url_seleccion = reverse("organizaciones:seleccionar")
            if request.path != url_seleccion and request.path != "/":
                return redirect(url_seleccion)

        return self.get_response(request)

    @staticmethod
    def _resolver(request, usuario):
        from organizaciones.models import Membresia

        vigentes = Membresia.objects.filter(
            user=usuario, activa=True, organizacion__activa=True
        ).select_related("organizacion", "tipo")

        organizacion_id = request.session.get(CLAVE_SESION)
        membresia = None
        if organizacion_id:
            # Se vuelve a consultar en cada petición: si desactivan la
            # membresía o la organización, el acceso se corta de inmediato.
            membresia = vigentes.filter(organizacion_id=organizacion_id).first()
            if membresia is None:
                request.session.pop(CLAVE_SESION, None)

        if membresia is None:
            candidatas = list(vigentes[:2])
            if len(candidatas) == 1:
                membresia = candidatas[0]
                request.session[CLAVE_SESION] = membresia.organizacion_id

        if membresia is not None:
            request.membresia = membresia
            request.organizacion = membresia.organizacion
