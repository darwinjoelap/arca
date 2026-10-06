from django.urls import path

from . import views

app_name = "inventario"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("articulos/nuevo/", views.articulo_form, name="articulo_crear"),
    path("articulos/<int:pk>/", views.articulo_detalle, name="articulo_detalle"),
    path("articulos/<int:pk>/editar/", views.articulo_form, name="articulo_editar"),
    path("articulos/<int:pk>/eliminar/", views.articulo_eliminar, name="articulo_eliminar"),
    path("entrada/", views.movimiento_nuevo, {"tipo": "entrada"}, name="entrada"),
    path("salida/", views.movimiento_nuevo, {"tipo": "salida"}, name="salida"),
    path("traslado/", views.movimiento_nuevo, {"tipo": "traslado"}, name="traslado"),
    path("movimientos/", views.movimientos, name="movimientos"),
    path("movimientos/<int:pk>/anular/", views.movimiento_anular, name="movimiento_anular"),
    path("catalogos/", views.catalogos, name="catalogos"),
    path("catalogos/<str:cual>/nuevo/", views.catalogo_form, name="catalogo_crear"),
    path("catalogos/<str:cual>/<int:pk>/editar/", views.catalogo_form, name="catalogo_editar"),
    path("catalogos/<str:cual>/<int:pk>/eliminar/", views.catalogo_eliminar, name="catalogo_eliminar"),
]
