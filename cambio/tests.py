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
