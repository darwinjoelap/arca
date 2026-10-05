from django.urls import path

from . import views

app_name = "cambio"

urlpatterns = [
    path("tasas/", views.TasaCambioListView.as_view(), name="tasa_lista"),
    path("tasas/nueva/", views.TasaCambioCreateView.as_view(), name="tasa_crear"),
    path("tasas/<int:pk>/editar/", views.TasaCambioUpdateView.as_view(), name="tasa_editar"),
]
