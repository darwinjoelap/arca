"""Login por usuario dentro de una organización (misma idea que Ordo).

- En el enlace de una organización (/<slug>/) la vista deja
  `request.organizacion_login`: se busca el usuario de ESA organización.
- En la dirección principal y en /admin/ no hay organización: solo entran las
  cuentas de plataforma.
"""

from django.contrib.auth.backends import ModelBackend

from .models import Usuario, normalizar_usuario


class UsuarioPorOrganizacionBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        organizacion = getattr(request, "organizacion_login", None) if request is not None else None
        filtro = {"organizacion_cuenta": organizacion} if organizacion is not None else {"organizacion_cuenta__isnull": True}
        usuario = Usuario.objects.filter(username=normalizar_usuario(username), **filtro).first()
        if usuario is None:
            Usuario().set_password(password)   # mismo tiempo de respuesta exista o no
            return None
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
