from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("instalar/", views.instalar, name="instalar"),
    path("sin-conexion/", views.sin_conexion, name="sin_conexion"),
]
