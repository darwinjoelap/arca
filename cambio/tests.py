from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import TasaCambio
from .services import SinTasaError, convertir, formatear, obtener_tasa

User = get_user_model()


class ConvertirTests(TestCase):
    def test_redondeo_en_punto_cinco_exacto_usa_round_half_up(self):
        # 1.00005 a 4 decimales cae justo en el medio del último dígito;
        # ROUND_HALF_UP debe subir a 1.0001 (no 1.0000 como daría banker's
        # rounding, que es el default de Decimal sin especificar redondeo).
        _, monto_usd = convertir(Decimal("1.00005"), "USD", Decimal("1"))
        self.assertEqual(monto_usd, Decimal("1.0001"))

    def test_tasa_con_cuatro_decimales_se_respeta_sin_perder_precision(self):
        monto_ves, monto_usd = convertir(Decimal("10"), "USD", Decimal("36.4321"))
        self.assertEqual(monto_ves, Decimal("364.3210"))
        self.assertEqual(monto_usd, Decimal("10.0000"))

    def test_monto_cero(self):
        monto_ves, monto_usd = convertir(Decimal("0"), "VES", Decimal("36.5"))
        self.assertEqual(monto_ves, Decimal("0.0000"))
        self.assertEqual(monto_usd, Decimal("0.0000"))

    def test_ida_y_vuelta_usd_ves_usd_no_se_desvia_mas_de_una_diezmilesima(self):
        tasa = Decimal("112.3456")
        original = Decimal("57.32")
        monto_ves, _ = convertir(original, "USD", tasa)
        _, monto_usd_de_vuelta = convertir(monto_ves, "VES", tasa)
        self.assertLessEqual(abs(monto_usd_de_vuelta - original), Decimal("0.0001"))

    def test_moneda_origen_queda_exacta_y_solo_se_deriva_la_otra(self):
        monto_ves, monto_usd = convertir(Decimal("100.1234"), "VES", Decimal("40"))
        self.assertEqual(monto_ves, Decimal("100.1234"))

    def test_moneda_no_soportada_lanza_value_error(self):
        with self.assertRaises(ValueError):
            convertir(Decimal("10"), "EUR", Decimal("36"))


class ObtenerTasaTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="tesorero", password="clave-de-prueba-123")

    def test_devuelve_la_tasa_exacta_de_la_fecha(self):
        hoy = date(2026, 9, 20)
        tasa = TasaCambio.objects.create(fecha=hoy, valor=Decimal("100"), fuente="bcv", cargada_por=self.usuario)
        obtenida, es_exacta = obtener_tasa(hoy, fuente="bcv")
        self.assertEqual(obtenida, tasa)
        self.assertTrue(es_exacta)

    def test_usa_la_ultima_tasa_anterior_si_no_hay_una_exacta(self):
        anterior = date(2026, 9, 18)
        TasaCambio.objects.create(fecha=anterior, valor=Decimal("95"), fuente="bcv", cargada_por=self.usuario)
        obtenida, es_exacta = obtener_tasa(date(2026, 9, 20), fuente="bcv")
        self.assertEqual(obtenida.fecha, anterior)
        self.assertFalse(es_exacta)

    def test_sin_ninguna_tasa_lanza_sin_tasa_error(self):
        with self.assertRaises(SinTasaError):
            obtener_tasa(date(2026, 9, 20), fuente="bcv")

    def test_filtra_por_fuente_aunque_exista_tasa_de_otra_fuente_esa_fecha(self):
        TasaCambio.objects.create(
            fecha=date(2026, 9, 20), valor=Decimal("100"), fuente="paralelo", cargada_por=self.usuario
        )
        with self.assertRaises(SinTasaError):
            obtener_tasa(date(2026, 9, 20), fuente="bcv")

    def test_sin_fuente_considera_cualquiera(self):
        TasaCambio.objects.create(
            fecha=date(2026, 9, 20), valor=Decimal("100"), fuente="paralelo", cargada_por=self.usuario
        )
        obtenida, es_exacta = obtener_tasa(date(2026, 9, 20))
        self.assertTrue(es_exacta)
        self.assertEqual(obtenida.fuente, "paralelo")


class FormatearTests(TestCase):
    def test_formato_es_ve_con_miles_y_dos_decimales(self):
        self.assertEqual(formatear(Decimal("1234.5")), "1.234,50")

    def test_formato_sin_decimales_redondea_half_up(self):
        self.assertEqual(formatear(Decimal("1234.5"), decimales=0), "1.235")

    def test_formato_numero_negativo(self):
        self.assertEqual(formatear(Decimal("-1234.5")), "-1.234,50")

    def test_formato_sin_miles(self):
        self.assertEqual(formatear(Decimal("9.999")), "10,00")


