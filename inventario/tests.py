from datetime import date
from decimal import Decimal as D

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import RegistroAuditoria
from organizaciones.models import Membresia, TipoMiembro
from organizaciones.tests import DosOrganizacionesMixin

from . import services
from .models import Articulo, CategoriaArticulo, MovimientoInventario, Ubicacion


class InventarioMixin(DosOrganizacionesMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.deposito = Ubicacion.objects.create(organizacion=cls.org_a, nombre="Depósito")
        cls.cocina = Ubicacion.objects.create(organizacion=cls.org_a, nombre="Cocina")
        cls.arroz = Articulo.objects.create(organizacion=cls.org_a, clase="consumible", nombre="Arroz", unidad="kg",
                                            minimo=D("5"), valor_unitario=D("2"), moneda="USD")
        cls.silla = Articulo.objects.create(organizacion=cls.org_a, clase="bien", nombre="Silla plástica")
        cls.ubi_b = Ubicacion.objects.create(organizacion=cls.org_b, nombre="Sede B")
        cls.art_b = Articulo.objects.create(organizacion=cls.org_b, nombre="Proyector B")
        cls.usuario = cls.dueno_a.user

    def mover(self, tipo, cantidad, articulo=None, origen=None, destino=None, motivo=None):
        motivo = motivo or {"entrada": "compra", "salida": "consumo", "traslado": "traslado"}[tipo]
        return services.registrar(MovimientoInventario(
            organizacion=self.org_a, articulo=articulo or self.arroz, tipo=tipo, motivo=motivo, cantidad=D(cantidad),
            origen=origen, destino=destino), usuario=self.usuario)


class ExistenciasTests(InventarioMixin, TestCase):
    def test_entradas_salidas_y_traslados(self):
        self.mover("entrada", "20", destino=self.deposito)
        self.mover("traslado", "8", origen=self.deposito, destino=self.cocina)
        self.mover("salida", "3", origen=self.cocina)
        self.assertEqual(services.en_ubicacion(self.org_a, self.arroz, self.deposito), D("12"))
        self.assertEqual(services.en_ubicacion(self.org_a, self.arroz, self.cocina), D("5"))
        self.assertEqual(services.totales_por_articulo(self.org_a)[self.arroz.pk], D("17"))

    def test_no_sale_mas_de_lo_que_hay_en_esa_ubicacion(self):
        self.mover("entrada", "4", destino=self.deposito)
        with self.assertRaises(ValidationError):
            self.mover("salida", "5", origen=self.deposito)
        with self.assertRaises(ValidationError):
            self.mover("salida", "1", origen=self.cocina)          # hay en el depósito, no en la cocina
        with self.assertRaises(ValidationError):
            self.mover("traslado", "9", origen=self.deposito, destino=self.cocina)
        self.assertEqual(MovimientoInventario.objects.count(), 1)

    def test_reglas_del_movimiento(self):
        for kwargs in (
            dict(tipo="entrada", cantidad="0", destino=self.deposito),
            dict(tipo="entrada", cantidad="1", destino=self.deposito, motivo="consumo"),       # motivo de salida
            dict(tipo="traslado", cantidad="1", origen=self.deposito, destino=self.deposito),
            dict(tipo="entrada", cantidad="1", destino=self.ubi_b),                              # ubicación de otra organización
            dict(tipo="entrada", cantidad="1", destino=self.deposito, articulo=self.art_b),
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                self.mover(**kwargs)

    def test_anular_devuelve_la_existencia_pero_no_deja_negativos(self):
        entrada = self.mover("entrada", "10", destino=self.deposito)
        salida = self.mover("salida", "7", origen=self.deposito)
        with self.assertRaises(ValidationError):                     # ya salieron 7: quedaría en -7
            services.anular(entrada, usuario=self.usuario, motivo="error")
        services.anular(salida, usuario=self.usuario, motivo="no se usó")
        self.assertEqual(services.en_ubicacion(self.org_a, self.arroz, self.deposito), D("10"))
        services.anular(entrada, usuario=self.usuario, motivo="error de carga")
        self.assertEqual(services.totales_por_articulo(self.org_a).get(self.arroz.pk, D("0")), D("0"))
        with self.assertRaises(ValidationError):
            services.anular(entrada, usuario=self.usuario, motivo="otra vez")

    def test_resumen_minimo_y_valor(self):
        self.mover("entrada", "5", destino=self.deposito)             # justo en el mínimo
        self.mover("entrada", "3", articulo=self.silla, destino=self.deposito, motivo="donacion")
        filas, totales = services.resumen(self.org_a)
        arroz = next(a for a in filas if a.pk == self.arroz.pk)
        self.assertTrue(arroz.bajo_minimo)
        self.assertEqual((totales["articulos"], totales["bajo_minimo"], totales["usd"], totales["sin_valor"]), (2, 1, D("10"), 1))
        self.mover("entrada", "1", destino=self.cocina)
        self.assertEqual(services.resumen(self.org_a)[1]["bajo_minimo"], 0)

    def test_un_bien_no_guarda_minimo(self):
        self.silla.minimo = D("3")
        self.silla.save()
        self.silla.refresh_from_db()
        self.assertIsNone(self.silla.minimo)


class VistasInventarioTests(InventarioMixin, TestCase):
    def test_solo_entra_quien_gestiona_inventario(self):
        urls = [reverse("inventario:inicio"), reverse("inventario:articulo_crear"), reverse("inventario:entrada"),
                reverse("inventario:salida"), reverse("inventario:traslado"), reverse("inventario:movimientos"),
                reverse("inventario:catalogos"), reverse("inventario:articulo_detalle", args=[self.arroz.pk]),
                reverse("inventario:articulo_editar", args=[self.arroz.pk])]
        self.entrar("ana")
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertNotContains(self.client.get(reverse("inicio")), reverse("inventario:inicio"))
        TipoMiembro.objects.filter(pk=self.tipo_a.pk).update(puede_gestionar_inventario=True)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get(reverse("inicio")), reverse("inventario:inicio"))

    def test_lo_de_otra_organizacion_no_existe(self):
        self.entrar("dir_a")
        mov_b = services.registrar(MovimientoInventario(
            organizacion=self.org_b, articulo=self.art_b, tipo="entrada", motivo="compra", cantidad=D("1"),
            destino=self.ubi_b), usuario=self.dueno_b.user)
        for url in (reverse("inventario:articulo_detalle", args=[self.art_b.pk]),
                    reverse("inventario:articulo_editar", args=[self.art_b.pk]),
                    reverse("inventario:movimiento_anular", args=[mov_b.pk]),
                    reverse("inventario:catalogo_editar", args=["ubicacion", self.ubi_b.pk])):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.post(reverse("inventario:articulo_eliminar", args=[self.art_b.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse("inventario:inicio")), "Proyector B")
        r = self.client.post(reverse("inventario:entrada"), {
            "articulo": self.art_b.pk, "fecha": "2026-03-01", "cantidad": "1", "destino": self.ubi_b.pk, "motivo": "compra"})
        self.assertEqual(r.status_code, 200)                           # el formulario no los ofrece
        self.assertEqual(MovimientoInventario.objects.filter(organizacion=self.org_b).count(), 1)

    def test_crear_articulo_con_existencia_inicial(self):
        self.entrar("dir_a")
        cat = CategoriaArticulo.objects.create(organizacion=self.org_a, nombre="Limpieza")
        r = self.client.post(reverse("inventario:articulo_crear"), {
            "clase": "consumible", "nombre": "Cloro", "unidad": "litro", "categoria": cat.pk, "minimo": "2", "estado": "bueno",
            "moneda": "USD", "valor_unitario": "1.50", "cantidad_inicial": "6", "ubicacion_inicial": self.deposito.pk})
        cloro = Articulo.objects.get(nombre="Cloro")
        self.assertRedirects(r, reverse("inventario:articulo_detalle", args=[cloro.pk]))
        self.assertEqual(services.en_ubicacion(self.org_a, cloro, self.deposito), D("6"))
        self.assertEqual(cloro.movimientos.get().motivo, "inicial")
        self.assertTrue(RegistroAuditoria.objects.filter(accion="crear_articulo", organizacion=self.org_a).exists())
        r = self.client.post(reverse("inventario:articulo_crear"), {"clase": "bien", "nombre": "cloro", "unidad": "unidad", "estado": "bueno", "moneda": "USD"})
        self.assertContains(r, "Ya existe uno con ese nombre")

    def test_registrar_salida_y_anularla_desde_la_pantalla(self):
        self.mover("entrada", "10", destino=self.deposito)
        self.entrar("dir_a")
        datos = {"articulo": self.arroz.pk, "fecha": "2026-03-02", "cantidad": "50", "origen": self.deposito.pk, "motivo": "consumo"}
        self.assertContains(self.client.post(reverse("inventario:salida"), datos), "solo hay 10 kg")
        datos["cantidad"] = "4"
        self.assertRedirects(self.client.post(reverse("inventario:salida"), datos), reverse("inventario:articulo_detalle", args=[self.arroz.pk]))
        salida = MovimientoInventario.objects.get(tipo="salida")
        self.assertEqual((salida.registrado_por, salida.fecha), (self.usuario, date(2026, 3, 2)))
        self.assertTrue(RegistroAuditoria.objects.filter(accion="mover_inventario", objeto_id=salida.pk).exists())
        self.client.post(reverse("inventario:movimiento_anular", args=[salida.pk]), {"motivo": "se contó mal"})
        salida.refresh_from_db()
        self.assertTrue(salida.anulado)
        self.assertEqual(services.en_ubicacion(self.org_a, self.arroz, self.deposito), D("10"))
        self.assertContains(self.client.get(reverse("inventario:articulo_detalle", args=[self.arroz.pk])), "se contó mal")

    def test_filtros_del_listado(self):
        self.mover("entrada", "2", destino=self.cocina)
        self.entrar("dir_a")
        url = reverse("inventario:inicio")
        self.assertEqual({a.nombre for a in self.client.get(url, {"clase": "bien"}).context["articulos"]}, {"Silla plástica"})
        self.assertEqual({a.nombre for a in self.client.get(url, {"solo": "minimo"}).context["articulos"]}, {"Arroz"})
        en_cocina = self.client.get(url, {"ubicacion": self.cocina.pk}).context["articulos"]
        self.assertEqual([(a.nombre, a.existencia) for a in en_cocina], [("Arroz", D("2"))])
        self.assertEqual(list(self.client.get(url, {"ubicacion": self.deposito.pk}).context["articulos"]), [])

    def test_catalogos_en_uso_no_se_eliminan(self):
        self.mover("entrada", "2", destino=self.cocina)
        self.entrar("dir_a")
        self.client.post(reverse("inventario:catalogo_eliminar", args=["ubicacion", self.cocina.pk]))
        self.assertTrue(Ubicacion.objects.filter(pk=self.cocina.pk).exists())
        self.client.post(reverse("inventario:catalogo_eliminar", args=["ubicacion", self.deposito.pk]))
        self.assertFalse(Ubicacion.objects.filter(pk=self.deposito.pk).exists())
        self.client.post(reverse("inventario:articulo_eliminar", args=[self.arroz.pk]))
        self.assertTrue(Articulo.objects.filter(pk=self.arroz.pk).exists())
        self.client.post(reverse("inventario:catalogo_crear", args=["categoria"]), {"nombre": "Cocina"})
        self.assertTrue(CategoriaArticulo.objects.filter(organizacion=self.org_a, nombre="Cocina").exists())
        self.assertEqual(self.client.get(reverse("inventario:catalogo_crear", args=["otra"])).status_code, 404)
