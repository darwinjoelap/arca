"""Pruebas de la Fase 1. La más importante es el aislamiento: ningún usuario
ve ni modifica datos de una organización a la que no pertenece."""

from datetime import date

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.middleware import CLAVE_SESION
from core.models import RegistroAuditoria

from .models import Ejercicio, Membresia, ModeloDeOrganizacion, Organizacion, TipoMiembro
from .services import crear_organizacion, usuario_es_exclusivo

Usuario = get_user_model()
CLAVE = "clave-de-prueba-123"


def _usuario(username, **extra):
    return Usuario.objects.create_user(username=username, password=CLAVE, **extra)


class DosOrganizacionesMixin:
    """Dos organizaciones completas e independientes: A y B."""

    @classmethod
    def setUpTestData(cls):
        cls.org_a, cls.dueno_a, _ = crear_organizacion(nombre="Casa A", usuario_director="dir_a", clave=CLAVE)
        cls.org_b, cls.dueno_b, _ = crear_organizacion(nombre="Club B", usuario_director="dir_b", clave=CLAVE)
        Usuario.objects.update(debe_cambiar_clave=False)

        cls.tipo_a = TipoMiembro.objects.create(organizacion=cls.org_a, nombre="Residente", puede_registrar_egresos=True)
        cls.tipo_b = TipoMiembro.objects.create(organizacion=cls.org_b, nombre="Socio")
        cls.miembro_a = Membresia.objects.create(
            organizacion=cls.org_a, user=_usuario("ana"), tipo=cls.tipo_a, nombre_visible="Ana"
        )
        cls.miembro_b = Membresia.objects.create(
            organizacion=cls.org_b, user=_usuario("beto"), tipo=cls.tipo_b, nombre_visible="Beto"
        )
        cls.ejercicio_a = Ejercicio.objects.create(
            organizacion=cls.org_a, nombre="2026", fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31)
        )
        cls.ejercicio_b = Ejercicio.objects.create(
            organizacion=cls.org_b, nombre="2026", fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31)
        )

    def entrar(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=CLAVE))


