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
        self.client.post(f"/{organizacion.slug}/", {"username": "dir_a", "password": CLAVE})
        registro = RegistroAuditoria.objects.get(accion="login")
        self.assertEqual(registro.organizacion, organizacion)

    def test_login_fallido_queda_como_evento_de_plataforma(self):
        self.client.post(reverse("login"), {"username": "nadie", "password": "x"})
        registro = RegistroAuditoria.objects.get(accion="login_fallido")
        self.assertIsNone(registro.organizacion)
        self.assertIn("nadie", registro.descripcion)


class AsegurarSuperadminTests(TestCase):
    def correr(self, **entorno):
        from io import StringIO
        from unittest import mock

        from django.core.management import call_command

        salida = StringIO()
        with mock.patch.dict("os.environ", entorno, clear=False):
            call_command("asegurar_superadmin", stdout=salida)
        return salida.getvalue()

    def test_crea_uno_solo_y_no_toca_al_que_existe(self):
        import os
        for nombre in ("ARCA_ADMIN_USUARIO", "ARCA_ADMIN_CLAVE"):
            os.environ.pop(nombre, None)
        self.assertIn("faltan", self.correr())
        self.assertIn("al menos 12", self.correr(ARCA_ADMIN_USUARIO="Soporte", ARCA_ADMIN_CLAVE="corta"))
        self.assertFalse(Usuario.objects.filter(is_superuser=True).exists())
        self.correr(ARCA_ADMIN_USUARIO="Soporte", ARCA_ADMIN_CLAVE="Una-clave-larga-1")
        admin = Usuario.objects.get(is_superuser=True)
        self.assertEqual((admin.username, admin.organizacion_cuenta, admin.debe_cambiar_clave), ("soporte", None, True))
        self.assertTrue(admin.check_password("Una-clave-larga-1"))
        # Segundo arranque, incluso con otra clave en la variable: no cambia nada.
        self.assertIn("no se hace nada", self.correr(ARCA_ADMIN_USUARIO="otro", ARCA_ADMIN_CLAVE="Otra-clave-larga-2"))
        self.assertEqual(Usuario.objects.filter(is_superuser=True).count(), 1)
        self.assertTrue(Usuario.objects.get(is_superuser=True).check_password("Una-clave-larga-1"))
        # Entra por la dirección principal y debe cambiar la clave.
        self.client.post(reverse("login"), {"username": "soporte", "password": "Una-clave-larga-1"})
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("password_change"))
