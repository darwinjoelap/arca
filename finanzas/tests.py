"""Pruebas del libro de caja (Fase 3, parte 1)."""

import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cambio.models import TasaCambio
from core.models import RegistroAuditoria
from organizaciones.models import Ejercicio, Membresia, Organizacion, TipoMiembro
from organizaciones.services import crear_organizacion

from .models import Caja, Concepto, Cuenta, Movimiento
from .services import registrar_movimiento, resumen_saldos, saldo_cuenta, totales_periodo

Usuario = get_user_model()
CLAVE = "clave-de-prueba-123"
D = Decimal


class LibroMixin:
    """Organización A completa (caja, dos cuentas, conceptos, tres tipos de
    miembro) y una organización B mínima para las pruebas de aislamiento."""

    @classmethod
    def setUpTestData(cls):
        cls.hoy = timezone.localdate()
        cls.root = Usuario.objects.create_superuser("root", password=CLAVE)
        cls.tasa = TasaCambio.objects.create(fecha=cls.hoy, valor=D("100"), fuente="bcv", cargada_por=cls.root)

        cls.org, cls.director, _ = crear_organizacion(nombre="Casa A", usuario_director="dir_a", clave=CLAVE)
        cls.org_b, cls.director_b, _ = crear_organizacion(nombre="Club B", usuario_director="dir_b", clave=CLAVE)
        Usuario.objects.update(debe_cambiar_clave=False)

        anio = dict(fecha_inicio=date(cls.hoy.year, 1, 1), fecha_fin=date(cls.hoy.year, 12, 31), activo=True)
        cls.ejercicio = Ejercicio.objects.create(organizacion=cls.org, nombre=str(cls.hoy.year), **anio)
        cls.ejercicio_b = Ejercicio.objects.create(organizacion=cls.org_b, nombre=str(cls.hoy.year), **anio)

        cls.caja = Caja.objects.create(organizacion=cls.org, nombre="Casa")
        cls.usd = Cuenta.objects.create(organizacion=cls.org, caja=cls.caja, nombre="Efectivo", moneda="USD", saldo_inicial=D("50"))
        cls.ves = Cuenta.objects.create(organizacion=cls.org, caja=cls.caja, nombre="Banco", moneda="VES", tipo="banco")
        cls.c_ingreso = Concepto.objects.create(organizacion=cls.org, tipo="ingreso", nombre="Aportes")
        cls.c_egreso = Concepto.objects.create(organizacion=cls.org, tipo="egreso", nombre="Comida")

        cls.caja_b = Caja.objects.create(organizacion=cls.org_b, nombre="Club")
        cls.cuenta_b = Cuenta.objects.create(organizacion=cls.org_b, caja=cls.caja_b, nombre="Caja chica", moneda="USD")
        cls.concepto_b = Concepto.objects.create(organizacion=cls.org_b, tipo="egreso", nombre="Canchas")

        def miembro(username, **permisos):
            tipo = TipoMiembro.objects.create(organizacion=cls.org, nombre=f"Tipo {username}", **permisos)
            return Membresia.objects.create(
                organizacion=cls.org, user=Usuario.objects.create_user(username, password=CLAVE),
                tipo=tipo, nombre_visible=username.title(),
            )

        cls.tesorero = miembro("tesorero", puede_registrar_ingresos=True, puede_registrar_egresos=True, puede_ver_movimientos=True)
        cls.comprador = miembro("comprador", puede_registrar_egresos=True)
        cls.residente = miembro("residente")

    def entrar(self, username):
        self.client.logout()
        self.assertTrue(self.client.login(username=username, password=CLAVE))

    def mov(self, tipo="egreso", monto="10", cuenta=None, membresia=None, concepto="auto", org=None, **extra):
        cuenta = cuenta or self.usd
        if concepto == "auto":
            concepto = self.c_ingreso if tipo == "ingreso" else self.c_egreso
        m = Movimiento(
            organizacion=org or self.org, tipo=tipo, fecha=extra.pop("fecha", self.hoy), cuenta=cuenta,
            concepto=concepto, monto=D(monto), **extra,
        )
        return registrar_movimiento(m, membresia=membresia or self.director)[0]

    def datos_form(self, **cambios):
        datos = {
            "fecha": self.hoy.isoformat(), "cuenta": self.usd.pk, "concepto": self.c_egreso.pk,
            "descripcion": "", "monto": "25.50", "miembro": "", "tercero": "", "referencia": "",
            "uuid_cliente": str(uuid.uuid4()),
        }
        datos.update(cambios)
        return datos


