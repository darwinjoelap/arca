"""La forma común de todo reporte tabular.

Cada reporte se arma UNA vez como un `Reporte` (reportes/services.py) y de ahí
salen las tres presentaciones sin repetir lógica: la pantalla
(templates/reportes/reporte.html), el Excel y el PDF (reportes/exportar.py).
Agregar un reporte es escribir una función que devuelva un `Reporte`.
"""

from dataclasses import dataclass, field

# Tipos de columna: deciden alineación y formato en las tres salidas.
TEXTO, MONTO, PORCENTAJE, ENTERO, FECHA = "texto", "monto", "pct", "entero", "fecha"

# Clases de fila.
NORMAL, GRUPO, SUBTOTAL, TOTAL, SECCION = "normal", "grupo", "subtotal", "total", "seccion"


@dataclass
class Columna:
    titulo: str
    tipo: str = TEXTO
    ancho: float = 1.0  # proporción relativa, para el PDF y el Excel

    @property
    def numerica(self):
        return self.tipo in (MONTO, PORCENTAJE, ENTERO)


@dataclass
class Fila:
    celdas: list
    clase: str = NORMAL
    sangria: int = 0
    # {índice de columna: "bien" | "mal"}: para pintar una variación favorable o no.
    tonos: dict = field(default_factory=dict)
    enlace: str = ""

    def celdas_con_tono(self):
        return [(valor, self.tonos.get(i, "")) for i, valor in enumerate(self.celdas)]


@dataclass
class Reporte:
    clave: str
    titulo: str
    subtitulo: str = ""
    columnas: list = field(default_factory=list)
    filas: list = field(default_factory=list)
    notas: list = field(default_factory=list)
    horizontal: bool = False   # PDF apaisado (muchas columnas)
    firmas: list = field(default_factory=list)  # etiquetas de líneas de firma al pie del PDF

    @property
    def vacio(self):
        return not any(f.clase == NORMAL for f in self.filas)

    def filas_para_plantilla(self):
        """[(fila, [(valor, tono, columna)])] — evita índices en la plantilla."""
        return [
            (fila, [(valor, fila.tonos.get(i, ""), self.columnas[i]) for i, valor in enumerate(fila.celdas)])
            for fila in self.filas
        ]
