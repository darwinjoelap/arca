from django.urls import path

from . import views

app_name = "reportes"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("analisis/", views.analisis, name="analisis"),
    path("comprobante/<int:pk>/", views.comprobante, name="comprobante"),
    path("presupuesto/<int:pk>/", views.presupuesto, name="presupuesto"),
    path("<slug:clave>/", views.reporte, name="reporte"),
]
