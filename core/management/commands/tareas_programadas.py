"""Tareas periódicas de Arca. En Railway: un servicio Cron con este comando
(ver docs/DESPLIEGUE.md). Hoy solo actualiza la tasa; aquí se suman las demás."""

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ejecuta las tareas periódicas (tasa BCV)."

    def handle(self, *args, **opciones):
        call_command("actualizar_tasa_bcv", stdout=self.stdout, stderr=self.stderr)
