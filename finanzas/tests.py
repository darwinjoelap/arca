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

from .models import Anticipo, Arqueo, Caja, Concepto, Cuenta, Movimiento, Traslado
from .services import registrar_movimiento, registrar_traslado, resumen_saldos, saldo_cuenta, totales_periodo

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
        # force_login: el login real va por el enlace de cada organización (ver EntradaTests).
        self.client.logout()
        self.client.force_login(Usuario.objects.get(username=username))

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


class TrasladosTests(LibroMixin, TestCase):
    def tras(self, origen, destino, monto, recibido=None, org=None, usuario=None, **extra):
        t = Traslado(
            organizacion=org or self.org, fecha=self.hoy, cuenta_origen=origen, cuenta_destino=destino,
            monto_origen=D(monto), monto_destino=D(recibido) if recibido else None, **extra,
        )
        return registrar_traslado(t, usuario=usuario or self.director.user)[0]

    def test_misma_moneda_mueve_el_mismo_monto_y_no_es_ingreso_ni_egreso(self):
        otra = Cuenta.objects.create(organizacion=self.org, caja=self.caja, nombre="Caja fuerte", moneda="USD")
        t = self.tras(self.usd, otra, "20", recibido="999")  # lo escrito se ignora: misma moneda
        self.assertEqual(t.monto_destino, D("20"))
        self.assertEqual((saldo_cuenta(self.usd), saldo_cuenta(otra)), (D("30"), D("20")))
        totales = totales_periodo(self.org, self.hoy.replace(day=1), self.hoy)
        self.assertEqual((totales["ingreso"]["usd"], totales["egreso"]["usd"]), (D("0"), D("0")))
        # El total de la organización no cambia.
        self.assertEqual(resumen_saldos(self.org, self.tasa)["usd"], D("50"))

    def test_cambio_de_moneda_usa_lo_recibido_o_la_tasa_del_dia(self):
        self.tras(self.usd, self.ves, "10")                    # tasa 100 -> Bs. 1000
        self.assertEqual(saldo_cuenta(self.ves), D("1000"))
        t = self.tras(self.usd, self.ves, "10", recibido="1250")  # se cambió en la calle a 125
        self.assertEqual(saldo_cuenta(self.ves), D("2250"))
        self.assertEqual(saldo_cuenta(self.usd), D("30"))
        self.assertEqual(t.tasa_implicita, D("125"))

    def test_anular_devuelve_los_saldos(self):
        t = self.tras(self.usd, self.ves, "10")
        with self.assertRaises(ValidationError):
            t.anular(self.director.user, " ")
        t.anular(self.director.user, "Me equivoqué de cuenta")
        self.assertEqual((saldo_cuenta(self.usd), saldo_cuenta(self.ves)), (D("50"), D("0")))
        with self.assertRaises(ValidationError):
            t.anular(self.director.user, "otra vez")

    def test_reglas(self):
        with self.assertRaises(ValidationError):
            self.tras(self.usd, self.usd, "5")
        with self.assertRaises(ValidationError):
            self.tras(self.usd, self.ves, "0")
        with self.assertRaises(ValidationError):
            self.tras(self.usd, self.cuenta_b, "5")
        clave = uuid.uuid4()
        a = self.tras(self.usd, self.ves, "5", uuid_cliente=clave)
        b = self.tras(self.usd, self.ves, "5", uuid_cliente=clave)
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Traslado.objects.count(), 1)

    def test_sin_tasa_el_cambio_de_moneda_exige_el_monto_recibido(self):
        TasaCambio.objects.all().delete()
        with self.assertRaises(ValidationError):
            self.tras(self.usd, self.ves, "10")
        self.assertEqual(self.tras(self.usd, self.ves, "10", recibido="1300").monto_destino, D("1300"))

    def test_vistas_solo_para_quien_administra(self):
        self.entrar("tesorero")
        for vista in ("finanzas:traslado_lista", "finanzas:traslado_registrar"):
            self.assertEqual(self.client.get(reverse(vista)).status_code, 403)
        self.entrar("dir_a")
        datos = {"fecha": self.hoy.isoformat(), "cuenta_origen": self.usd.pk, "cuenta_destino": self.ves.pk,
                 "monto_origen": "10", "monto_recibido": "", "descripcion": "Cambio", "referencia": "",
                 "uuid_cliente": str(uuid.uuid4())}
        r = self.client.post(reverse("finanzas:traslado_registrar"), datos)
        self.assertRedirects(r, reverse("finanzas:traslado_lista"))
        self.client.post(reverse("finanzas:traslado_registrar"), datos)  # doble envío
        t = Traslado.objects.get()
        self.assertEqual(t.monto_destino, D("1000"))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="registrar_traslado", organizacion=self.org).exists())
        self.assertContains(self.client.get(reverse("finanzas:traslado_lista")), "Cambio")
        self.client.post(reverse("finanzas:traslado_anular", args=[t.pk]), {"motivo": "Prueba"})
        t.refresh_from_db()
        self.assertEqual(t.estado, "anulado")
        self.assertTrue(RegistroAuditoria.objects.filter(accion="anular_traslado").exists())

    def test_aislamiento(self):
        otra_b = Cuenta.objects.create(organizacion=self.org_b, caja=self.caja_b, nombre="Banco B", moneda="USD")
        ajeno = self.tras(self.cuenta_b, otra_b, "7", org=self.org_b, usuario=self.director_b.user)
        self.entrar("dir_a")
        self.assertEqual(list(self.client.get(reverse("finanzas:traslado_lista")).context["traslados"]), [])
        url = reverse("finanzas:traslado_anular", args=[ajeno.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"motivo": "x"}).status_code, 404)
        r = self.client.post(reverse("finanzas:traslado_registrar"), {
            "fecha": self.hoy.isoformat(), "cuenta_origen": self.usd.pk, "cuenta_destino": otra_b.pk, "monto_origen": "5",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Traslado.objects.filter(organizacion=self.org).count(), 0)


class PanelPorCajaTests(LibroMixin, TestCase):
    def test_con_una_caja_no_hay_desglose_y_con_dos_cada_una_muestra_lo_suyo(self):
        self.mov(tipo="ingreso", monto="100")
        self.entrar("dir_a")
        self.assertNotIn("por_caja", self.client.get(reverse("inicio")).context)
        obra = Caja.objects.create(organizacion=self.org, nombre="Obra social")
        cuenta_obra = Cuenta.objects.create(organizacion=self.org, caja=obra, nombre="Efectivo obra", moneda="USD")
        self.mov(tipo="ingreso", monto="40", cuenta=cuenta_obra)
        self.mov(tipo="egreso", monto="15", cuenta=cuenta_obra)
        r = self.client.get(reverse("inicio"))
        por_caja = {b["caja"].nombre: b for b in r.context["por_caja"]}
        self.assertEqual(por_caja["Obra social"]["usd"], D("25"))
        self.assertEqual((por_caja["Obra social"]["mes"]["ingreso"]["usd"], por_caja["Obra social"]["mes"]["egreso"]["usd"]), (D("40"), D("15")))
        self.assertEqual(r.context["saldos"]["usd"], sum(b["usd"] for b in por_caja.values()))
        self.assertContains(r, "todas las cajas")
        self.assertEqual([v["clave"] for v in r.context["vistas"]], ["todas", f"caja-{self.caja.pk}", f"caja-{obra.pk}"])
        vista_obra = r.context["vistas"][-1]
        self.assertEqual({m.caja_id for m in vista_obra["ultimos"]}, {obra.pk})
        self.assertContains(r, "Disponible en Obra social")
        # El enlace de la tarjeta filtra el libro por esa caja.
        lista = self.client.get(reverse("finanzas:movimiento_lista"), {"caja": obra.pk})
        self.assertEqual({m.caja_id for m in lista.context["object_list"]}, {obra.pk})


class ArqueoTests(LibroMixin, TestCase):
    def test_cuadra_sobrante_y_faltante_con_ajuste(self):
        self.mov(tipo="ingreso", monto="30")                      # saldo: 50 + 30 = 80
        self.entrar("dir_a")
        url = reverse("finanzas:arqueo_nuevo")
        r = self.client.post(url, {"cuenta": self.usd.pk, "fecha": str(self.hoy), "contado": "80"}, follow=True)
        self.assertContains(r, "No hay nada que ajustar")
        cuadra = Arqueo.objects.get()
        self.assertTrue(cuadra.cuadra)
        self.client.post(reverse("finanzas:arqueo_ajustar", args=[cuadra.pk]))
        self.assertIsNone(Arqueo.objects.get(pk=cuadra.pk).ajuste)

        self.client.post(url, {"cuenta": self.usd.pk, "fecha": str(self.hoy), "contado": "73.50", "nota": "faltó un billete"})
        faltante = Arqueo.objects.order_by("-pk").first()
        self.assertEqual((faltante.saldo_sistema, faltante.diferencia), (D("80"), D("-6.50")))
        self.client.post(reverse("finanzas:arqueo_ajustar", args=[faltante.pk]))
        faltante.refresh_from_db()
        self.assertEqual((faltante.ajuste.tipo, faltante.ajuste.monto, faltante.ajuste.estado), ("egreso", D("6.50"), "confirmado"))
        self.assertEqual(saldo_cuenta(self.usd), D("73.50"))        # el sistema quedó igual a lo contado
        self.client.post(reverse("finanzas:arqueo_ajustar", args=[faltante.pk]))   # dos veces no duplica
        self.assertEqual(Movimiento.objects.filter(descripcion__startswith="Faltante").count(), 1)
        self.assertEqual(faltante.saldo_sistema, D("80"))            # el arqueo guarda la foto de ese día

        self.client.post(url, {"cuenta": self.usd.pk, "fecha": str(self.hoy), "contado": "75"})
        sobrante = Arqueo.objects.order_by("-pk").first()
        self.client.post(reverse("finanzas:arqueo_ajustar", args=[sobrante.pk]))
        self.assertEqual(Arqueo.objects.get(pk=sobrante.pk).ajuste.tipo, "ingreso")
        self.assertEqual(saldo_cuenta(self.usd), D("75"))
        self.assertEqual(RegistroAuditoria.objects.filter(accion="registrar_arqueo").count(), 3)
        self.assertEqual(RegistroAuditoria.objects.filter(accion="ajustar_arqueo").count(), 2)

    def test_solo_administra_y_no_cruza_organizaciones(self):
        self.entrar("tesorero")
        for nombre in ("finanzas:arqueo_lista", "finanzas:arqueo_nuevo", "finanzas:anticipo_lista", "finanzas:anticipo_nuevo"):
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 403, nombre)
        self.entrar("dir_a")
        r = self.client.post(reverse("finanzas:arqueo_nuevo"), {"cuenta": self.cuenta_b.pk, "fecha": str(self.hoy), "contado": "1"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Arqueo.objects.exists())
        ajeno = services_arqueo(self.org_b, self.cuenta_b, self.director_b.user, self.hoy)
        self.assertEqual(self.client.get(reverse("finanzas:arqueo_detalle", args=[ajeno.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("finanzas:arqueo_ajustar", args=[ajeno.pk])).status_code, 404)
        r = self.client.post(reverse("finanzas:arqueo_nuevo"), {"cuenta": self.usd.pk, "fecha": "2999-01-01", "contado": "1"})
        self.assertContains(r, "fecha futura")


def services_arqueo(org, cuenta, usuario, fecha):
    from .services import registrar_arqueo
    return registrar_arqueo(organizacion=org, cuenta=cuenta, contado=D("5"), fecha=fecha, nota="", usuario=usuario)


class AnticipoTests(LibroMixin, TestCase):
    def entregar(self, monto="40", **extra):
        datos = {"cuenta": self.usd.pk, "fecha": str(self.hoy), "monto": monto, "miembro": self.comprador.pk, "motivo": "Mercado"}
        datos.update(extra)
        return self.client.post(reverse("finanzas:anticipo_nuevo"), datos)

    def test_entregar_rendir_y_devolver(self):
        self.entrar("dir_a")
        self.entregar()
        a = Anticipo.objects.get()
        self.assertEqual((a.estado, a.entrega.estado, a.entrega.concepto_id), ("pendiente", "confirmado", None))
        self.assertEqual(saldo_cuenta(self.usd), D("10"))             # 50 - 40: el dinero ya salió
        luz = Concepto.objects.create(organizacion=self.org, tipo="egreso", nombre="Luz")
        r = self.client.post(reverse("finanzas:anticipo_rendir", args=[a.pk]), {
            "fecha": str(self.hoy), "concepto_0": self.c_egreso.pk, "monto_0": "25", "concepto_2": luz.pk, "monto_2": "7.50",
            "descripcion_2": "Recibo de octubre"})
        self.assertRedirects(r, reverse("finanzas:anticipo_detalle", args=[a.pk]))
        a.refresh_from_db()
        self.assertEqual((a.estado, a.gastado, a.devuelto, a.entrega.estado), ("rendido", D("32.50"), D("7.50"), "anulado"))
        gastos = list(a.gastos.order_by("pk"))
        self.assertEqual([(g.concepto, g.monto, g.miembro, g.estado) for g in gastos],
                         [(self.c_egreso, D("25"), self.comprador, "confirmado"), (luz, D("7.50"), self.comprador, "confirmado")])
        self.assertEqual(saldo_cuenta(self.usd), D("17.50"))          # 50 - 32,50: lo que sobró volvió
        self.assertContains(self.client.get(reverse("finanzas:anticipo_detalle", args=[a.pk])), "volvió a la cuenta")
        # Rendido, no se rinde ni se anula otra vez.
        self.client.post(reverse("finanzas:anticipo_rendir", args=[a.pk]), {"fecha": str(self.hoy), "monto_0": "1", "descripcion_0": "x"})
        self.client.post(reverse("finanzas:anticipo_anular", args=[a.pk]), {"motivo": "x"})
        self.assertEqual((Anticipo.objects.get().estado, a.gastos.count()), ("rendido", 2))
        for accion in ("entregar_anticipo", "rendir_anticipo"):
            self.assertTrue(RegistroAuditoria.objects.filter(accion=accion, organizacion=self.org).exists(), accion)

    def test_gasto_de_mas_sin_gasto_y_validaciones(self):
        self.entrar("dir_a")
        self.assertContains(self.entregar(monto="500"), "no tiene saldo suficiente")
        self.assertContains(self.entregar(miembro=""), "Indica a quién")
        self.assertFalse(Anticipo.objects.exists())
        self.entregar(monto="20", miembro="", tercero="Sr. Pérez")
        a = Anticipo.objects.get()
        self.assertEqual(a.responsable, "Sr. Pérez")
        url = reverse("finanzas:anticipo_rendir", args=[a.pk])
        self.assertContains(self.client.post(url, {"fecha": str(self.hoy), "monto_0": "5"}), "Elige un concepto o escribe el detalle")
        self.assertContains(self.client.post(url, {"fecha": str(self.hoy), "descripcion_0": "Taxi"}), "Falta el monto")
        self.assertEqual(Anticipo.objects.get().estado, "pendiente")
        self.client.post(url, {"fecha": str(self.hoy), "descripcion_0": "Taxi", "monto_0": "26"})
        a.refresh_from_db()
        self.assertEqual((a.gastado, a.devuelto), (D("26"), D("-6")))   # gastó de más: se le repone
        self.assertEqual(saldo_cuenta(self.usd), D("24"))
        self.entregar(monto="10")
        b = Anticipo.objects.order_by("-pk").first()
        self.client.post(reverse("finanzas:anticipo_rendir", args=[b.pk]), {"fecha": str(self.hoy)})   # no gastó nada
        b.refresh_from_db()
        self.assertEqual((b.estado, b.gastado, b.gastos.count()), ("rendido", D("0"), 0))
        self.assertEqual(saldo_cuenta(self.usd), D("24"))

    def test_anular_y_proteccion_del_egreso_provisional(self):
        self.entrar("dir_a")
        self.entregar()
        a = Anticipo.objects.get()
        r = self.client.post(reverse("finanzas:movimiento_anular", args=[a.entrega.pk]), {"motivo": "desde el libro"})
        self.assertRedirects(r, reverse("finanzas:anticipo_detalle", args=[a.pk]))
        self.assertEqual(Movimiento.objects.get(pk=a.entrega.pk).estado, "confirmado")
        self.client.post(reverse("finanzas:anticipo_anular", args=[a.pk]), {"motivo": "no viajó"})
        a.refresh_from_db()
        self.assertEqual((a.estado, a.entrega.estado), ("anulado", "anulado"))
        self.assertEqual(saldo_cuenta(self.usd), D("50"))
        self.assertEqual(self.client.get(reverse("finanzas:anticipo_lista"), {"estado": "anulado"}).context["anticipos"][0], a)
        ajeno_url = reverse("finanzas:anticipo_detalle", args=[a.pk])
        self.entrar("dir_b")
        self.assertEqual(self.client.get(ajeno_url).status_code, 404)


class AvisosYExportacionTests(LibroMixin, TestCase):
    def test_cuotas_en_excel_y_pdf(self):
        from .models import CuotaMiembro
        CuotaMiembro.objects.create(organizacion=self.org, membresia=self.residente, concepto=self.c_ingreso,
                                    monto=D("10"), moneda="USD", vigente_desde=date(self.hoy.year, 1, 1))
        self.entrar("dir_a")
        self.assertContains(self.client.get(reverse("finanzas:cuota_lista")), "?formato=xlsx")
        excel = self.client.get(reverse("finanzas:cuota_lista"), {"formato": "xlsx"})
        self.assertEqual(excel.status_code, 200)
        self.assertIn("spreadsheetml", excel["Content-Type"])
        pdf = self.client.get(reverse("finanzas:cuota_lista"), {"formato": "pdf"})
        self.assertEqual(pdf["Content-Type"], "application/pdf")

    def test_el_panel_avisa_anticipos_e_inventario(self):
        from inventario import services as inv
        from inventario.models import Articulo, MovimientoInventario, Ubicacion
        from .services import entregar_anticipo
        director = Membresia.objects.get(organizacion=self.org, es_dueno=True)
        self.entrar("dir_a")
        respuesta = self.client.get(reverse("inicio"))
        self.assertNotContains(respuesta, "por rendir")
        self.assertNotContains(respuesta, "en el mínimo")
        entregar_anticipo(organizacion=self.org, cuenta=self.usd, monto=D("20"), fecha=self.hoy, motivo="Compras",
                          miembro=self.comprador, tercero="", membresia=director)
        cloro = Articulo.objects.create(organizacion=self.org, clase="consumible", nombre="Cloro", minimo=D("5"))
        lugar = Ubicacion.objects.create(organizacion=self.org, nombre="Depósito")
        inv.registrar(MovimientoInventario(organizacion=self.org, articulo=cloro, tipo="entrada", motivo="inicial",
                                           cantidad=D("3"), destino=lugar), usuario=director.user)
        respuesta = self.client.get(reverse("inicio"))
        self.assertContains(respuesta, "1 anticipo por rendir")
        self.assertContains(respuesta, "1 consumible en el mínimo")
        # Quien no administra ni lleva inventario no ve ninguno de los dos.
        self.entrar("residente")
        respuesta = self.client.get(reverse("inicio"))
        self.assertNotContains(respuesta, "por rendir")
        self.assertNotContains(respuesta, "en el mínimo")
