from django.urls import path

from . import views, views_cierre as cierre

app_name = "finanzas"

urlpatterns = [
    path("", views.MovimientoListView.as_view(), name="movimiento_lista"),
    path("ingreso/nuevo/", views.movimiento_registrar, {"tipo": "ingreso"}, name="ingreso_registrar"),
    path("egreso/nuevo/", views.movimiento_registrar, {"tipo": "egreso"}, name="egreso_registrar"),
    path("movimientos/<int:pk>/", views.movimiento_detalle, name="movimiento_detalle"),
    path("movimientos/<int:pk>/aprobar/", views.movimiento_aprobar, name="movimiento_aprobar"),
    path("movimientos/<int:pk>/anular/", views.movimiento_anular, name="movimiento_anular"),
    path("traslados/", views.TrasladoListView.as_view(), name="traslado_lista"),
    path("traslados/nuevo/", views.traslado_registrar, name="traslado_registrar"),
    path("traslados/<int:pk>/anular/", views.traslado_anular, name="traslado_anular"),
    path("arqueos/", cierre.arqueos, name="arqueo_lista"),
    path("arqueos/nuevo/", cierre.arqueo_nuevo, name="arqueo_nuevo"),
    path("arqueos/<int:pk>/", cierre.arqueo_detalle, name="arqueo_detalle"),
    path("arqueos/<int:pk>/ajustar/", cierre.arqueo_ajustar, name="arqueo_ajustar"),
    path("anticipos/", cierre.anticipos, name="anticipo_lista"),
    path("anticipos/nuevo/", cierre.anticipo_nuevo, name="anticipo_nuevo"),
    path("anticipos/<int:pk>/", cierre.anticipo_detalle, name="anticipo_detalle"),
    path("anticipos/<int:pk>/rendir/", cierre.anticipo_rendir, name="anticipo_rendir"),
    path("anticipos/<int:pk>/anular/", cierre.anticipo_anular, name="anticipo_anular"),
    path("cuotas/", views.cuotas, name="cuota_lista"),
    path("cuotas/nueva/", views.CuotaCreateView.as_view(), name="cuota_crear"),
    path("cuotas/<int:pk>/editar/", views.CuotaUpdateView.as_view(), name="cuota_editar"),
    path("cuotas/<int:pk>/eliminar/", views.cuota_eliminar, name="cuota_eliminar"),
    path("cajas/", views.cajas, name="caja_lista"),
    path("cajas/nueva/", views.CajaCreateView.as_view(), name="caja_crear"),
    path("cajas/<int:pk>/editar/", views.CajaUpdateView.as_view(), name="caja_editar"),
    path("cajas/<int:pk>/eliminar/", views.caja_eliminar, name="caja_eliminar"),
    path("cuentas/nueva/", views.CuentaCreateView.as_view(), name="cuenta_crear"),
    path("cuentas/<int:pk>/editar/", views.CuentaUpdateView.as_view(), name="cuenta_editar"),
    path("cuentas/<int:pk>/eliminar/", views.cuenta_eliminar, name="cuenta_eliminar"),
    path("conceptos/", views.ConceptoListView.as_view(), name="concepto_lista"),
    path("conceptos/nuevo/", views.ConceptoCreateView.as_view(), name="concepto_crear"),
    path("conceptos/<int:pk>/editar/", views.ConceptoUpdateView.as_view(), name="concepto_editar"),
    path("conceptos/<int:pk>/eliminar/", views.concepto_eliminar, name="concepto_eliminar"),
]
