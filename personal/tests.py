"""Cuotas, asignaciones, cuenta personal y «Mi resumen».

Lo más delicado aquí es la privacidad: la cuenta personal es de su dueño, y el
director solo la abre si el superadmin lo permitió para esa organización."""

from datetime import date
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import RegistroAuditoria
from finanzas.models import Concepto, CuotaMiembro, Movimiento
from finanzas.services import estado_cuotas, saldo_cuenta
from organizaciones.models import Membresia, Organizacion
from presupuestos.tests import PresupuestoMixin

from . import services
from .models import ConceptoPersonal, MovimientoPersonal


class PersonalMixin(PresupuestoMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # `residente` tiene cuenta personal (es el valor por defecto del tipo); el comprador no.
        tipo = cls.comprador.tipo
        tipo.tiene_cuenta_personal = False
        tipo.save()
        cls.rosa = Membresia.objects.create(organizacion=cls.org, tipo=cls.residente.tipo, nombre_visible="Doña Rosa")

    def asignar(self, destino=None, monto="100", fecha=date(2026, 3, 1), cuenta=None, **extra):
        return services.asignar(destino=destino or self.residente, cuenta=cuenta or self.usd, monto=D(monto), fecha=fecha,
                                concepto=extra.get("concepto"), nota=extra.get("nota", ""), actor=self.director)

    def gasto_personal(self, membresia=None, monto="10", tipo="egreso", fecha=date(2026, 3, 5), **extra):
        m = MovimientoPersonal(organizacion=self.org, membresia=membresia or self.residente, tipo=tipo, fecha=fecha,
                               monto=D(monto), moneda=extra.pop("moneda", "USD"), descripcion=extra.pop("descripcion", "Algo"), **extra)
        return services.registrar_personal(m)


class AsignacionesTests(PersonalMixin, TestCase):
    def test_asignar_crea_el_egreso_y_la_entrada_personal(self):
        egreso, personal = self.asignar(nota="Mesada de marzo")
        self.assertEqual((egreso.tipo, egreso.miembro, egreso.estado), ("egreso", self.residente, "confirmado"))
        self.assertEqual(saldo_cuenta(self.usd), D("-50"))        # 50 inicial − 100
        self.assertEqual((personal.tipo, personal.origen, personal.descripcion), ("ingreso", egreso, "Mesada de marzo"))
        self.assertEqual(services.saldo(self.residente), (D("10000"), D("100")))
        self.assertEqual(services.total_asignado(self.org)[self.residente.pk], (D("10000"), D("100"), 1))

    def test_anular_el_egreso_quita_la_entrada_de_la_cuenta(self):
        egreso, _ = self.asignar()
        egreso.transicionar("anulado", self.director.user, motivo="Me equivoqué")
        self.assertEqual(services.saldo(self.residente), (D("0"), D("0")))
        self.assertEqual(services.total_asignado(self.org), {})

    def test_solo_a_quien_tiene_cuenta_personal_y_acceso(self):
        for destino in (self.comprador, self.rosa, self.director_b):
            with self.subTest(destino=destino.nombre):
                with self.assertRaises(ValidationError):
                    self.asignar(destino=destino)
        self.assertEqual(Movimiento.objects.count(), 0)   # tampoco quedó el egreso a medias

    def test_vistas(self):
        self.entrar("tesorero")
        for vista in ("personal:asignaciones", "personal:asignacion_nueva"):
            self.assertEqual(self.client.get(reverse(vista)).status_code, 403)
        self.entrar("dir_a")
        r = self.client.post(reverse("personal:asignacion_nueva"), {
            "destino": self.residente.pk, "cuenta": self.usd.pk, "monto": "25", "fecha": "2026-03-02", "concepto": "", "nota": "Pasaje"})
        self.assertRedirects(r, reverse("personal:asignaciones"))
        self.assertEqual(services.saldo(self.residente)[1], D("25"))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="asignar", organizacion=self.org).exists())
        # El formulario no ofrece a quien no tiene cuenta personal, ni a gente de otra organización.
        for ajeno in (self.comprador.pk, self.rosa.pk, self.director_b.pk):
            r = self.client.post(reverse("personal:asignacion_nueva"), {
                "destino": ajeno, "cuenta": self.usd.pk, "monto": "5", "fecha": "2026-03-02"})
            self.assertEqual(r.status_code, 200)
        self.assertEqual(MovimientoPersonal.objects.count(), 1)