class AislamientoTests(DosOrganizacionesMixin, TestCase):
    def test_las_listas_solo_muestran_lo_de_mi_organizacion(self):
        self.entrar("dir_a")
        r = self.client.get(reverse("organizaciones:miembro_lista"))
        self.assertContains(r, "Ana")
        self.assertNotContains(r, "Beto")
        self.assertEqual(set(r.context["miembros"]), {self.dueno_a, self.miembro_a})

        r = self.client.get(reverse("organizaciones:tipo_lista"))
        self.assertEqual(list(r.context["tipos"]), [self.tipo_a])

        r = self.client.get(reverse("organizaciones:ejercicio_lista"))
        self.assertEqual(list(r.context["ejercicios"]), [self.ejercicio_a])

    def test_pedir_por_url_un_objeto_de_otra_organizacion_da_404(self):
        self.entrar("dir_a")
        casos = [
            ("get", "organizaciones:tipo_editar", self.tipo_b.pk),
            ("post", "organizaciones:tipo_editar", self.tipo_b.pk),
            ("post", "organizaciones:tipo_eliminar", self.tipo_b.pk),
            ("get", "organizaciones:miembro_editar", self.miembro_b.pk),
            ("post", "organizaciones:miembro_editar", self.miembro_b.pk),
            ("get", "organizaciones:miembro_restablecer_clave", self.miembro_b.pk),
            ("post", "organizaciones:miembro_restablecer_clave", self.miembro_b.pk),
            ("post", "organizaciones:miembro_toggle_activa", self.miembro_b.pk),
            ("get", "organizaciones:ejercicio_editar", self.ejercicio_b.pk),
            ("post", "organizaciones:ejercicio_activar", self.ejercicio_b.pk),
            ("post", "organizaciones:ejercicio_cerrar", self.ejercicio_b.pk),
            ("post", "organizaciones:ejercicio_eliminar", self.ejercicio_b.pk),
        ]
        for metodo, nombre, pk in casos:
            with self.subTest(vista=nombre, metodo=metodo):
                respuesta = getattr(self.client, metodo)(reverse(nombre, args=[pk]), {"clave": "Otra-clave-987"})
                self.assertEqual(respuesta.status_code, 404)

        # Y nada cambió en B.
        self.miembro_b.refresh_from_db()
        self.ejercicio_b.refresh_from_db()
        self.assertTrue(self.miembro_b.activa)
        self.assertFalse(self.ejercicio_b.activo)
        self.assertFalse(self.ejercicio_b.cerrado)
        self.assertTrue(TipoMiembro.objects.filter(pk=self.tipo_b.pk).exists())
        self.assertTrue(self.miembro_b.user.check_password(CLAVE))

    def test_no_se_puede_asignar_un_tipo_de_otra_organizacion(self):
        self.entrar("dir_a")
        r = self.client.post(reverse("organizaciones:miembro_crear"), {
            "username": "carla", "nombre_visible": "Carla", "tipo": self.tipo_b.pk, "clave": "Otra-clave-987",
        })
        self.assertEqual(r.status_code, 200)  # vuelve al formulario con error
        self.assertFalse(Usuario.objects.filter(username="carla").exists())

        # Tampoco saltándose el formulario.
        with self.assertRaises(ValidationError):
            Membresia.objects.create(organizacion=self.org_a, user=_usuario("dario"), tipo=self.tipo_b)

    def test_no_se_puede_elegir_una_organizacion_ajena(self):
        self.entrar("dir_a")
        r = self.client.post(reverse("organizaciones:seleccionar"), {"organizacion": self.org_b.pk})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.session.get(CLAVE_SESION), self.org_a.pk)

    def test_una_sesion_manipulada_no_abre_otra_organizacion(self):
        self.entrar("dir_a")
        sesion = self.client.session
        sesion[CLAVE_SESION] = self.org_b.pk
        sesion.save()
        r = self.client.get(reverse("organizaciones:miembro_lista"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["organizacion_activa"], self.org_a)

    def test_la_bitacora_solo_muestra_mi_organizacion(self):
        RegistroAuditoria.objects.create(organizacion=self.org_b, accion="crear_tipo", descripcion="secreto de B")
        RegistroAuditoria.objects.create(organizacion=None, accion="cargar_tasa", descripcion="evento de plataforma")
        RegistroAuditoria.objects.create(organizacion=self.org_a, accion="crear_tipo", descripcion="cosa de A")
        self.entrar("dir_a")
        r = self.client.get(reverse("organizaciones:bitacora_lista"))
        self.assertContains(r, "cosa de A")
        self.assertNotContains(r, "secreto de B")
        self.assertNotContains(r, "evento de plataforma")

    def test_todo_modelo_de_organizacion_tiene_la_fk_protegida(self):
        """Red de seguridad para las fases siguientes: cualquier modelo nuevo
        que herede de ModeloDeOrganizacion entra aquí automáticamente."""
        modelos = [m for m in apps.get_models() if issubclass(m, ModeloDeOrganizacion)]
        self.assertGreaterEqual(len(modelos), 3)
        for modelo in modelos:
            with self.subTest(modelo=modelo.__name__):
                campo = modelo._meta.get_field("organizacion")
                self.assertFalse(campo.null)
                self.assertEqual(campo.remote_field.on_delete.__name__, "PROTECT")

    def test_el_superusuario_sin_membresia_no_entra_a_una_organizacion(self):
        Usuario.objects.create_superuser("root", password=CLAVE)
        self.entrar("root")
        r = self.client.get(reverse("organizaciones:miembro_lista"))
        self.assertRedirects(r, reverse("organizaciones:seleccionar"))
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, "Panel de plataforma")


