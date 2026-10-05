from django.urls import path

from . import views

app_name = "sync"

urlpatterns = [
    path("api/movimiento/", views.api_movimiento, name="api_movimiento"),
]
