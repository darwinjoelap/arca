"""Reportes. Los ve quien tiene el permiso `puede_ver_reportes` en su tipo de
miembro (el director y los administradores lo tienen siempre). El de
presupuesto lo ve además quien tiene `puede_ver_presupuesto`.

Toda pantalla acepta ?formato=xlsx o ?formato=pdf y devuelve el mismo reporte
como archivo. Cada emisión de archivo queda en la bitácora."""

from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify

from core.auditoria import registrar
from core.mixins import requiere_permiso, tiene_permiso
from core.models import RegistroAuditoria
from finanzas.models import Movimiento
from finanzas.views import movimientos_visibles
from presupuestos.models import Presupuesto
from presupuestos.services import meses_del_ejercicio

from . import services
from .exportar import a_excel, a_pdf, comprobante_pdf
from .forms import FiltroReporteForm

VER = "puede_ver_reportes"

# clave -> (título, descripción, icono, filtros que usa, grupo)
CATALOGO = {
    "estado": ("Estado de ingresos y egresos", "Cuánto entró y salió por concepto, y el resultado del período.",
               "bi-clipboard-data", ("periodo", "caja", "moneda"), "Resultados"),
    "variacion": ("Variación contra el período anterior", "Cada concepto comparado con el período anterior de igual duración.",
                  "bi-arrow-left-right", ("periodo", "caja", "moneda"), "Resultados"),
    "flujo": ("Flujo mensual", "Ingresos, egresos y resultado de cada mes del ejercicio.",
              "bi-bar-chart-line", ("ejercicio", "caja", "moneda"), "Resultados"),
    "miembros": ("Por miembro", "Lo que aportó y lo que recibió cada miembro.",
                 "bi-people", ("periodo", "caja", "moneda"), "Resultados"),
    "libro": ("Libro de caja o banco", "Una cuenta, movimiento por movimiento, con saldo corrido en su moneda.",
              "bi-journal-text", ("periodo", "cuenta"), "Libros contables"),
    "diario": ("Libro diario", "Todos los movimientos en orden, con monto original, tasa y equivalente.",
               "bi-journals", ("periodo", "caja", "moneda"), "Libros contables"),
}


def _archivo(request, reporte, formato):
    organizacion = request.organizacion
    quien = request.membresia.nombre
    nombre = f"{slugify(reporte.titulo)[:50]}-{timezone.localdate():%Y%m%d}"
    if formato == "xlsx":
        contenido, tipo = a_excel(reporte, organizacion, quien), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif formato == "pdf":
        contenido, tipo = a_pdf(reporte, organizacion, quien), "application/pdf"
    else:
        raise Http404
    registrar(request, RegistroAuditoria.Accion.EMITIR_REPORTE, modelo="Reporte", objeto_id=reporte.clave,
              descripcion=f"{reporte.titulo} ({formato.upper()}) · {reporte.subtitulo}")
    respuesta = HttpResponse(contenido, content_type=tipo)
    respuesta["Content-Disposition"] = f'{"inline" if formato == "pdf" else "attachment"}; filename="{nombre}.{formato}"'
    return respuesta


def _consulta_sin_formato(request):
    consulta = request.GET.copy()
    consulta.pop("formato", None)
    return consulta.urlencode()


@requiere_permiso(VER)
def inicio(request):
    grupos = {}
    for clave, (titulo, descripcion, icono, _filtros, grupo) in CATALOGO.items():
        grupos.setdefault(grupo, []).append({"clave": clave, "titulo": titulo, "descripcion": descripcion, "icono": icono})
    presupuestos = Presupuesto.objects.filter(organizacion=request.organizacion).select_related("caja", "ejercicio")
    return render(request, "reportes/inicio.html", {"grupos": grupos, "presupuestos": presupuestos})