class PermisosTests(DosOrganizacionesMixin, TestCase):
    URLS_ADMIN = [
        "organizaciones:configuracion", "organizaciones:organizacion_editar", "organizaciones:tipo_lista",
        "organizaciones:tipo_crear", "organizaciones:miembro_lista", "organizaciones:miembro_crear",
        "organizaciones:ejercicio_lista", "organizaciones:ejercicio_crear", "organizaciones:bitacora_lista",
    ]

    def test_un_miembro_comun_no_entra_a_la_configuracion(self):
        self.entrar("ana")
        for nombre in self.URLS_ADMIN:
            with self.subTest(vista=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 403)
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)

    def test_sin_sesion_redirige_al_login(self):
        for nombre in self.URLS_ADMIN:
            with self.subTest(vista=nombre):
                r = self.client.get(reverse(nombre))
                self.assertEqual(r.status_code, 302)
                self.assertIn("/cuentas/login/", r["Location"])

    def test_permisos_segun_el_tipo(self):
        self.assertTrue(self.miembro_a.tiene_permiso("puede_registrar_egresos"))
        self.assertFalse(self.miembro_a.tiene_permiso("puede_registrar_ingresos"))
        self.assertFalse(self.miembro_a.tiene_permiso("administrar"))
        self.assertFalse(self.miembro_a.tiene_permiso("permiso_inventado"))
        self.assertTrue(self.dueno_a.tiene_permiso("administrar"))
        self.assertTrue(self.dueno_a.tiene_permiso("puede_gestionar_inventario"))

    def test_tipo_inactivo_o_membresia_inactiva_quitan_los_permisos(self):
        self.tipo_a.activo = False
        self.tipo_a.save()
        self.miembro_a.refresh_from_db()
        self.assertFalse(self.miembro_a.tiene_permiso("puede_registrar_egresos"))

        self.dueno_a.activa = False
        self.assertFalse(self.dueno_a.tiene_permiso("administrar"))

    def test_membresia_desactivada_corta_el_acceso_de_inmediato(self):
        self.entrar("ana")
        self.assertEqual(self.client.get(reverse("inicio")).status_code, 200)
        Membresia.objects.filter(pk=self.miembro_a.pk).update(activa=False)
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, "Sin acceso a una organización")

    def test_organizacion_desactivada_corta_el_acceso(self):
        Organizacion.objects.filter(pk=self.org_a.pk).update(activa=False)
        self.entrar("dir_a")
        self.assertContains(self.client.get(reverse("inicio")), "Sin acceso a una organización")

    def test_el_director_no_cambia_la_visibilidad_de_cuentas(self):
        self.entrar("dir_a")
        self.client.post(reverse("organizaciones:organizacion_editar"), {
            "nombre": "Casa A", "moneda_base": "USD", "director_ve_cuentas_personales": "on", "activa": "",
        })
        self.org_a.refresh_from_db()
        self.assertFalse(self.org_a.director_ve_cuentas_personales)
        self.assertTrue(self.org_a.activa)


