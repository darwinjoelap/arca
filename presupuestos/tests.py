from datetime import date
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from cambio.models import TasaCambio
from core.models import RegistroAuditoria
from finanzas.models import Concepto, Movimiento
from finanzas.services import registrar_movimiento
from finanzas.tests import LibroMixin
from organizaciones.models import Ejercicio

from .models import PartidaPresupuestaria, Presupuesto
from .services import comparativo, meses_transcurridos


class PresupuestoMixin(LibroMixin):
    """Año fijo (2026) para que los meses de las pruebas no dependan de hoy."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Ejercicio.objects.filter(pk=cls.ejercicio.pk).update(
            nombre="2026", fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31))
        cls.ejercicio.refresh_from_db()
        TasaCambio.objects.create(fecha=date(2026, 1, 1), valor=D("100"), fuente="bcv", cargada_por=cls.root)
        cls.p = Presupuesto.objects.create(organizacion=cls.org, caja=cls.caja, ejercicio=cls.ejercicio, moneda="USD")
        cls.luz = Concepto.objects.create(organizacion=cls.org, tipo="egreso", nombre="Luz")
        PartidaPresupuestaria.objects.create(organizacion=cls.org, presupuesto=cls.p, concepto=cls.c_egreso, monto_mensual=D("100"))
        PartidaPresupuestaria.objects.create(organizacion=cls.org, presupuesto=cls.p, concepto=cls.c_ingreso, monto_mensual=D("300"))

    def gasto(self, fecha, monto, concepto="auto", tipo="egreso", cuenta=None, **extra):
        if concepto == "auto":
            concepto = self.c_ingreso if tipo == "ingreso" else self.c_egreso
        m = Movimiento(organizacion=self.org, tipo=tipo, fecha=fecha, cuenta=cuenta or self.usd,
                       concepto=concepto, monto=D(monto), **extra)
        return registrar_movimiento(m, membresia=self.director)[0]


class ComparativoTests(PresupuestoMixin, TestCase):
    def test_mes_y_acumulado(self):
        self.gasto(date(2026, 1, 10), "80")
        self.gasto(date(2026, 3, 5), "150")
        self.gasto(date(2026, 3, 20), "2000", cuenta=self.ves)   # Bs. 2000 a tasa 100 = $20
        self.gasto(date(2026, 4, 1), "999")                      # fuera del corte de marzo
        self.gasto(date(2026, 3, 9), "250", tipo="ingreso")
        c = comparativo(self.p, date(2026, 3, 15))
        self.assertEqual(c.meses, 3)
        comida = next(l for l in c.egresos if l.concepto == self.c_egreso)
        self.assertEqual((comida.presupuesto_mes, comida.real_mes, comida.variacion_mes), (D("100"), D("170"), D("70")))
        self.assertEqual((comida.presupuesto_acumulado, comida.real_acumulado), (D("300"), D("250")))
        self.assertEqual(comida.pct_mes, D("170"))
        self.assertFalse(comida.favorable(comida.variacion_mes))       # gastar de más: desfavorable
        self.assertTrue(comida.favorable(comida.variacion_acumulada))  # vamos por debajo en el año
        aportes = c.ingresos[0]
        self.assertEqual((aportes.real_mes, aportes.variacion_mes), (D("250"), D("-50")))
        self.assertFalse(aportes.favorable(aportes.variacion_mes))     # ingresar de menos: desfavorable
        self.assertEqual(c.resultado("real_mes"), D("80"))

    def test_lo_ejecutado_sin_partida_o_sin_concepto_aparece(self):
        self.gasto(date(2026, 2, 3), "40", concepto=self.luz)
        self.gasto(date(2026, 2, 4), "15", concepto=None, descripcion="Taxi")
        c = comparativo(self.p, date(2026, 2, 1))
        nombres = {l.nombre: l for l in c.egresos}
        self.assertFalse(nombres["Luz"].tiene_partida)
        self.assertEqual(nombres["Luz"].real_mes, D("40"))
        self.assertIsNone(nombres["Luz"].pct_mes)
        self.assertEqual(nombres["Otros (sin concepto)"].real_acumulado, D("15"))
        self.assertEqual(c.total("egreso", "real_mes"), D("55"))

    def test_anulados_por_aprobar_y_otras_cajas_no_cuentan(self):
        self.gasto(date(2026, 1, 5), "30").transicionar("anulado", self.director.user, motivo="x")
        from finanzas.models import Caja, Cuenta
        otra = Caja.objects.create(organizacion=self.org, nombre="Grupo")
        cuenta = Cuenta.objects.create(organizacion=self.org, caja=otra, nombre="Efectivo", moneda="USD")
        self.gasto(date(2026, 1, 6), "70", cuenta=cuenta)
        c = comparativo(self.p, date(2026, 1, 1))
        self.assertEqual(c.total("egreso", "real_mes"), D("0"))

    def test_meses_transcurridos(self):
        self.assertEqual(meses_transcurridos(self.ejercicio, date(2026, 1, 31)), 1)
        self.assertEqual(meses_transcurridos(self.ejercicio, date(2026, 12, 31)), 12)
        self.assertEqual(meses_transcurridos(self.ejercicio, date(2027, 5, 1)), 12)
        self.assertEqual(meses_transcurridos(self.ejercicio, date(2025, 5, 1)), 0)


class VistasPresupuestoTests(PresupuestoMixin, TestCase):
    def test_permisos(self):
        self.tesorero.tipo.puede_ver_presupuesto = True
        self.tesorero.tipo.save()
        detalle = reverse("presupuestos:detalle", args=[self.p.pk])
        self.entrar("tesorero")
        self.assertEqual(self.client.get(detalle).status_code, 200)
        self.assertEqual(self.client.get(reverse("presupuestos:lista")).status_code, 200)
        for nombre in ("editar", "aprobar", "reabrir", "eliminar"):
            self.assertEqual(self.client.post(reverse(f"presupuestos:{nombre}", args=[self.p.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("presupuestos:crear")).status_code, 403)
        self.entrar("comprador")
        self.assertEqual(self.client.get(detalle).status_code, 403)

    def test_editar_guarda_crea_y_borra_partidas(self):
        self.entrar("dir_a")
        url = reverse("presupuestos:editar", args=[self.p.pk])
        self.assertContains(self.client.get(url), 'value="100.00"')
        r = self.client.post(url, {
            f"monto_{self.c_egreso.pk}": "1.250,50", f"monto_{self.luz.pk}": "25", f"solicitud_{self.luz.pk}": "on",
            f"nota_{self.luz.pk}": "Pedir antes", f"monto_{self.c_ingreso.pk}": "",
        })
        self.assertRedirects(r, reverse("presupuestos:detalle", args=[self.p.pk]))
        partidas = {p.concepto_id: p for p in self.p.partidas.all()}
        self.assertEqual(partidas[self.c_egreso.pk].monto_mensual, D("1250.50"))
        self.assertTrue(partidas[self.luz.pk].requiere_solicitud)
        self.assertNotIn(self.c_ingreso.pk, partidas)   # quedó vacía: se borra
        self.assertTrue(RegistroAuditoria.objects.filter(accion="editar_presupuesto", organizacion=self.org).exists())

        r = self.client.post(url, {f"monto_{self.c_egreso.pk}": "-5"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "mayor o igual a cero")
        self.assertEqual(self.p.partidas.get(concepto=self.c_egreso).monto_mensual, D("1250.50"))

    def test_aprobar_bloquea_y_reabrir_queda_en_bitacora(self):
        self.entrar("dir_a")
        self.client.post(reverse("presupuestos:aprobar", args=[self.p.pk]))
        self.p.refresh_from_db()
        self.assertEqual((self.p.estado, self.p.aprobado_por), ("aprobado", self.director.user))
        editar = reverse("presupuestos:editar", args=[self.p.pk])
        self.client.post(editar, {f"monto_{self.c_egreso.pk}": "5"})
        self.assertEqual(self.p.partidas.get(concepto=self.c_egreso).monto_mensual, D("100"))
        self.client.post(reverse("presupuestos:eliminar", args=[self.p.pk]))
        self.assertTrue(Presupuesto.objects.filter(pk=self.p.pk).exists())
        self.client.post(reverse("presupuestos:reabrir", args=[self.p.pk]))
        self.p.refresh_from_db()
        self.assertEqual(self.p.estado, "borrador")
        self.assertTrue(RegistroAuditoria.objects.filter(accion="reabrir_presupuesto").exists())

    def test_crear_y_uno_solo_por_caja_y_ejercicio(self):
        self.entrar("dir_a")
        r = self.client.post(reverse("presupuestos:crear"), {
            "caja": self.caja.pk, "ejercicio": self.ejercicio.pk, "moneda": "USD", "nota": ""})
        self.assertContains(r, "ya tiene un presupuesto")
        self.assertEqual(Presupuesto.objects.filter(organizacion=self.org).count(), 1)

    def test_aislamiento(self):
        ajeno = Presupuesto.objects.create(organizacion=self.org_b, caja=self.caja_b, ejercicio=self.ejercicio_b)
        self.entrar("dir_a")
        self.assertEqual(list(self.client.get(reverse("presupuestos:lista")).context["presupuestos"]), [self.p])
        for nombre in ("detalle", "editar", "aprobar", "reabrir", "eliminar"):
            with self.subTest(vista=nombre):
                url = reverse(f"presupuestos:{nombre}", args=[ajeno.pk])
                self.assertEqual(self.client.post(url).status_code if nombre not in ("detalle",) else self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse("reportes:presupuesto", args=[ajeno.pk])).status_code, 404)
        r = self.client.post(reverse("presupuestos:crear"), {
            "caja": self.caja_b.pk, "ejercicio": self.ejercicio.pk, "moneda": "USD"})
        self.assertEqual(r.status_code, 200)
        with self.assertRaises(ValidationError):
            Presupuesto.objects.create(organizacion=self.org, caja=self.caja_b, ejercicio=self.ejercicio)
        with self.assertRaises(ValidationError):
            PartidaPresupuestaria.objects.create(organizacion=self.org, presupuesto=self.p, concepto=self.concepto_b)


class AvisoDePartidaTests(PresupuestoMixin, TestCase):
    """El presupuesto avisa al registrar un egreso, pero no lo impide."""

    def aprobar(self):
        Presupuesto.objects.filter(pk=self.p.pk).update(estado="aprobado")

    def consulta(self, concepto=None, fecha="2026-03-15"):
        return self.client.get(reverse("presupuestos:partida_disponible"), {
            "cuenta": self.usd.pk, "concepto": (concepto or self.c_egreso).pk, "fecha": fecha}).json()["partida"]

    def test_borrador_no_rige_y_sin_partida_no_avisa(self):
        self.client.force_login(self.director.user)
        self.assertIsNone(self.consulta())
        self.aprobar()
        self.assertIsNone(self.consulta(concepto=self.luz))
        self.assertIsNotNone(self.consulta())

    def test_disponible_del_mes(self):
        self.aprobar()
        self.gasto(date(2026, 3, 5), "30")
        self.gasto(date(2026, 3, 20), "2000", cuenta=self.ves)   # $20
        self.gasto(date(2026, 2, 5), "70")                       # otro mes
        self.client.force_login(self.director.user)
        p = self.consulta()
        self.assertEqual((p["presupuesto"], p["ejecutado"], p["disponible"], p["moneda"]), (100.0, 50.0, 50.0, "USD"))
        self.assertEqual(p["mes"], "marzo de 2026")

    def test_egreso_que_se_pasa_se_guarda_con_aviso(self):
        self.aprobar()
        self.gasto(date(2026, 3, 5), "80")
        self.client.force_login(self.director.user)
        datos = {"fecha": "2026-03-10", "cuenta": self.usd.pk, "concepto": self.c_egreso.pk, "monto": "50"}
        r = self.client.post(reverse("finanzas:egreso_registrar"), datos, follow=True)
        self.assertEqual(Movimiento.objects.filter(fecha=date(2026, 3, 10)).count(), 1)
        self.assertContains(r, "queda excedida en $ 30,00")
        datos["fecha"] = "2026-04-10"                              # abril: partida intacta, sin aviso
        r = self.client.post(reverse("finanzas:egreso_registrar"), datos, follow=True)
        self.assertNotContains(r, "queda excedida")

    def test_quien_no_registra_egresos_no_consulta(self):
        self.aprobar()
        self.client.force_login(self.residente.user)
        r = self.client.get(reverse("presupuestos:partida_disponible"), {"cuenta": self.usd.pk, "concepto": self.c_egreso.pk, "fecha": "2026-03-15"})
        self.assertEqual(r.status_code, 403)


class ConceptoNuevoDesdePresupuestoTests(PresupuestoMixin, TestCase):
    def test_se_crea_el_concepto_y_su_partida(self):
        self.client.force_login(self.director.user)
        url = reverse("presupuestos:editar", args=[self.p.pk])
        r = self.client.post(url, {f"monto_{self.c_egreso.pk}": "100", "nuevo_egreso_nombre": "  Gas  doméstico ", "nuevo_egreso_monto": "15,50"})
        self.assertRedirects(r, reverse("presupuestos:detalle", args=[self.p.pk]))
        gas = Concepto.objects.get(organizacion=self.org, nombre="Gas doméstico")
        self.assertEqual((gas.tipo, gas.caja_id, gas.activo), ("egreso", None, True))
        self.assertEqual(self.p.partidas.get(concepto=gas).monto_mensual, D("15.50"))
        self.assertEqual(self.p.partidas.get(concepto=self.c_egreso).monto_mensual, D("100"))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="crear_concepto", objeto_id=gas.pk).exists())
        # ya sirve para registrar un egreso
        self.assertContains(self.client.get(reverse("finanzas:egreso_registrar")), "Gas doméstico")

    def test_si_ya_existe_no_se_duplica(self):
        self.client.force_login(self.director.user)
        r = self.client.post(reverse("presupuestos:editar", args=[self.p.pk]), {"nuevo_egreso_nombre": "luz", "nuevo_egreso_monto": "5"})
        self.assertContains(r, "ya existe")
        self.assertEqual(Concepto.objects.filter(organizacion=self.org, nombre__iexact="luz").count(), 1)