@requiere_permiso(VER)
def reporte(request, clave):
    if clave not in CATALOGO:
        raise Http404
    organizacion = request.organizacion
    filtro = FiltroReporteForm(request.GET, organizacion=organizacion)
    v = filtro.valores()
    usa = CATALOGO[clave][3]

    aviso = None
    if clave == "libro":
        if v["cuenta"] is None:
            aviso = "Todavía no hay cuentas. Crea una en Configuración → Cajas y cuentas."
        else:
            resultado = services.libro_cuenta(v["cuenta"], v["desde"], v["hasta"])
    elif clave == "flujo":
        if v["ejercicio"] is None:
            aviso = "Todavía no hay ejercicios. Crea uno en Configuración → Ejercicios."
        else:
            resultado = services.flujo_mensual(organizacion, v["ejercicio"], v["caja"], v["moneda"], hoy=timezone.localdate())
    else:
        constructor = {"estado": services.estado_ingresos_egresos, "variacion": services.comparativo_periodos,
                       "miembros": services.por_miembro, "diario": services.libro_diario}[clave]
        resultado = constructor(organizacion, v["desde"], v["hasta"], v["caja"], v["moneda"])

    if aviso is None and request.GET.get("formato"):
        return _archivo(request, resultado, request.GET["formato"])

    grafico = None
    if aviso is None and clave == "flujo":
        grafico = _grafico_mensual(services.serie_mensual(organizacion, v["ejercicio"], v["caja"], v["moneda"]))
    return render(request, "reportes/reporte.html", {
        "reporte": None if aviso else resultado, "aviso": aviso, "filtro": filtro, "usa": usa, "v": v,
        "clave": clave, "consulta": _consulta_sin_formato(request), "grafico": grafico,
        "simbolo": services.SIMBOLO[v["moneda"]],
    })


@login_required
def presupuesto(request, pk):
    """Presupuesto contra real, como reporte (pantalla, Excel o PDF)."""
    if not (tiene_permiso(request, "puede_ver_presupuesto") or tiene_permiso(request, VER)):
        raise PermissionDenied("No tienes permiso para ver el presupuesto.")
    p = get_object_or_404(Presupuesto.objects.select_related("caja", "ejercicio"), pk=pk, organizacion=request.organizacion)
    meses = meses_del_ejercicio(p.ejercicio)
    hoy = timezone.localdate().replace(day=1)
    mes = hoy if hoy in meses else (meses[-1] if hoy > meses[-1] else meses[0])
    try:
        anio, numero = request.GET.get("mes", "").split("-")
        pedido = date(int(anio), int(numero), 1)
        mes = pedido if pedido in meses else mes
    except (ValueError, TypeError):
        pass
    resultado = services.presupuesto_vs_real(p, mes)
    if request.GET.get("formato"):
        return _archivo(request, resultado, request.GET["formato"])
    return render(request, "reportes/reporte.html", {
        "reporte": resultado, "clave": "presupuesto", "consulta": _consulta_sin_formato(request),
        "meses": [(m, services.nombre_mes(m)) for m in meses], "mes": mes, "presupuesto": p, "usa": (),
    })


@login_required
def comprobante(request, pk):
    """PDF de un movimiento. Lo puede emitir quien puede verlo."""
    if not any(tiene_permiso(request, p) for p in (VER, "puede_registrar_ingresos", "puede_registrar_egresos")):
        raise PermissionDenied("No tienes permiso para ver el libro de caja.")
    movimiento = get_object_or_404(
        movimientos_visibles(request).select_related(
            "cuenta", "caja", "concepto", "concepto__padre", "miembro", "miembro__user", "registrado_por", "ejercicio"),
        pk=pk,
    )
    contenido = comprobante_pdf(movimiento, request.organizacion, request.membresia.nombre)
    registrar(request, RegistroAuditoria.Accion.EMITIR_REPORTE, modelo="Movimiento", objeto_id=movimiento.pk,
              descripcion=f"Comprobante de {movimiento.get_tipo_display().lower()} #{movimiento.numero_vale}")
    respuesta = HttpResponse(contenido, content_type="application/pdf")
    respuesta["Content-Disposition"] = f'inline; filename="comprobante-{movimiento.tipo}-{movimiento.numero_vale:05d}.pdf"'
    return respuesta


# --- Análisis ---------------------------------------------------------------