class SaldosTests(LibroMixin, TestCase):
    def test_saldo_de_cuenta_es_inicial_mas_ingresos_menos_egresos(self):
        self.mov("ingreso", "100")
        self.mov("egreso", "30.25")
        self.assertEqual(saldo_cuenta(self.usd), D("119.75"))
        self.assertEqual(saldo_cuenta(self.ves), D("0"))

    def test_el_movimiento_toma_la_moneda_de_su_cuenta_y_congela_los_equivalentes(self):
        m = self.mov("ingreso", "2500", cuenta=self.ves)
        self.assertEqual(m.moneda, "VES")
        self.assertEqual(m.caja, self.caja)
        self.assertEqual(m.tasa_aplicada, D("100"))
        self.assertEqual((m.monto_ves, m.monto_usd), (D("2500"), D("25")))

    def test_anulados_y_por_aprobar_no_cuentan(self):
        self.org.requiere_aprobacion_egresos = True
        self.org.save()
        pendiente = self.mov("egreso", "20", membresia=self.comprador)
        confirmado = self.mov("egreso", "5")
        self.assertEqual(pendiente.estado, "registrado")
        self.assertEqual(saldo_cuenta(self.usd), D("45"))
        pendiente.transicionar("confirmado", self.director.user)
        self.assertEqual(saldo_cuenta(self.usd), D("25"))
        confirmado.transicionar("anulado", self.director.user, motivo="Duplicado")
        self.assertEqual(saldo_cuenta(self.usd), D("30"))

    def test_resumen_convierte_los_saldos_con_la_tasa_vigente(self):
        self.mov("ingreso", "5000", cuenta=self.ves)  # Bs. 5000 = $50 a tasa 100
        resumen = resumen_saldos(self.org, self.tasa)
        self.assertTrue(resumen["convertible"])
        self.assertEqual(resumen["usd"], D("100"))      # 50 inicial + 50
        self.assertEqual(resumen["ves"], D("10000"))    # 5000 + 50*100
        self.assertEqual(len(resumen["cajas"]), 1)
        self.assertEqual(len(resumen["cajas"][0]["cuentas"]), 2)

    def test_resumen_sin_tasa_no_mezcla_monedas(self):
        self.mov("ingreso", "5000", cuenta=self.ves)
        resumen = resumen_saldos(self.org, None)
        self.assertFalse(resumen["convertible"])
        self.assertEqual((resumen["usd"], resumen["ves"]), (D("50"), D("5000")))

    def test_totales_del_periodo_usan_el_equivalente_congelado(self):
        self.mov("ingreso", "40")
        self.mov("egreso", "1000", cuenta=self.ves)
        # La tasa cambia después: lo ya confirmado no se mueve (D-09).
        self.tasa.valor = D("200")
        self.tasa.save()
        t = totales_periodo(self.org, self.hoy.replace(day=1), self.hoy)
        self.assertEqual(t["ingreso"]["usd"], D("40"))
        self.assertEqual(t["egreso"]["usd"], D("10"))
        self.assertEqual(t["egreso"]["ves"], D("1000"))

    def test_corregir_la_tasa_recalcula_solo_lo_que_espera_aprobacion(self):
        self.org.requiere_aprobacion_egresos = True
        self.org.save()
        pendiente = self.mov("egreso", "1000", cuenta=self.ves, membresia=self.comprador)
        confirmado = self.mov("egreso", "1000", cuenta=self.ves)
        self.tasa.valor = D("200")
        self.tasa.save()
        pendiente.refresh_from_db()
        confirmado.refresh_from_db()
        self.assertEqual(pendiente.monto_usd, D("5"))
        self.assertEqual(confirmado.monto_usd, D("10"))
        self.assertTrue(self.tasa.tiene_transacciones())