class PrivacidadTests(PersonalMixin, TestCase):
    def setUp(self):
        self.asignar(nota="Mesada")
        self.gasto_personal(descripcion="Regalo secreto", monto="30")
        self.url = reverse("personal:cuenta_de_miembro", args=[self.residente.pk])

    def test_apagado_el_director_ve_lo_asignado_pero_no_la_cuenta(self):
        self.entrar("dir_a")
        r = self.client.get(reverse("personal:asignaciones"))
        self.assertContains(r, "100,00")                 # lo que asignó
        self.assertNotContains(r, "Regalo secreto")
        self.assertNotContains(r, "Ver cuenta")
        self.assertIsNone(r.context["miembros"][0]["saldo_usd"])
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertFalse(RegistroAuditoria.objects.filter(accion="ver_cuenta_personal").exists())

    def test_encendido_la_ve_en_solo_lectura_y_queda_en_bitacora(self):
        Organizacion.objects.filter(pk=self.org.pk).update(director_ve_cuentas_personales=True)
        self.entrar("dir_a")
        r = self.client.get(self.url)
        self.assertContains(r, "Regalo secreto")
        self.assertTrue(r.context["solo_lectura"])
        self.assertNotContains(r, reverse("personal:egreso"))
        registro = RegistroAuditoria.objects.get(accion="ver_cuenta_personal")
        self.assertEqual((registro.organizacion, registro.usuario), (self.org, self.director.user))
        # Y el miembro lo sabe.
        self.entrar("residente")
        self.assertContains(self.client.get(reverse("personal:cuenta")), "el director puede ver tus saldos")

    def test_ni_encendido_se_puede_modificar_la_cuenta_de_otro(self):
        Organizacion.objects.filter(pk=self.org.pk).update(director_ve_cuentas_personales=True)
        secreto = MovimientoPersonal.objects.get(descripcion="Regalo secreto")
        self.entrar("dir_a")
        self.assertEqual(self.client.get(reverse("personal:movimiento_editar", args=[secreto.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("personal:movimiento_eliminar", args=[secreto.pk])).status_code, 404)
        self.assertTrue(MovimientoPersonal.objects.filter(pk=secreto.pk).exists())

    def test_ningun_otro_miembro_ve_la_cuenta(self):
        Organizacion.objects.filter(pk=self.org.pk).update(director_ve_cuentas_personales=True)
        for usuario in ("tesorero", "comprador"):
            self.entrar(usuario)
            self.assertEqual(self.client.get(self.url).status_code, 403)
        self.entrar("dir_b")   # director de otra organización, también con el interruptor
        Organizacion.objects.filter(pk=self.org_b.pk).update(director_ve_cuentas_personales=True)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_los_reportes_de_la_organizacion_no_incluyen_lo_personal(self):
        from reportes import services as reportes

        estado = reportes.estado_ingresos_egresos(self.org, date(2026, 1, 1), date(2026, 12, 31), None, "USD")
        totales = {f.celdas[0]: f.celdas[1] for f in estado.filas}
        self.assertEqual(totales["Total egresos"], D("100"))     # la asignación sí; el gasto personal de 30, no
        self.assertEqual(totales["Total ingresos"], D("0"))

    def test_el_aviso_de_cuenta_privada(self):
        self.entrar("residente")
        self.assertContains(self.client.get(reverse("personal:cuenta")), "Esta cuenta es privada")


class MiCuentaTests(PersonalMixin, TestCase):
    def test_registrar_editar_y_eliminar_lo_propio(self):
        self.entrar("residente")
        r = self.client.post(reverse("personal:egreso"), {"fecha": "2026-03-10", "monto": "12.50", "moneda": "USD", "concepto": "", "descripcion": "Café"})
        self.assertRedirects(r, reverse("personal:cuenta"))
        mov = MovimientoPersonal.objects.get()
        self.assertEqual((mov.membresia, mov.tipo, mov.monto_ves), (self.residente, "egreso", D("1250")))
        self.client.post(reverse("personal:movimiento_editar", args=[mov.pk]), {"fecha": "2026-03-10", "monto": "20", "moneda": "USD", "concepto": "", "descripcion": "Café y pan"})
        mov.refresh_from_db()
        self.assertEqual((mov.monto, mov.descripcion, mov.tipo), (D("20"), "Café y pan", "egreso"))
        self.client.post(reverse("personal:movimiento_eliminar", args=[mov.pk]))
        self.assertEqual(MovimientoPersonal.objects.count(), 0)

    def test_una_asignacion_no_se_edita_ni_se_borra_desde_la_cuenta(self):
        _, personal = self.asignar()
        self.entrar("residente")
        self.assertEqual(self.client.get(reverse("personal:movimiento_editar", args=[personal.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("personal:movimiento_eliminar", args=[personal.pk])).status_code, 404)

    def test_sin_cuenta_personal_no_hay_pantalla(self):
        self.entrar("comprador")
        for vista in ("personal:cuenta", "personal:egreso", "personal:conceptos"):
            self.assertEqual(self.client.get(reverse(vista)).status_code, 403)
        self.assertEqual(self.client.get(reverse("personal:resumen")).status_code, 200)

    def test_no_toco_los_movimientos_ni_conceptos_de_otro(self):
        ajeno = self.gasto_personal(membresia=self.tesorero)
        concepto = ConceptoPersonal.objects.create(organizacion=self.org, membresia=self.tesorero, tipo="egreso", nombre="Suyo")
        self.entrar("residente")
        self.assertEqual(self.client.post(reverse("personal:movimiento_eliminar", args=[ajeno.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("personal:concepto_eliminar", args=[concepto.pk])).status_code, 404)
        r = self.client.post(reverse("personal:egreso"), {"fecha": "2026-03-10", "monto": "5", "moneda": "USD", "concepto": concepto.pk, "descripcion": ""})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(MovimientoPersonal.objects.filter(membresia=self.residente).count(), 0)
        self.assertNotContains(self.client.get(reverse("personal:conceptos")), "Suyo")

    def test_conceptos_propios(self):
        self.entrar("residente")
        self.client.post(reverse("personal:conceptos"), {"tipo": "egreso", "nombre": "Transporte"})
        concepto = ConceptoPersonal.objects.get(membresia=self.residente)
        self.assertContains(self.client.post(reverse("personal:conceptos"), {"tipo": "egreso", "nombre": "transporte"}), "Ya tienes un concepto")
        self.gasto_personal(concepto=concepto, descripcion="")
        self.client.post(reverse("personal:concepto_eliminar", args=[concepto.pk]))   # en uso: se desactiva
        concepto.refresh_from_db()
        self.assertFalse(concepto.activo)

    def test_estadisticas(self):
        self.asignar(monto="200", fecha=date(2026, 3, 1))
        self.gasto_personal(monto="50", fecha=date(2026, 3, 4), descripcion="Comida")
        self.gasto_personal(monto="3000", moneda="VES", fecha=date(2026, 3, 6), descripcion="Pasaje")   # $30
        self.gasto_personal(monto="40", tipo="ingreso", fecha=date(2026, 4, 2), descripcion="Regalo")    # fuera de marzo
        e = services.estadisticas(self.residente, date(2026, 3, 1), date(2026, 3, 31), "USD")
        self.assertEqual((e["ingresos"], e["egresos"], e["resultado"], e["asignado"]), (D("200"), D("80"), D("120"), D("200")))
        self.assertEqual(e["gastado_pct"], D("40"))
        self.assertEqual([(r["nombre"], r["monto"]) for r in e["top_egresos"]], [("Comida", D("50")), ("Pasaje", D("30"))])
        self.assertEqual(services.saldo(self.residente)[1], D("160"))
        serie = services.serie_mensual(self.residente, [date(2026, 3, 1), date(2026, 4, 1)], "USD")
        self.assertEqual([(i, g) for _, i, g in serie], [(D("200"), D("80")), (D("40"), D("0"))])

    def test_el_director_tambien_es_miembro_y_tiene_su_cuenta(self):
        self.assertTrue(self.director.tiene_permiso("tiene_cuenta_personal"))
        self.asignar(destino=self.director, monto="15")
        self.gasto_personal(membresia=self.director, monto="5", descripcion="Lo mío")
        self.entrar("dir_a")
        r = self.client.get(reverse("personal:cuenta"))
        self.assertContains(r, "Lo mío")
        self.assertFalse(r.context["solo_lectura"])
        self.assertEqual(r.context["saldo_usd"], D("10"))
        # Su vista de director sigue intacta, en otra parte del menú.
        self.assertEqual(self.client.get(reverse("reportes:inicio")).status_code, 200)
        self.assertContains(self.client.get(reverse("inicio")), "Mi cuenta")
        # Pedir «su» cuenta por la ruta del director lo lleva a la propia.
        self.assertRedirects(self.client.get(reverse("personal:cuenta_de_miembro", args=[self.director.pk])), reverse("personal:cuenta"))


class CuotasYResumenTests(PersonalMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cuota = CuotaMiembro.objects.create(
            organizacion=cls.org, membresia=cls.rosa, concepto=cls.c_ingreso, monto=D("20"), moneda="USD",
            vigente_desde=date(2026, 2, 1))

    def test_esperado_contra_pagado_incluso_para_quien_no_tiene_acceso(self):
        self.gasto(date(2026, 2, 10), "20", tipo="ingreso", miembro=self.rosa)
        self.gasto(date(2026, 3, 12), "1500", tipo="ingreso", miembro=self.rosa, cuenta=self.ves)   # $15
        self.gasto(date(2026, 3, 12), "99", tipo="ingreso", miembro=self.residente)                 # de otro: no cuenta
        fila = estado_cuotas(self.org, self.ejercicio, hasta=date(2026, 4, 15))[0]
        self.assertEqual((fila["meses"], fila["esperado"], fila["pagado"], fila["pendiente"]), (3, D("60"), D("35"), D("25")))
        self.assertEqual(fila["ultimo_pago"], date(2026, 3, 12))

    def test_vigencia(self):
        self.cuota.vigente_hasta = date(2026, 3, 31)
        self.cuota.save()
        self.assertEqual(estado_cuotas(self.org, self.ejercicio, hasta=date(2026, 9, 1))[0]["meses"], 2)
        self.assertEqual(estado_cuotas(self.org, self.ejercicio, hasta=date(2026, 1, 20)), [])

    def test_reglas(self):
        with self.assertRaises(ValidationError):
            CuotaMiembro(organizacion=self.org, membresia=self.rosa, concepto=self.c_egreso, monto=D("5"),
                         vigente_desde=date(2026, 1, 1)).full_clean()
        with self.assertRaises(ValidationError):
            CuotaMiembro.objects.create(organizacion=self.org, membresia=self.director_b, concepto=self.c_ingreso,
                                        monto=D("5"), vigente_desde=date(2026, 1, 1))

    def test_vistas_de_cuotas(self):
        self.entrar("tesorero")
        self.assertEqual(self.client.get(reverse("finanzas:cuota_lista")).status_code, 403)
        self.entrar("dir_a")
        r = self.client.get(reverse("finanzas:cuota_lista"))
        self.assertContains(r, "Doña Rosa")
        r = self.client.post(reverse("finanzas:cuota_crear"), {
            "membresia": self.residente.pk, "concepto": self.c_ingreso.pk, "monto": "30", "moneda": "USD", "vigente_desde": "2026-01-01"})
        self.assertRedirects(r, reverse("finanzas:cuota_lista"))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="crear_cuota").exists())
        ajena = CuotaMiembro.objects.create(organizacion=self.org_b, membresia=self.director_b,
                                            concepto=Concepto.objects.create(organizacion=self.org_b, tipo="ingreso", nombre="Mensualidad"),
                                            monto=D("9"), vigente_desde=date(2026, 1, 1))
        self.assertEqual(self.client.get(reverse("finanzas:cuota_editar", args=[ajena.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("finanzas:cuota_eliminar", args=[ajena.pk])).status_code, 404)

    def test_mi_resumen_solo_muestra_lo_mio(self):
        self.gasto(date(2026, 2, 10), "70", tipo="ingreso", miembro=self.residente)
        self.gasto(date(2026, 2, 11), "20", miembro=self.residente)
        self.gasto(date(2026, 2, 12), "777", tipo="ingreso", miembro=self.tesorero)
        CuotaMiembro.objects.create(organizacion=self.org, membresia=self.residente, concepto=self.c_ingreso,
                                    monto=D("50"), vigente_desde=date(2026, 1, 1))
        self.entrar("residente")
        r = self.client.get(reverse("personal:resumen") + "?desde=2026-01-01&hasta=2026-12-31")
        self.assertEqual((r.context["aporto"], r.context["recibio"], r.context["neto"]), (D("70"), D("20"), D("50")))
        self.assertEqual(len(r.context["movimientos"]), 2)
        self.assertEqual([f["cuota"].membresia for f in r.context["cuotas"]], [self.residente])
        self.assertNotContains(r, "777,00")
        # El por-miembro de la organización cuenta también a quien no tiene acceso.
        self.gasto(date(2026, 2, 13), "20", tipo="ingreso", miembro=self.rosa)
        from reportes import services as reportes
        nombres = [f.celdas[0] for f in reportes.por_miembro(self.org, date(2026, 1, 1), date(2026, 12, 31), None, "USD").filas]
        self.assertIn("Doña Rosa", nombres)
