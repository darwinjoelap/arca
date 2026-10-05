"""El contrato del endpoint de sync. El cliente (offline-sync-core.js) decide
qué hacer con un pendiente solo por el código y el JSON de la respuesta, así
que estas pruebas fijan exactamente eso."""

import json
import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import RegistroAuditoria
from finanzas.models import Movimiento
from finanzas.tests import CLAVE, LibroMixin

URL = reverse("sync:api_movimiento")


class ApiMovimientoTests(LibroMixin, TestCase):
    def carga(self, **cambios):
        datos = {
            "tipo": "egreso", "fecha": self.hoy.isoformat(), "cuenta": str(self.usd.pk),
            "concepto": str(self.c_egreso.pk), "descripcion": "", "monto": "12.50", "miembro": "",
            "tercero": "Bodega", "referencia": "", "uuid_cliente": str(uuid.uuid4()),
        }
        datos.update(cambios)
        return datos

    def enviar(self, datos):
        return self.client.post(URL, data=json.dumps(datos), content_type="application/json")

    def test_crea_y_es_idempotente(self):
        self.entrar("tesorero")
        datos = self.carga(_offline=True, _usuario=str(self.tesorero.user.pk), _organizacion=str(self.org.pk))
        r = self.enviar(datos)
        self.assertEqual(r.status_code, 201)
        cuerpo = r.json()
        self.assertEqual((cuerpo["resultado"], cuerpo["numero_vale"], cuerpo["por_aprobar"]), ("creado", 1, False))
        m = Movimiento.objects.get()
        self.assertEqual((m.monto, m.tercero, m.registrado_por), (Decimal("12.50"), "Bodega", self.tesorero.user))
        self.assertEqual(cuerpo["url"], reverse("finanzas:movimiento_detalle", args=[m.pk]))

        r = self.enviar(datos)  # el reintento de una respuesta que se perdió
        self.assertEqual((r.status_code, r.json()["resultado"]), (200, "ya_existia"))
        self.assertEqual(Movimiento.objects.count(), 1)
        registro = RegistroAuditoria.objects.get(accion="registrar_movimiento")
        self.assertIn("capturado sin conexión", registro.descripcion)

    def test_sin_sesion_responde_401_en_json_y_nunca_redirige(self):
        r = self.enviar(self.carga())
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["codigo"], "sin_sesion")
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_clave_temporal_tambien_es_401_en_json(self):
        self.tesorero.user.debe_cambiar_clave = True
        self.tesorero.user.save()
        self.client.login(username="tesorero", password=CLAVE)
        r = self.enviar(self.carga())
        self.assertEqual((r.status_code, r.json()["codigo"]), (401, "sin_sesion"))

    def test_lo_capturado_por_otro_usuario_u_organizacion_no_se_guarda_a_mi_nombre(self):
        self.entrar("tesorero")
        r = self.enviar(self.carga(_usuario=str(self.comprador.user.pk), _organizacion=str(self.org.pk)))
        self.assertEqual((r.status_code, r.json()["codigo"]), (409, "otra_sesion"))
        r = self.enviar(self.carga(_usuario=str(self.tesorero.user.pk), _organizacion=str(self.org_b.pk)))
        self.assertEqual((r.status_code, r.json()["codigo"]), (409, "otra_sesion"))
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_datos_invalidos_son_422_con_detalle(self):
        self.entrar("tesorero")
        casos = [
            self.carga(monto="0"), self.carga(monto="abc"), self.carga(concepto="", descripcion=""),
            self.carga(cuenta=str(self.cuenta_b.pk)), self.carga(concepto=str(self.concepto_b.pk)),
            self.carga(fecha="1999-01-01"), self.carga(tipo="regalo"), self.carga(uuid_cliente=""),
            self.carga(uuid_cliente="no-es-uuid"),
        ]
        for datos in casos:
            with self.subTest(datos=datos):
                r = self.enviar(datos)
                self.assertEqual(r.status_code, 422)
                self.assertTrue(r.json()["detalle"])
        self.assertEqual(self.client.post(URL, data="{roto", content_type="application/json").status_code, 422)
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_sin_permiso_es_403_en_json(self):
        self.entrar("comprador")  # registra egresos, no ingresos
        r = self.enviar(self.carga(tipo="ingreso", concepto=str(self.c_ingreso.pk)))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(r.json()["detalle"])
        self.entrar("residente")
        self.assertEqual(self.enviar(self.carga()).status_code, 403)
        self.assertEqual(Movimiento.objects.count(), 0)

    def test_respeta_la_aprobacion_de_egresos(self):
        self.org.requiere_aprobacion_egresos = True
        self.org.save()
        self.entrar("comprador")
        r = self.enviar(self.carga())
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["por_aprobar"])
        self.assertEqual(Movimiento.objects.get().estado, "registrado")

    def test_solo_post(self):
        self.entrar("tesorero")
        self.assertEqual(self.client.get(URL).status_code, 405)

    def test_el_formulario_carga_los_scripts_de_la_cola(self):
        self.entrar("tesorero")
        r = self.client.get(reverse("finanzas:egreso_registrar"))
        self.assertContains(r, "js/offline-forms.js")
        self.assertContains(r, 'data-offline data-tipo="egreso"')
        self.assertContains(r, f'data-usuario="{self.tesorero.user.pk}"')
        self.assertContains(r, f'data-organizacion="{self.org.pk}"')
        self.assertContains(self.client.get("/sw.js"), "ArcaOffline.TAG_SYNC")
