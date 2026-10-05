from django.urls import path

from . import views

app_name = "presupuestos"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.crear, name="crear"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/aprobar/", views.aprobar, name="aprobar"),
    path("<int:pk>/reabrir/", views.reabrir, name="reabrir"),
    path("<int:pk>/eliminar/", views.eliminar, name="eliminar"),
]