class MiembrosTests(DosOrganizacionesMixin, TestCase):
    def test_crear_miembro_deja_clave_temporal_y_bitacora(self):
        self.entrar("dir_a")
        r = self.client.post(reverse("organizaciones:miembro_crear"), {
            "username": "carla", "nombre_visible": "Carla Pérez", "tipo": self.tipo_a.pk, "clave": "Otra-clave-987",
        })
        self.assertRedirects(r, reverse("organizaciones:miembro_lista"))
        carla = Usuario.objects.get(username="carla")
        self.assertTrue(carla.debe_cambiar_clave)
        self.assertEqual(carla.membresias.get().organizacion, self.org_a)
        self.assertTrue(
            RegistroAuditoria.objects.filter(organizacion=self.org_a, accion="crear_miembro").exists()
        )

    def test_la_clave_temporal_obliga_a_cambiarla(self):
        Usuario.objects.filter(username="ana").update(debe_cambiar_clave=True)
        self.entrar("ana")
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("password_change"))
        r = self.client.post(reverse("password_change"), {
            "old_password": CLAVE, "new_password1": "Nueva-clave-4567", "new_password2": "Nueva-clave-4567",
        })
        self.assertRedirects(r, reverse("inicio"))
        self.assertFalse(Usuario.objects.get(username="ana").debe_cambiar_clave)

    def test_username_repetido_no_revela_de_que_organizacion_es(self):
        self.entrar("dir_a")
        r = self.client.post(reverse("organizaciones:miembro_crear"), {
            "username": "beto", "nombre_visible": "Otro Beto", "tipo": self.tipo_a.pk, "clave": "Otra-clave-987",
        })
        self.assertContains(r, "no está disponible")
        self.assertEqual(Membresia.objects.filter(user__username="beto").count(), 1)

    def test_no_se_restablece_la_clave_de_quien_pertenece_a_otra_organizacion(self):
        # Ana (de A) también es miembro de B.
        Membresia.objects.create(organizacion=self.org_b, user=self.miembro_a.user, tipo=self.tipo_b)
        self.assertFalse(usuario_es_exclusivo(self.miembro_a.user, self.org_a))
        self.entrar("dir_a")
        url = reverse("organizaciones:miembro_restablecer_clave", args=[self.miembro_a.pk])
        self.assertEqual(self.client.post(url, {"clave": "Otra-clave-987"}).status_code, 403)
        self.assertTrue(Usuario.objects.get(username="ana").check_password(CLAVE))

    def test_restablecer_clave_de_un_miembro_propio(self):
        self.entrar("dir_a")
        url = reverse("organizaciones:miembro_restablecer_clave", args=[self.miembro_a.pk])
        self.assertRedirects(self.client.post(url, {"clave": "Otra-clave-987"}), reverse("organizaciones:miembro_lista"))
        ana = Usuario.objects.get(username="ana")
        self.assertTrue(ana.check_password("Otra-clave-987"))
        self.assertTrue(ana.debe_cambiar_clave)

    def test_nadie_modifica_al_director_y_solo_el_nombra_administradores(self):
        admin_a = Membresia.objects.create(
            organizacion=self.org_a, user=_usuario("adm_a"), es_administrador=True, nombre_visible="Admin A"
        )
        self.entrar("adm_a")
        # El administrador entra a la configuración…
        self.assertEqual(self.client.get(reverse("organizaciones:miembro_lista")).status_code, 200)
        # …pero no toca al director ni a otro administrador (ni a sí mismo).
        for pk in (self.dueno_a.pk, admin_a.pk):
            for nombre in ("miembro_editar", "miembro_restablecer_clave", "miembro_toggle_activa"):
                r = self.client.post(reverse(f"organizaciones:{nombre}", args=[pk]), {"clave": "Otra-clave-987"})
                self.assertEqual(r.status_code, 403, f"{nombre} {pk}")
        # …ni asciende a nadie: el campo se ignora.
        self.client.post(reverse("organizaciones:miembro_editar", args=[self.miembro_a.pk]), {
            "nombre_visible": "Ana", "tipo": self.tipo_a.pk, "es_administrador": "on",
        })
        self.miembro_a.refresh_from_db()
        self.assertFalse(self.miembro_a.es_administrador)

        # El director sí.
        self.entrar("dir_a")
        self.client.post(reverse("organizaciones:miembro_editar", args=[self.miembro_a.pk]), {
            "nombre_visible": "Ana", "tipo": self.tipo_a.pk, "es_administrador": "on",
        })
        self.miembro_a.refresh_from_db()
        self.assertTrue(self.miembro_a.es_administrador)

    def test_desactivar_miembro_no_desactiva_al_usuario(self):
        self.entrar("dir_a")
        self.client.post(reverse("organizaciones:miembro_toggle_activa", args=[self.miembro_a.pk]))
        self.miembro_a.refresh_from_db()
        self.assertFalse(self.miembro_a.activa)
        self.assertTrue(self.miembro_a.user.is_active)

    def test_tipo_en_uso_no_se_elimina(self):
        self.entrar("dir_a")
        self.client.post(reverse("organizaciones:tipo_eliminar", args=[self.tipo_a.pk]))
        self.assertTrue(TipoMiembro.objects.filter(pk=self.tipo_a.pk).exists())

    def test_el_mismo_nombre_de_tipo_puede_existir_en_dos_organizaciones(self):
        self.entrar("dir_a")
        r = self.client.post(reverse("organizaciones:tipo_crear"), {"nombre": "Socio", "tiene_cuenta_personal": "on", "activo": "on"})
        self.assertRedirects(r, reverse("organizaciones:tipo_lista"))
        r = self.client.post(reverse("organizaciones:tipo_crear"), {"nombre": "socio", "activo": "on"})
        self.assertContains(r, "Ya existe un tipo")


