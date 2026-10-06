"""Pruebas de la Fase 1. La más importante es el aislamiento: ningún usuario
ve ni modifica datos de una organización a la que no pertenece."""

from datetime import date, timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

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
        # force_login: el login real va por el enlace de cada organización (ver EntradaTests).
        self.client.logout()
        self.client.force_login(Usuario.objects.get(username=username))


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
            "username": "carla", "nombre_visible": "Carla", "tipo": self.tipo_b.pk, "clave": "Otra-clave-987", "con_acceso": "on",
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
        self.assertRedirects(r, reverse("organizaciones:seleccionar"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("plataforma:lista"))


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
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, "Acceso suspendido")
        self.assertContains(r, "Casa A")
        self.assertEqual(self.client.get(reverse("finanzas:movimiento_lista"), follow=True).redirect_chain[-1][0], reverse("inicio"))

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
            "username": "carla", "nombre_visible": "Carla Pérez", "tipo": self.tipo_a.pk, "con_acceso": "on",
        })
        clave = r.context["clave"]
        self.assertRegex(clave, r"^Arca-[A-Za-z2-9]{10}$")
        self.assertContains(r, clave)
        self.assertEqual(r["Cache-Control"], "no-store")
        carla = Usuario.objects.get(username="carla")
        self.assertTrue(carla.check_password(clave))
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

    def test_el_mismo_usuario_puede_existir_en_dos_organizaciones(self):
        """«beto» ya existe en B; A puede crear su propio «beto». Dentro de A no se repite."""
        self.entrar("dir_a")
        datos = {"username": "Beto", "nombre_visible": "Otro Beto", "tipo": self.tipo_a.pk, "con_acceso": "on"}
        r = self.client.post(reverse("organizaciones:miembro_crear"), datos)
        self.assertIn("clave", r.context)
        self.assertEqual(Usuario.objects.filter(username="beto").count(), 2)      # se guarda en minúsculas
        self.assertEqual(Usuario.objects.get(username="beto", organizacion_cuenta=self.org_a).membresias.get().organizacion, self.org_a)
        r = self.client.post(reverse("organizaciones:miembro_crear"), datos)
        self.assertContains(r, "Ya hay alguien con ese usuario")
        self.assertEqual(Usuario.objects.filter(username="beto").count(), 2)

    def test_una_cuenta_no_cruza_a_otra_organizacion(self):
        with self.assertRaises(ValidationError):
            Membresia.objects.create(organizacion=self.org_b, user=self.miembro_a.user, tipo=self.tipo_b)
        self.assertTrue(usuario_es_exclusivo(self.miembro_a.user, self.org_a))
        self.assertFalse(usuario_es_exclusivo(self.miembro_a.user, self.org_b))
        root = Usuario.objects.create_superuser("root", password=CLAVE)
        self.assertFalse(usuario_es_exclusivo(root, self.org_a))
        with self.assertRaises(ValidationError):
            Membresia.objects.create(organizacion=self.org_a, user=root, es_administrador=True)

    def test_restablecer_clave_de_un_miembro_propio(self):
        self.entrar("dir_a")
        url = reverse("organizaciones:miembro_restablecer_clave", args=[self.miembro_a.pk])
        self.assertNotContains(self.client.get(url), "Arca-")     # ver la pantalla no cambia nada
        self.assertTrue(Usuario.objects.get(username="ana").check_password(CLAVE))
        r = self.client.post(url)
        ana = Usuario.objects.get(username="ana")
        self.assertTrue(ana.check_password(r.context["clave"]))
        self.assertFalse(ana.check_password(CLAVE))
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

    def test_un_usuario_una_sola_membresia(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membresia.objects.create(organizacion=self.org_a, user=self.miembro_a.user, tipo=self.tipo_a)

    def test_miembro_comun_necesita_tipo(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membresia.objects.create(organizacion=self.org_a, user=_usuario("sintipo"))

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
            "nombre": "Casa A", "slug": self.org_a.slug, "activa": "on", "moneda_base": "USD", "plan": "prueba",
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

    def test_crear_organizacion_crea_un_director_propio_aunque_el_nombre_exista_en_otra(self):
        organizacion, membresia, _ = crear_organizacion(nombre="Familia C", usuario_director="ana", clave="Arca-temporal1")
        self.assertTrue(membresia.es_dueno)
        self.assertEqual(membresia.user.organizacion_cuenta, organizacion)
        self.assertNotEqual(membresia.user, self.miembro_a.user)
        self.assertTrue(self.miembro_a.user.check_password(CLAVE))       # la «ana» de A no se toca
        self.assertEqual(organizacion.slug, "familia-c")

    def test_la_tasa_de_cambio_es_solo_del_superusuario(self):
        self.entrar("dir_a")
        self.assertEqual(self.client.get(reverse("cambio:tasa_lista")).status_code, 403)
        self.entrar("root")
        self.assertEqual(self.client.get(reverse("cambio:tasa_lista")).status_code, 200)


class MiembrosSinAccesoTests(DosOrganizacionesMixin, TestCase):
    """Gente de la comunidad que aporta o recibe pero no entra al sistema."""

    def crear(self, **datos):
        self.entrar("dir_a")
        return self.client.post(reverse("organizaciones:miembro_crear"), {"tipo": self.tipo_a.pk, **datos})

    def test_se_crea_sin_usuario_ni_clave(self):
        antes = Usuario.objects.count()
        r = self.crear(nombre_visible="Doña Rosa")
        self.assertRedirects(r, reverse("organizaciones:miembro_lista"))
        rosa = Membresia.objects.get(nombre_visible="Doña Rosa")
        self.assertIsNone(rosa.user)
        self.assertFalse(rosa.tiene_acceso)
        self.assertEqual((rosa.nombre, rosa.usuario_texto), ("Doña Rosa", "sin acceso"))
        self.assertEqual(Usuario.objects.count(), antes)
        self.assertContains(self.client.get(reverse("organizaciones:miembro_lista")), "Sin acceso")

    def test_varios_sin_usuario_conviven_en_la_misma_organizacion(self):
        self.crear(nombre_visible="Uno")
        self.crear(nombre_visible="Dos")
        self.assertEqual(Membresia.objects.filter(organizacion=self.org_a, user__isnull=True).count(), 2)

    def test_sin_usuario_exige_nombre_y_no_puede_administrar(self):
        with self.assertRaises(ValidationError):
            Membresia(organizacion=self.org_a, tipo=self.tipo_a).full_clean()
        with self.assertRaises(ValidationError):
            Membresia(organizacion=self.org_a, nombre_visible="X", es_administrador=True).full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Membresia.objects.create(organizacion=self.org_a, tipo=self.tipo_a)  # sin nombre
        r = self.crear(nombre_visible="Jefe", es_administrador="on")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Membresia.objects.filter(nombre_visible="Jefe").exists())

    def test_con_acceso_sigue_exigiendo_usuario_y_clave(self):
        r = self.crear(nombre_visible="Pedro", con_acceso="on")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Escribe el nombre de usuario")
        self.assertFalse(Membresia.objects.filter(nombre_visible="Pedro").exists())

    def test_dar_acceso_despues_conserva_el_mismo_registro(self):
        self.crear(nombre_visible="Doña Rosa")
        rosa = Membresia.objects.get(nombre_visible="Doña Rosa")
        url = reverse("organizaciones:miembro_dar_acceso", args=[rosa.pk])
        r = self.client.post(url, {"username": "rosa"})
        clave = r.context["clave"]                       # se muestra una sola vez, sin redirigir
        self.assertContains(r, f"/{self.org_a.slug}/")
        self.assertContains(r, clave)
        rosa.refresh_from_db()
        self.assertEqual(rosa.user.username, "rosa")
        self.assertTrue(rosa.user.debe_cambiar_clave)
        self.assertTrue(RegistroAuditoria.objects.filter(accion="dar_acceso", organizacion=self.org_a).exists())
        self.client.logout()
        self.client.post(f"/{self.org_a.slug}/", {"username": "rosa", "password": clave})
        self.assertEqual(self.client.session["_auth_user_id"], str(rosa.user_id))
        # Ya con acceso, no se le da otra vez.
        self.entrar("dir_a")
        self.client.post(url, {"username": "rosa2", "clave": "Otra-clave-987"})
        self.assertFalse(Usuario.objects.filter(username="rosa2").exists())

    def test_dar_acceso_no_cruza_de_organizacion(self):
        ajeno = Membresia.objects.create(organizacion=self.org_b, tipo=self.tipo_b, nombre_visible="De B")
        self.entrar("dir_a")
        url = reverse("organizaciones:miembro_dar_acceso", args=[ajeno.pk])
        self.assertEqual(self.client.post(url, {"username": "intruso", "clave": "Otra-clave-987"}).status_code, 404)
        self.assertFalse(Usuario.objects.filter(username="intruso").exists())

    def test_restablecer_clave_de_quien_no_tiene_acceso_lleva_a_darselo(self):
        self.crear(nombre_visible="Doña Rosa")
        rosa = Membresia.objects.get(nombre_visible="Doña Rosa")
        r = self.client.get(reverse("organizaciones:miembro_restablecer_clave", args=[rosa.pk]))
        self.assertRedirects(r, reverse("organizaciones:miembro_dar_acceso", args=[rosa.pk]))


class SuscripcionTests(DosOrganizacionesMixin, TestCase):
    """Panel /plataforma/: alta, plan, vencimiento, límite y suspensión."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.root = Usuario.objects.create_superuser("root", password=CLAVE)

    def datos(self, **extra):
        base = {"nombre": "Casa A", "slug": self.org_a.slug, "moneda_base": "USD", "plan": "basico", "activa": "on"}
        base.update(extra)
        return base

    def test_solo_el_superusuario_entra(self):
        urls = [reverse("plataforma:lista"), reverse("plataforma:nueva"), reverse("plataforma:editar", args=[self.org_b.pk])]
        self.entrar("dir_a")
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.post(reverse("plataforma:restablecer_clave_director", args=[self.org_b.pk])).status_code, 403)
        self.entrar("root")
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_alta_muestra_la_clave_una_vez_y_el_director_debe_cambiarla(self):
        self.entrar("root")
        r = self.client.post(reverse("plataforma:nueva"), {
            "nombre": "Club Nuevo", "moneda_base": "USD", "plan": "pro", "activa_hasta": "2030-01-01",
            "limite_usuarios": "5", "usuario_director": "dir_nuevo", "nombre_director": "Nora",
        })
        clave = r.context["clave"]
        self.assertContains(r, clave)
        org = Organizacion.objects.get(nombre="Club Nuevo")
        self.assertEqual((org.plan, org.limite_usuarios, str(org.activa_hasta)), ("pro", 5, "2030-01-01"))
        director = org.director
        self.assertTrue(director.es_dueno and director.user.debe_cambiar_clave and director.user.check_password(clave))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="crear_organizacion", organizacion=org, usuario=self.root).exists())
        # Con la clave temporal no pasa de la pantalla de cambio.
        self.client.logout()
        self.assertContains(r, f"/{org.slug}/")
        self.assertRedirects(self.client.post(f"/{org.slug}/", {"username": "dir_nuevo", "password": clave}), "/",
                             fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("inicio")), reverse("password_change"))

    def test_el_enlace_se_valida(self):
        self.entrar("root")
        base = {"nombre": "Otra", "moneda_base": "USD", "plan": "prueba", "usuario_director": "dir_otra"}
        for malo, mensaje in [("admin", "reservado"), (self.org_a.slug, "ya lo usa"), ("Con Espacios", "letras minúsculas")]:
            r = self.client.post(reverse("plataforma:nueva"), {**base, "slug": malo})
            self.assertContains(r, mensaje)
        self.assertFalse(Organizacion.objects.filter(nombre="Otra").exists())
        r = self.client.post(reverse("plataforma:nueva"), {**base, "slug": "la-otra"})
        self.assertContains(r, "/la-otra/")
        # Sin escribirlo, sale del nombre y esquiva los reservados.
        self.client.post(reverse("plataforma:nueva"), {**base, "nombre": "Admin", "usuario_director": "x"})
        self.assertEqual(Organizacion.objects.get(nombre="Admin").slug, "admin-2")

    def test_vencida_corta_el_acceso_y_renovar_lo_devuelve(self):
        ayer = timezone.localdate() - timedelta(days=1)
        Organizacion.objects.filter(pk=self.org_a.pk).update(activa_hasta=ayer)
        self.entrar("dir_a")
        self.assertContains(self.client.get(reverse("inicio")), "Acceso suspendido")
        self.entrar("root")
        self.client.post(reverse("plataforma:editar", args=[self.org_a.pk]),
                         self.datos(activa_hasta=str(timezone.localdate() + timedelta(days=30))))
        registro = RegistroAuditoria.objects.get(accion="editar_suscripcion")
        self.assertEqual(registro.organizacion, self.org_a)
        self.assertIn("activa_hasta", registro.descripcion)
        self.entrar("dir_a")
        self.assertEqual(self.client.get(reverse("organizaciones:miembro_lista")).status_code, 200)

    def test_suspender_desde_la_plataforma(self):
        self.entrar("root")
        datos = self.datos()
        del datos["activa"]
        self.client.post(reverse("plataforma:editar", args=[self.org_a.pk]), datos)
        self.org_a.refresh_from_db()
        self.assertFalse(self.org_a.activa)
        self.assertEqual(self.org_a.estado_texto, "Suspendida")

    def test_el_limite_de_usuarios_frena_altas_pero_no_miembros_sin_acceso(self):
        Organizacion.objects.filter(pk=self.org_a.pk).update(limite_usuarios=self.org_a.usuarios_con_acceso())
        self.entrar("dir_a")
        url = reverse("organizaciones:miembro_crear")
        r = self.client.post(url, {"username": "carla", "nombre_visible": "Carla", "tipo": self.tipo_a.pk, "con_acceso": "on"})
        self.assertContains(r, "El plan de la organización permite")
        self.assertFalse(Usuario.objects.filter(username="carla").exists())
        self.client.post(url, {"nombre_visible": "Doña Rosa", "tipo": self.tipo_a.pk})
        rosa = Membresia.objects.get(nombre_visible="Doña Rosa")
        r = self.client.post(reverse("organizaciones:miembro_dar_acceso", args=[rosa.pk]), {"username": "rosa"})
        self.assertContains(r, "El plan de la organización permite")
        # Reactivar a alguien con acceso también cuenta.
        Membresia.objects.filter(pk=self.miembro_a.pk).update(activa=False)
        Organizacion.objects.filter(pk=self.org_a.pk).update(limite_usuarios=1)
        self.client.post(reverse("organizaciones:miembro_toggle_activa", args=[self.miembro_a.pk]))
        self.miembro_a.refresh_from_db()
        self.assertFalse(self.miembro_a.activa)

    def test_la_plataforma_restablece_la_clave_del_director(self):
        self.entrar("root")
        r = self.client.post(reverse("plataforma:restablecer_clave_director", args=[self.org_a.pk]))
        dir_a = Usuario.objects.get(username="dir_a")
        self.assertTrue(dir_a.check_password(r.context["clave"]) and dir_a.debe_cambiar_clave)
        self.assertTrue(RegistroAuditoria.objects.filter(accion="restablecer_clave", organizacion=self.org_a, usuario=self.root).exists())

    def test_la_plataforma_no_muestra_dinero(self):
        self.entrar("root")
        self.assertEqual(self.client.get(reverse("finanzas:movimiento_lista"), follow=True).redirect_chain[-1][0], reverse("plataforma:lista"))


class EntradaTests(DosOrganizacionesMixin, TestCase):
    """Cada organización entra por su enlace, con sus propios usuarios."""

    def entrar_por(self, org, username, clave=CLAVE):
        return self.client.post(f"/{org.slug}/", {"username": username, "password": clave})

    def test_el_enlace_muestra_el_nombre_de_la_organizacion(self):
        self.assertContains(self.client.get(f"/{self.org_a.slug}/"), "Casa A")
        self.assertEqual(self.client.get("/no-existe/").status_code, 404)
        self.assertEqual(self.client.get(f"/{self.org_a.slug.upper()}/").status_code, 404)

    def test_se_entra_solo_por_el_enlace_propio(self):
        self.assertRedirects(self.entrar_por(self.org_a, "ANA"), "/", fetch_redirect_response=False)   # sin distinguir mayúsculas
        self.assertEqual(self.client.get(reverse("inicio")).context["organizacion_activa"], self.org_a)
        self.client.logout()
        for intento in (self.entrar_por(self.org_b, "ana"),                                       # enlace de otra
                        self.client.post(reverse("login"), {"username": "ana", "password": CLAVE})):  # dirección principal
            self.assertEqual(intento.status_code, 200)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_dos_organizaciones_con_el_mismo_usuario_no_se_mezclan(self):
        beto_a = Usuario.objects.create_user("beto", password="Clave-de-A-123", organizacion_cuenta=self.org_a)
        Membresia.objects.create(organizacion=self.org_a, user=beto_a, tipo=self.tipo_a)
        self.entrar_por(self.org_a, "beto", "Clave-de-A-123")
        self.assertEqual(self.client.session["_auth_user_id"], str(beto_a.pk))
        self.client.logout()
        self.entrar_por(self.org_b, "beto", "Clave-de-A-123")          # la clave de A no abre el «beto» de B
        self.assertNotIn("_auth_user_id", self.client.session)
        self.entrar_por(self.org_b, "beto")
        self.assertEqual(self.client.session["_auth_user_id"], str(self.miembro_b.user_id))

    def test_la_plataforma_entra_por_la_direccion_principal(self):
        Usuario.objects.create_superuser("root", password=CLAVE)
        self.entrar_por(self.org_a, "root")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.post(reverse("login"), {"username": "root", "password": CLAVE}), "/",
                             fetch_redirect_response=False)

    def test_el_equipo_recuerda_su_organizacion(self):
        self.entrar_por(self.org_a, "ana")
        # «Cerrar sesión» de verdad (client.logout() borraría también la cookie del equipo).
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"), fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse("login")), f"/{self.org_a.slug}/")
        self.assertEqual(self.client.get(reverse("login") + "?plataforma").status_code, 200)

    def test_suspendida_no_muestra_el_login(self):
        Organizacion.objects.filter(pk=self.org_a.pk).update(activa=False)
        r = self.client.get(f"/{self.org_a.slug}/")
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "suspendido", status_code=403)

    def test_login_fallido_se_anota_en_la_organizacion_del_enlace(self):
        self.entrar_por(self.org_a, "ana", "mala")
        self.assertEqual(RegistroAuditoria.objects.get(accion="login_fallido").organizacion, self.org_a)
