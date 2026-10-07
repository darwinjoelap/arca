from django.core.management.base import BaseCommand

from cambio import bcv


class Command(BaseCommand):
    help = "Consulta la tasa del dólar en el BCV y la guarda con su fecha valor."

    def handle(self, *args, **opciones):
        try:
            tasa, estado = bcv.actualizar()
        except Exception as e:  # noqa: BLE001 - la tarea programada no debe caerse
            bcv.log.error("No se pudo actualizar la tasa BCV: %s", e)
            self.stderr.write(self.style.ERROR(f"Tasa BCV no actualizada: {e}"))
            return
        self.stdout.write(self.style.SUCCESS(f"Tasa BCV {estado}: {tasa}"))
