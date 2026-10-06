from django.contrib import admin
from django.templatetags.static import static
from django.utils.functional import lazy
from django.urls import include, path
from django.views.generic import RedirectView

from core import views as core_views

urlpatterns = [
    path("salud/", core_views.salud, name="salud"),
    # Servido en la raíz (no bajo /static/) para que el scope por defecto
    # del service worker cubra todo el sitio.
    path("sw.js", core_views.service_worker, name="sw_js"),
    # Los navegadores piden /favicon.ico por su cuenta (p. ej. en /admin/).
    path("favicon.ico", RedirectView.as_view(url=lazy(static, str)("img/favicon-32.png"))),
    path("admin/", admin.site.urls),
    # Antes del include de auth: esta vista apaga `debe_cambiar_clave`.
    path("cuentas/password_change/", core_views.CambiarClaveView.as_view(), name="password_change"),
    path("cuentas/login/", core_views.EntrarPrincipal.as_view(), name="login"),
    path("cuentas/", include("django.contrib.auth.urls")),
    path("organizacion/", include("organizaciones.urls")),
    path("plataforma/", include("organizaciones.urls_plataforma")),
    path("cambio/", include("cambio.urls")),
    path("libro/", include("finanzas.urls")),
    path("personal/", include("personal.urls")),
    path("presupuestos/", include("presupuestos.urls")),
    path("reportes/", include("reportes.urls")),
    path("sync/", include("sync.urls")),
    path("", include("core.urls")),
    path("", core_views.inicio, name="inicio"),
    # Enlace propio de cada organización. Va AL FINAL para no tapar ninguna ruta de Arca
    # (y por eso los primeros segmentos de arriba están en organizaciones.services.RESERVADOS).
    path("<slug:slug>/", core_views.entrada_organizacion, name="entrada_organizacion"),
]
