from django.urls import path

from . import views

app_name = "personal"

urlpatterns = [
    path("", views.resumen, name="resumen"),
    path("cuenta/", views.cuenta, name="cuenta"),
    path("cuenta/ingreso/", views.movimiento_form, {"tipo": "ingreso"}, name="ingreso"),
    path("cuenta/egreso/", views.movimiento_form, {"tipo": "egreso"}, name="egreso"),
    path("cuenta/movimientos/<int:pk>/editar/", views.movimiento_form, name="movimiento_editar"),
    path("cuenta/movimientos/<int:pk>/eliminar/", views.movimiento_eliminar, name="movimiento_eliminar"),
    path("cuenta/conceptos/", views.conceptos, name="conceptos"),
    path("cuenta/conceptos/<int:pk>/eliminar/", views.concepto_eliminar, name="concepto_eliminar"),
    path("asignaciones/", views.asignaciones, name="asignaciones"),
    path("asignaciones/nueva/", views.asignacion_nueva, name="asignacion_nueva"),
    path("miembros/<int:pk>/", views.cuenta_de_miembro, name="cuenta_de_miembro"),
]