def _escala_limpia(maximo):
    """Tope del eje y sus marcas, redondeados a números fáciles de leer."""
    maximo = float(maximo)
    if maximo <= 0:
        return 1.0, [0.0, 1.0]
    potencia = 10 ** (len(str(int(maximo))) - 1)
    for paso in (0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10):
        if paso * potencia * 4 >= maximo:
            unidad = paso * potencia
            break
    marcas = [unidad * i for i in range(5)]
    return marcas[-1], marcas


def _grafico_mensual(serie):
    """Geometría de las columnas agrupadas (ingresos y egresos por mes), ya
    calculada para dibujarla como SVG en la plantilla sin JavaScript de cálculo."""
    if not serie or not any(i or e for _, i, e in serie):
        return None
    ancho, alto, izq, abajo, arriba = 720, 260, 56, 28, 12
    util_alto, util_ancho = alto - abajo - arriba, ancho - izq - 8
    tope, marcas = _escala_limpia(max(max(i, e) for _, i, e in serie))
    banda = util_ancho / len(serie)
    grosor = min(20, (banda - 10) / 2)

    def y(valor):
        return arriba + util_alto * (1 - float(valor) / tope)

    base = arriba + util_alto

    def columna(x, valor):
        """Trazo SVG de una columna: recta en la base, redondeada (4px) arriba."""
        alto_col = base - y(valor)
        if alto_col < 0.5:
            return ""
        r = min(4, alto_col, grosor / 2)
        return (f"M{x:.1f},{base:.1f} v{-(alto_col - r):.1f} q0,{-r:.1f} {r:.1f},{-r:.1f} "
                f"h{grosor - 2 * r:.1f} q{r:.1f},0 {r:.1f},{r:.1f} v{alto_col - r:.1f} z")

    columnas = []
    for n, (mes, ing, egr) in enumerate(serie):
        centro = izq + banda * (n + 0.5)
        columnas.append({
            "mes": services.nombre_mes(mes, con_anio=False)[:3], "nombre": services.nombre_mes(mes),
            "x": f"{centro:.1f}", "banda_x": f"{izq + banda * n:.1f}", "banda_ancho": f"{banda:.1f}",
            "ingreso": ing, "egreso": egr, "resultado": ing - egr,
            # 2px de aire entre las dos columnas de un mismo mes.
            "trazo_ingreso": columna(centro - grosor - 1, ing), "trazo_egreso": columna(centro + 1, egr),
        })
    return {
        "ancho": ancho, "alto": alto, "izq": izq, "izq_texto": izq - 8, "base": base, "base_texto": base + 16,
        "derecha": ancho - 8, "columnas": columnas, "arriba": arriba, "util_alto": util_alto,
        "marcas": [{"valor": m, "y": f"{y(m):.1f}"} for m in marcas],
    }


@requiere_permiso(VER)
def analisis(request):
    organizacion = request.organizacion
    filtro = FiltroReporteForm(request.GET, organizacion=organizacion)
    v = filtro.valores()
    if not request.GET.get("desde") and v["ejercicio"]:
        # Por defecto, lo que va del ejercicio: un mes solo dice poco.
        v["desde"] = v["ejercicio"].fecha_inicio
        v["hasta"] = min(timezone.localdate(), v["ejercicio"].fecha_fin)
        filtro = FiltroReporteForm(
            {**request.GET.dict(), "desde": v["desde"].isoformat(), "hasta": v["hasta"].isoformat()},
            organizacion=organizacion,
        )
        v = filtro.valores()
    datos = services.analisis(organizacion, v["ejercicio"], v["desde"], v["hasta"], v["caja"], v["moneda"])
    return render(request, "reportes/analisis.html", {
        "a": datos, "filtro": filtro, "v": v, "simbolo": services.SIMBOLO[v["moneda"]],
        "grafico": _grafico_mensual(datos["serie"]), "consulta": _consulta_sin_formato(request),
        "presupuestos": Presupuesto.objects.filter(organizacion=organizacion, ejercicio=v["ejercicio"]).select_related("caja")
        if v["ejercicio"] else [],
    })