# --- Tasa automática del BCV -------------------------------------------------

from unittest import mock  # noqa: E402

from django.core.management import call_command  # noqa: E402
from django.urls import reverse  # noqa: E402

from . import bcv  # noqa: E402

HTML_BCV = """
<html><body>
<div id="euro"><div class="col-sm-6 col-xs-6 centrado"><strong> 612,10450000 </strong></div></div>
<div id="dolar" class="col-sm-12"><div class="field-content"><div class="row recuadrotsmc">
  <div class="col-sm-6 col-xs-6"><span> USD</span></div>
  <div class="col-sm-6 col-xs-6 centrado"><strong> 1.536,81560000 </strong></div></div></div></div>
<div class="pull-right dinpro center"><strong>Fecha Valor:</strong>
  <span class="date-display-single" property="dc:date" datatype="xsd:dateTime" content="2026-10-08T00:00:00-04:00">Jueves, 08 Octubre 2026</span></div>
</body></html>
"""


class TasaBCVTests(TestCase):
    def test_lee_valor_y_fecha_valor(self):
        valor, fecha = bcv.leer_tasa_html(HTML_BCV)
        self.assertEqual(valor, Decimal("1536.8156"))
        self.assertEqual(fecha, date(2026, 10, 8))

    def test_pagina_sin_el_bloque_del_dolar(self):
        with self.assertRaises(bcv.ErrorBCV):
            bcv.leer_tasa_html("<html><body>En mantenimiento</body></html>")
        with self.assertRaises(bcv.ErrorBCV):
            bcv.leer_tasa_html('<div id="dolar"><strong>n/d</strong></div>')

    def test_registra_con_la_fecha_valor_y_sin_usuario(self):
        with mock.patch.object(bcv, "descargar", return_value=HTML_BCV):
            tasa, estado = bcv.actualizar()
        self.assertEqual((estado, tasa.fecha, tasa.fuente, tasa.cargada_por), ("nueva", date(2026, 10, 8), "bcv", None))
        with mock.patch.object(bcv, "descargar", return_value=HTML_BCV):
            self.assertEqual(bcv.actualizar()[1], "igual")
        self.assertEqual(TasaCambio.objects.count(), 1)

    def test_corrige_si_el_bcv_cambia_el_valor_del_mismo_dia(self):
        bcv.registrar(Decimal("1500"), date(2026, 10, 8))
        tasa, estado = bcv.registrar(Decimal("1536.8156"), date(2026, 10, 8))
        self.assertEqual((estado, tasa.valor), ("corregida", Decimal("1536.8156")))

    def test_rechaza_un_salto_absurdo(self):
        bcv.registrar(Decimal("1500"), date(2026, 10, 7))
        with self.assertRaises(bcv.ErrorBCV):
            bcv.registrar(Decimal("15.36"), date(2026, 10, 8))   # coma mal leída
        self.assertEqual(TasaCambio.objects.count(), 1)

    def test_la_tasa_de_manana_no_se_usa_hoy(self):
        bcv.registrar(Decimal("1500"), date(2026, 10, 7))
        bcv.registrar(Decimal("1536"), date(2026, 10, 8))
        self.assertEqual(obtener_tasa(date(2026, 10, 7), fuente="bcv")[0].valor, Decimal("1500"))

    def test_el_comando_no_se_cae_si_el_bcv_falla(self):
        with mock.patch.object(bcv, "descargar", side_effect=OSError("sin red")):
            call_command("tareas_programadas", stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(TasaCambio.objects.count(), 0)

    def test_boton_solo_para_la_plataforma(self):
        url = reverse("cambio:consultar_bcv")
        comun = User.objects.create_user("comun", password="x")
        self.client.force_login(comun)
        self.assertEqual(self.client.post(url).status_code, 403)
        root = User.objects.create_superuser("root2", password="x")
        root.debe_cambiar_clave = False
        root.save()
        self.client.force_login(root)
        with mock.patch.object(bcv, "descargar", return_value=HTML_BCV):
            self.assertRedirects(self.client.post(url), reverse("cambio:tasa_lista"))
        self.assertEqual(TasaCambio.objects.get().cargada_por, root)
        self.assertContains(self.client.get(reverse("cambio:tasa_lista")), "Consultar BCV ahora")