class ReglasDeModeloTests(DosOrganizacionesMixin, TestCase):
    def test_un_solo_director_por_organizacion(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membresia.objects.create(organizacion=self.org_a, user=_usuario("otro"), es_dueno=True)

    def test_un_usuario_una_membresia_por_organizacion_pero_varias_organizaciones(self):
        Membresia.objects.create(organizacion=self.org_b, user=self.miembro_a.user, tipo=self.tipo_b)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membresia.objects.create(organizacion=self.org_a, user=self.miembro_a.user, tipo=self.tipo_a)

    def test_miembro_comun_necesita_tipo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membresia.objects.create(organizacion=self.org_a, user=_usuario("sintipo"))

    def test_usuario_con_dos_organizaciones_elige_y_cambia(self):
        Membresia.objects.create(organizacion=self.org_b, user=self.miembro_a.user, tipo=self.tipo_b)
        self.entrar("ana")
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("organizaciones:seleccionar"))
        self.client.post(reverse("organizaciones:seleccionar"), {"organizacion": self.org_b.pk})
        self.assertEqual(self.client.get(reverse("inicio")).context["organizacion_activa"], self.org_b)

    def test_ejercicios_un_activo_por_organizacion_y_sin_traslapes(self):
        self.entrar("dir_a")
        self.client.post(reverse("organizaciones:ejercicio_activar", args=[self.ejercicio_a.pk]))
        r = self.client.post(reverse("organizaciones:ejercicio_crear"), {
            "nombre": "2026-b", "fecha_inicio": "2026-06-01", "fecha_fin": "2027-05-31",
        })
        self.assertContains(r, "traslapan")
        r = self.client.post(reverse("organizaciones:ejercicio_crear"), {
            "nombre": "2027", "fecha_inicio": "2027-01-01", "fecha_fin": "2027-12-31",
        })
        self.assertRedirects(r, reverse("organizaciones:ejercicio_lista"))
        nuevo = Ejercicio.objects.get(organizacion=self.org_a, nombre="2027")
        self.client.post(reverse("organizaciones:ejercicio_activar", args=[nuevo.pk]))
        self.assertEqual(list(Ejercicio.objects.filter(organizacion=self.org_a, activo=True)), [nuevo])
        # El de B no se enteró.
        self.ejercicio_b.refresh_from_db()
        self.assertFalse(self.ejercicio_b.activo)


class PanelDePlataformaTests(DosOrganizacionesMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.root = Usuario.objects.create_superuser("root", password=CLAVE)

    def test_el_admin_es_solo_para_el_superusuario(self):
        self.entrar("dir_a")
        r = self.client.get("/admin/organizaciones/organizacion/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])

    def test_cambiar_la_visibilidad_queda_en_la_bitacora_de_esa_organizacion(self):
        self.entrar("root")
        url = f"/admin/organizaciones/organizacion/{self.org_a.pk}/change/"
        datos = {
            "nombre": "Casa A", "slug": self.org_a.slug, "activa": "on", "moneda_base": "USD",
            "director_ve_cuentas_personales": "on",
            "membresias-TOTAL_FORMS": "0", "membresias-INITIAL_FORMS": "0",
            "membresias-MIN_NUM_FORMS": "0", "membresias-MAX_NUM_FORMS": "1000",
        }
        r = self.client.post(url, datos)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        self.org_a.refresh_from_db()
        self.assertTrue(self.org_a.director_ve_cuentas_personales)
        registro = RegistroAuditoria.objects.get(accion="visibilidad_cuentas")
        self.assertEqual(registro.organizacion, self.org_a)
        self.assertEqual(registro.usuario, self.root)
        self.assertIn("ENCENDIDA", registro.descripcion)

        # Guardar otra vez sin cambiar el interruptor no agrega un registro.
        self.client.post(url, datos)
        self.assertEqual(RegistroAuditoria.objects.filter(accion="visibilidad_cuentas").count(), 1)

        # El director lo ve en su bitácora; el de B no.
        self.entrar("dir_a")
        self.assertContains(self.client.get(reverse("organizaciones:bitacora_lista")), "ENCENDIDA")
        self.entrar("dir_b")
        self.assertNotContains(self.client.get(reverse("organizaciones:bitacora_lista")), "ENCENDIDA")

    def test_crear_organizacion_con_usuario_existente_no_toca_su_clave(self):
        organizacion, membresia, creado = crear_organizacion(nombre="Familia C", usuario_director="ana")
        self.assertFalse(creado)
        self.assertTrue(membresia.es_dueno)
        self.assertTrue(membresia.user.check_password(CLAVE))
        self.assertEqual(organizacion.slug, "familia-c")

    def test_la_tasa_de_cambio_es_solo_del_superusuario(self):
        self.entrar("dir_a")
        self.assertEqual(self.client.get(reverse("cambio:tasa_lista")).status_code, 403)
        self.entrar("root")
        self.assertEqual(self.client.get(reverse("cambio:tasa_lista")).status_code, 200)
