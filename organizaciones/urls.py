from django.urls import path

from . import views, views_datos, views_tasa

app_name = "organizaciones"

urlpatterns = [
    path("seleccionar/", views.seleccionar, name="seleccionar"),
    path("configuracion/", views.configuracion, name="configuracion"),
    path("configuracion/datos/", views.organizacion_editar, name="organizacion_editar"),
    path("configuracion/tipos/", views.TipoListView.as_view(), name="tipo_lista"),
    path("configuracion/tipos/nuevo/", views.TipoCreateView.as_view(), name="tipo_crear"),
    path("configuracion/tipos/<int:pk>/editar/", views.TipoUpdateView.as_view(), name="tipo_editar"),
    path("configuracion/tipos/<int:pk>/eliminar/", views.tipo_eliminar, name="tipo_eliminar"),
    path("configuracion/miembros/", views.MiembroListView.as_view(), name="miembro_lista"),
    path("configuracion/miembros/nuevo/", views.miembro_crear, name="miembro_crear"),
    path("configuracion/miembros/<int:pk>/editar/", views.miembro_editar, name="miembro_editar"),
    path("configuracion/miembros/<int:pk>/restablecer-clave/", views.miembro_restablecer_clave, name="miembro_restablecer_clave"),
    path("configuracion/miembros/<int:pk>/dar-acceso/", views.miembro_dar_acceso, name="miembro_dar_acceso"),
    path("configuracion/miembros/<int:pk>/activar-desactivar/", views.miembro_toggle_activa, name="miembro_toggle_activa"),
    path("configuracion/ejercicios/", views.EjercicioListView.as_view(), name="ejercicio_lista"),
    path("configuracion/ejercicios/nuevo/", views.EjercicioCreateView.as_view(), name="ejercicio_crear"),
    path("configuracion/ejercicios/<int:pk>/editar/", views.EjercicioUpdateView.as_view(), name="ejercicio_editar"),
    path("configuracion/ejercicios/<int:pk>/activar/", views.ejercicio_activar, name="ejercicio_activar"),
    path("configuracion/ejercicios/<int:pk>/cerrar/", views.ejercicio_cerrar, name="ejercicio_cerrar"),
    path("configuracion/ejercicios/<int:pk>/eliminar/", views.ejercicio_eliminar, name="ejercicio_eliminar"),
    path("configuracion/tasa/", views_tasa.inicio, name="tasa"),
    path("configuracion/tasa/<int:pk>/corregir/", views_tasa.corregir, name="tasa_corregir"),
    path("configuracion/tasa/<int:pk>/eliminar/", views_tasa.eliminar, name="tasa_eliminar"),
    path("configuracion/datos-excel/", views_datos.inicio, name="datos"),
    path("configuracion/datos-excel/exportar/", views_datos.exportar, name="datos_exportar"),
    path("configuracion/datos-excel/plantilla/", views_datos.plantilla, name="datos_plantilla"),
    path("configuracion/datos-excel/cargar/", views_datos.cargar, name="datos_cargar"),
    path("configuracion/bitacora/", views.BitacoraListView.as_view(), name="bitacora_lista"),
]