class ReglasTests(LibroMixin, TestCase):
    def test_vale_correlativo_por_caja_y_ejercicio(self):
        otra = Caja.objects.create(organizacion=self.org, nombre="Grupo")
        cuenta_otra = Cuenta.objects.create(organizacion=self.org, caja=otra, nombre="Efectivo", moneda="USD")
        numeros = [self.mov().numero_vale, self.mov("ingreso").numero_vale, self.mov(cuenta=cuenta_otra).numero_vale]
        self.assertEqual(numeros, [1, 2, 1])

    def test_sin_concepto_la_descripcion_es_obligatoria(self):
        with self.assertRaises(ValidationError):
            self.mov(concepto=None)
        libre = self.mov(concepto=None, descripcion="Taxi al aeropuerto")
        self.assertEqual(libre.titulo, "Taxi al aeropuerto")

    def test_concepto_del_tipo_equivocado_o_de_otra_caja_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self.mov("ingreso", concepto=self.c_egreso)
        otra = Caja.objects.create(organizacion=self.org, nombre="Grupo")
        solo_grupo = Concepto.objects.create(organizacion=self.org, tipo="egreso", nombre="Retiro", caja=otra)
        with self.assertRaises(ValidationError):
            self.mov(concepto=solo_grupo)

    def test_fecha_fuera_de_un_ejercicio_abierto_se_rechaza(self):
        with self.assertRaises(ValidationError):
            self.mov(fecha=date(self.hoy.year - 3, 6, 1))
        self.ejercicio.cerrado = True
        self.ejercicio.activo = False
        self.ejercicio.save()
        with self.assertRaises(ValidationError):
            self.mov()

    def test_sin_ninguna_tasa_no_se_registra(self):
        TasaCambio.objects.all().delete()
        with self.assertRaises(ValidationError):
            self.mov()

    def test_usa_la_ultima_tasa_anterior_si_no_hay_una_del_dia(self):
        TasaCambio.objects.all().delete()
        vieja = TasaCambio.objects.create(
            fecha=date(self.hoy.year, 1, 1), valor=D("80"), fuente="manual", cargada_por=self.root
        )
        self.assertEqual(self.mov().tasa, vieja)

    def test_transiciones(self):
        m = self.mov()
        with self.assertRaises(ValidationError):
            m.transicionar("anulado", self.director.user, motivo="  ")
        m.transicionar("anulado", self.director.user, motivo="Error de monto")
        self.assertEqual(m.motivo_anulacion, "Error de monto")
        with self.assertRaises(ValidationError):
            m.transicionar("confirmado", self.director.user)

    def test_uuid_repetido_devuelve_el_original(self):
        clave = uuid.uuid4()
        primero = self.mov(uuid_cliente=clave)
        segundo = self.mov(uuid_cliente=clave, monto="999")
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(Movimiento.objects.count(), 1)

    def test_la_moneda_de_una_cuenta_con_movimientos_no_cambia(self):
        self.mov()
        self.usd.moneda = "VES"
        with self.assertRaises(ValidationError):
            self.usd.full_clean()

    def test_conceptos_solo_dos_niveles(self):
        hijo = Concepto.objects.create(organizacion=self.org, tipo="egreso", nombre="Mercado", padre=self.c_egreso)
        nieto = Concepto(organizacion=self.org, tipo="egreso", nombre="Verduras", padre=hijo)
        with self.assertRaises(ValidationError):
            nieto.full_clean()
        cruzado = Concepto(organizacion=self.org, tipo="ingreso", nombre="Raro", padre=self.c_egreso)
        with self.assertRaises(ValidationError):
            cruzado.full_clean()


