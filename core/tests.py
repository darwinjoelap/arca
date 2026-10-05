from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from organizaciones.services import crear_organizacion

from .models import RegistroAuditoria

Usuario = get_user_model()
CLAVE = "clave-de-prueba-123"


class PaginasBasicasTests(TestCase):
    def test_salud_no_usa_base_de_datos(self):
        with self.assertNumQueries(0):
            self.assertEqual(self.client.get("/salud/").content, b"ok")

    def test_service_worker_y_sin_conexion(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r["Content-Type"])
        self.assertContains(r, "arca-shell")
        self.assertEqual(self.client.get(reverse("core:sin_conexion")).status_code, 200)

    def test_login_se_muestra(self):
        self.assertContains(self.client.get(reverse("login")), "Iniciar sesión")


class BitacoraDeLoginTests(TestCase):
    def test_login_se_anota_en_la_organizacion_del_usuario(self):
        organizacion, _, _ = crear_organizacion(nombre="Casa A", usuario_director="dir_a", clave=CLAVE)
        self.client.post(reverse("login"), {"username": "dir_a", "password": CLAVE})
        registro = RegistroAuditoria.objects.get(accion="login")
        self.assertEqual(registro.organizacion, organizacion)

    def test_login_fallido_queda_como_evento_de_plataforma(self):
        self.client.post(reverse("login"), {"username": "nadie", "password": "x"})
        registro = RegistroAuditoria.objects.get(accion="login_fallido")
        self.assertIsNone(registro.organizacion)
        self.assertIn("nadie", registro.descripcion)
