from django.urls import path

from . import plataforma as v

app_name = "plataforma"

urlpatterns = [
    path("", v.lista, name="lista"),
    path("nueva/", v.nueva, name="nueva"),
    path("<int:pk>/", v.editar, name="editar"),
    path("<int:pk>/restablecer-clave-director/", v.restablecer_clave_director, name="restablecer_clave_director"),
]