class VistasTests(LibroMixin, TestCase):
    def test_registrar_egreso_desde_el_formulario(self):
        self.entrar("tesorero")
        r = self.client.post(reverse("finanzas:egreso_registrar"), self.datos_form(miembro=self.residente.pk))
        m = Movimiento.objects.get()
        self.assertRedirects(r, reverse("finanzas:movimiento_detalle", args=[m.pk]))
        self.assertEqual((m.tipo, m.monto, m.estado), ("egreso", D("25.50"), "confirmado"))
        self.assertEqual(m.registrado_por, self.tesorero.user)
        self.assertEqual(m.miembro, self.residente)
        self.assertTrue(RegistroAuditoria.objects.filter(organizacion=self.org, accion="registrar_movimiento").exists())

    def test_reenviar_el_mismo_formulario_no_duplica(self):
        self.entrar("tesorero")
        datos = self.datos_form()
        self.client.post(reverse("finanzas:egreso_registrar"), datos)
        self.client.post(reverse("finanzas:egreso_registrar"), datos)
        self.assertEqual(Movimiento.objects.count(), 1)
        self.assertEqual(RegistroAuditoria.objects.filter(accion="registrar_movimiento").count(), 1)

    def test_el_tipo_lo_fija_la_url_no_el_formulario(self):
        self.entrar("tesorero")
        self.client.post(reverse("finanzas:ingreso_registrar"), self.datos_form(concepto=self.c_ingreso.pk, tipo="egreso"))
        self.assertEqual(Movimiento.objects.get().tipo, "ingreso")

    def test_permisos_para_registrar(self):
        casos = [("comprador", "finanzas:ingreso_registrar", 403), ("comprador", "finanzas:egreso_registrar", 200),
                 ("residente", "finanzas:egreso_registrar", 403), ("residente", "finanzas:movimiento_lista", 403),
                 ("tesorero", "finanzas:ingreso_registrar", 200), ("dir_a", "finanzas:ingreso_registrar", 200)]
        for usuario, vista, esperado in casos:
            with self.subTest(usuario=usuario, vista=vista):
                self.entrar(usuario)
                self.assertEqual(self.client.get(reverse(vista)).status_code, esperado)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("finanzas:movimiento_lista")).status_code, 302)

    def test_quien_solo_registra_ve_solo_lo_suyo(self):
        del_tesorero = self.mov(membresia=self.tesorero, concepto=None, descripcion="Compra del tesorero")
        del_comprador = self.mov(membresia=self.comprador, concepto=None, descripcion="Compra del comprador")
        self.entrar("comprador")
        r = self.client.get(reverse("finanzas:movimiento_lista"))
        self.assertContains(r, "Compra del comprador")
        self.assertNotContains(r, "Compra del tesorero")
        self.assertEqual(self.client.get(reverse("finanzas:movimiento_detalle", args=[del_tesorero.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("finanzas:movimiento_detalle", args=[del_comprador.pk])).status_code, 200)
        self.entrar("tesorero")
        self.assertContains(self.client.get(reverse("finanzas:movimiento_lista")), "Compra del comprador")

    def test_aprobacion_de_egresos(self):
        self.org.requiere_aprobacion_egresos = True
        self.org.save()
        self.entrar("comprador")
        self.client.post(reverse("finanzas:egreso_registrar"), self.datos_form())
        m = Movimiento.objects.get()
        self.assertEqual(m.estado, "registrado")
        # Quien registra no aprueba ni anula.
        self.assertEqual(self.client.post(reverse("finanzas:movimiento_aprobar", args=[m.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("finanzas:movimiento_anular", args=[m.pk]), {"motivo": "x"}).status_code, 403)
        self.entrar("dir_a")
        self.client.post(reverse("finanzas:movimiento_aprobar", args=[m.pk]))
        m.refresh_from_db()
        self.assertEqual((m.estado, m.aprobado_por), ("confirmado", self.director.user))
        # Un ingreso nunca espera aprobación; un egreso del director tampoco.
        self.assertEqual(self.mov("ingreso", membresia=self.tesorero).estado, "confirmado")
        self.assertEqual(self.mov("egreso").estado, "confirmado")

    def test_anular_exige_motivo_y_queda_en_bitacora(self):
        m = self.mov()
        self.entrar("dir_a")
        url = reverse("finanzas:movimiento_anular", args=[m.pk])
        self.assertEqual(self.client.post(url, {"motivo": ""}).status_code, 200)
        self.assertEqual(Movimiento.objects.get().estado, "confirmado")
        self.client.post(url, {"motivo": "Se registró dos veces"})
        self.assertEqual(Movimiento.objects.get().estado, "anulado")
        registro = RegistroAuditoria.objects.get(accion="anular_movimiento")
        self.assertIn("Se registró dos veces", registro.descripcion)

    def test_panel_muestra_saldos_solo_a_quien_ve_el_libro(self):
        self.mov("ingreso", "100")
        self.entrar("dir_a")
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, "Fondos disponibles")
        self.assertContains(r, "$ 150,00")
        self.assertEqual(r.context["saldos"]["usd"], D("150"))
        for usuario in ("comprador", "residente"):
            self.entrar(usuario)
            r = self.client.get(reverse("inicio"))
            self.assertNotContains(r, "Fondos disponibles")
            self.assertNotIn("saldos", r.context)

    def test_ajustar_el_saldo_inicial_queda_en_bitacora(self):
        self.entrar("dir_a")
        self.client.post(reverse("finanzas:cuenta_editar", args=[self.usd.pk]), {
            "caja": self.caja.pk, "nombre": "Efectivo", "tipo": "efectivo", "moneda": "USD",
            "banco": "", "saldo_inicial": "80", "activa": "on",
        })
        self.usd.refresh_from_db()
        self.assertEqual(self.usd.saldo_inicial, D("80"))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="ajustar_saldo_cuenta", organizacion=self.org).exists())

    def test_catalogos_solo_para_quien_administra(self):
        self.entrar("tesorero")
        for vista in ("finanzas:caja_lista", "finanzas:caja_crear", "finanzas:cuenta_crear",
                      "finanzas:concepto_lista", "finanzas:concepto_crear"):
            with self.subTest(vista=vista):
                self.assertEqual(self.client.get(reverse(vista)).status_code, 403)
        self.entrar("dir_a")
        r = self.client.post(reverse("finanzas:concepto_crear"), {"tipo": "egreso", "nombre": "Luz", "padre": "", "caja": "", "activo": "on"})
        self.assertRedirects(r, reverse("finanzas:concepto_lista"))
        r = self.client.post(reverse("finanzas:concepto_crear"), {"tipo": "egreso", "nombre": "luz", "padre": "", "caja": "", "activo": "on"})
        self.assertContains(r, "Ya existe un concepto")

    def test_caja_con_movimientos_no_se_elimina(self):
        self.mov()
        self.entrar("dir_a")
        self.client.post(reverse("finanzas:cuenta_eliminar", args=[self.usd.pk]))
        self.client.post(reverse("finanzas:caja_eliminar", args=[self.caja.pk]))
        self.assertTrue(Cuenta.objects.filter(pk=self.usd.pk).exists())
        self.assertTrue(Caja.objects.filter(pk=self.caja.pk).exists())


class AislamientoLibroTests(LibroMixin, TestCase):
    def setUp(self):
        self.mov_b = self.mov(cuenta=self.cuenta_b, concepto=self.concepto_b, org=self.org_b,
                              membresia=self.director_b, monto="777")

    def test_no_veo_movimientos_ni_saldos_de_otra_organizacion(self):
        self.entrar("dir_a")
        r = self.client.get(reverse("finanzas:movimiento_lista"))
        self.assertEqual(list(r.context["movimientos"]), [])
        self.assertNotContains(r, "777")
        r = self.client.get(reverse("inicio"))
        self.assertEqual(r.context["saldos"]["usd"], D("50"))
        self.assertNotContains(r, "Caja chica")
        self.assertNotContains(self.client.get(reverse("finanzas:caja_lista")), "Club")

    def test_urls_con_objetos_de_otra_organizacion_dan_404(self):
        self.entrar("dir_a")
        casos = [
            ("get", "finanzas:movimiento_detalle", self.mov_b.pk), ("post", "finanzas:movimiento_aprobar", self.mov_b.pk),
            ("post", "finanzas:movimiento_anular", self.mov_b.pk), ("get", "finanzas:caja_editar", self.caja_b.pk),
            ("post", "finanzas:caja_eliminar", self.caja_b.pk), ("get", "finanzas:cuenta_editar", self.cuenta_b.pk),
            ("post", "finanzas:cuenta_eliminar", self.cuenta_b.pk), ("get", "finanzas:concepto_editar", self.concepto_b.pk),
            ("post", "finanzas:concepto_eliminar", self.concepto_b.pk),
        ]
        for metodo, vista, pk in casos:
            with self.subTest(vista=vista):
                r = getattr(self.client, metodo)(reverse(vista, args=[pk]), {"motivo": "x"})
                self.assertEqual(r.status_code, 404)
        self.mov_b.refresh_from_db()
        self.assertEqual(self.mov_b.estado, "confirmado")

    def test_el_formulario_no_acepta_cuenta_concepto_ni_miembro_ajenos(self):
        self.entrar("dir_a")
        for cambio in ({"cuenta": self.cuenta_b.pk}, {"concepto": self.concepto_b.pk}, {"miembro": self.director_b.pk}):
            with self.subTest(cambio=cambio):
                r = self.client.post(reverse("finanzas:egreso_registrar"), self.datos_form(**cambio))
                self.assertEqual(r.status_code, 200)
        self.assertEqual(Movimiento.objects.filter(organizacion=self.org).count(), 0)

    def test_ni_saltandose_el_formulario(self):
        with self.assertRaises(ValidationError):
            self.mov(cuenta=self.cuenta_b)
        with self.assertRaises(ValidationError):
            Cuenta.objects.create(organizacion=self.org, caja=self.caja_b, nombre="Colada", moneda="USD")
        with self.assertRaises(ValidationError):
            Concepto.objects.create(organizacion=self.org, tipo="egreso", nombre="Colado", caja=self.caja_b)

    def test_el_mismo_uuid_en_dos_organizaciones_son_dos_movimientos(self):
        clave = uuid.uuid4()
        a = self.mov(uuid_cliente=clave)
        b = self.mov(cuenta=self.cuenta_b, concepto=self.concepto_b, org=self.org_b, membresia=self.director_b, uuid_cliente=clave)
        self.assertNotEqual(a.pk, b.pk)
