# =============================================================================
# Ventana del DDMRP consolidado v1 (la usa ddmrp_consolidado_v1.py).  Hecha con Qt (PySide6).
#
# Aquí solo está CÓMO SE MUESTRA. Los datos, filtros, columnas, grupos, colores de fila,
# indicadores y fórmulas se configuran en ddmrp_consolidado_v1.py y formulas_ddmrp_v1.sql.
#
#   Barra de título   nombre del reporte, "DATOS AL" (fecha y hora en que se leyeron los datos), botón
#                     "Actualizar datos" (vuelve a leer datos y fórmulas) y filtros fijos del DDMRP (tarjetas)
#   Pestañas:
#     Datos del ítem  indicadores, filtros, botones Exportar a Excel y Excel de validación (las columnas
#                     con fórmula en el Excel original van como fórmulas de Excel y se comparan con el
#                     programa en la hoja VALIDACIÓN), leyenda de colores y la tabla
#                     (arriba de los encabezados, los grupos con botones + / - como en Excel; las
#                     columnas hasta la anclada no se mueven al desplazarse a la derecha y las dos
#                     partes de la tabla bajan juntas con UNA sola barra; clic en un encabezado para ordenar)
#     Filtros         cuántos ítems deja cada filtro del DDMRP, filtros aplicados y la consulta SQL
#     Cálculos        todas las fórmulas (de formulas_ddmrp_v1.sql), en el orden en que se calculan
# =============================================================================
import datetime as dt
import os
import re
import sys
import threading
from pathlib import Path

import numpy as np
import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPalette, QPen,
                           QSyntaxHighlighter, QTextCharFormat)
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLayout, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QSplitter, QTableView, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

import ddmrp_v1_excel
import ddmrp_v1_legible

# ----------------------------------------------------------------------------- diseño
TITULO_VENTANA = "DDMRP Consolidado v1"
TITULO         = "DDMRP CONSOLIDADO · LLANTAS"
AZUL_OSCURO    = "#1F3864"     # barra de título
AZUL           = "#2F5597"     # acentos (borde de indicadores, pestaña activa, selección)
AZUL_CLARO     = "#DDEBF7"     # encabezado de la tabla
FONDO          = "#F3F5F9"     # fondo de la ventana
BLANCO         = "#FFFFFF"
GRIS_TEXTO     = "#595959"
BORDE          = "#D9DEE7"
FILA_PAR       = "#F7F9FC"     # filas sin color, alternadas
TARJETA_FONDO  = "#E2EFDA"     # tarjetas de filtros fijos
TARJETA_TEXTO  = "#375623"
LETRA          = "Segoe UI"
ANCHO_MAX_COL  = 380           # píxeles: ancho máximo de una columna (DESCRIPCION)
ALTO_FILA      = 22            # píxeles: alto de cada fila de la tabla
LINEAS_ENCABEZADO = 5          # máximo de líneas del encabezado (texto ajustado, como en el Excel)
COLORES_TARJETAS = ["#2F5597", "#7F7F7F", "#31859C", "#8064A2", "#FFC000", "#00B050"]   # borde de cada indicador
DECIMALES      = 2             # los números se muestran con 2 decimales (se ordena con el valor completo)
TODAS          = "(Todas)"
VACIO          = "(Vacío)"         # en los filtros: los ítems sin valor en esa columna
MAX_PARTE_FIJA = 0.6           # la parte anclada ocupa como máximo este % del ancho (si no, tiene su barra)
ALTO_BARRA_GRUPOS = 22         # franja de arriba de los encabezados con los botones + / - de los grupos
CARPETA_REPORTES  = Path(__file__).resolve().parent.parent / "REPORTES DDMRP"   # Exportar a Excel
NOMBRE_EXCEL      = "Reporte de Pedidos Consolidado v1 (NEUMATICOS) (TODAS) ({fecha}).xlsx"
NOMBRE_VALIDACION = "Validacion formulas Excel vs programa - DDMRP Consolidado v1 ({fecha}).xlsx"

OPCIONES_DECIMALES = ["2", "4", "Todos"]   # selector "Decimales" de la ventana

ESTILO = f"""
QMainWindow, QWidget#fondo {{ background: {FONDO}; }}
QWidget {{ font-family: "{LETRA}"; font-size: 9pt; color: #1F1F1F; }}
QFrame#barra {{ background: {AZUL_OSCURO}; }}
QFrame#barra QLabel {{ color: white; background: transparent; }}
QLabel#titulo {{ font-size: 16pt; font-weight: bold; }}
QLabel#subtitulo {{ color: #BDD7EE; }}
QFrame#cajaFecha {{ background: {AZUL}; border-radius: 4px; }}
QLabel#chico {{ color: #BDD7EE; font-size: 7pt; font-weight: bold; }}
QLabel#fecha {{ font-size: 12pt; font-weight: bold; }}
QFrame#fijo {{ background: {TARJETA_FONDO}; border-radius: 4px; }}
QFrame#barra QFrame#fijo QLabel {{ color: {TARJETA_TEXTO}; }}
QLabel#fijoTitulo {{ font-size: 7pt; font-weight: bold; }}
QLabel#fijoValor {{ font-size: 10pt; font-weight: bold; }}

QTabWidget::pane {{ border: 1px solid {BORDE}; background: {FONDO}; top: -1px; }}
QTabBar::tab {{ background: #E4E8F0; padding: 7px 18px; font-weight: bold; border: 1px solid {BORDE};
               border-bottom: none; margin-right: 2px; border-top-left-radius: 5px; border-top-right-radius: 5px; }}
QTabBar::tab:selected {{ background: {FONDO}; color: {AZUL}; }}
QTabBar::tab:!selected:hover {{ background: #EEF2F8; }}

QFrame#tarjeta {{ background: white; border: 1px solid {BORDE}; border-left: 4px solid {AZUL}; border-radius: 4px; }}
QFrame#tarjeta QLabel {{ border: none; background: transparent; }}
QLabel#tarjetaTitulo {{ color: {GRIS_TEXTO}; font-size: 8pt; font-weight: bold; }}
QLabel#tarjetaValor {{ font-size: 15pt; font-weight: bold; }}
QFrame#panel {{ background: white; border: 1px solid {BORDE}; border-radius: 4px; }}
QFrame#panel QLabel {{ border: none; background: transparent; }}
QLabel#campo {{ color: {GRIS_TEXTO}; font-size: 8pt; font-weight: bold; }}
QLabel#tarjetaNota {{ color: {GRIS_TEXTO}; font-size: 8pt; }}
QLineEdit#buscar {{ padding: 5px 10px; font-size: 10pt; border-radius: 5px; }}
QComboBox[activo="true"], QLineEdit[activo="true"] {{ background: #FFF8E1; border: 2px solid #F1C232; }}
QLabel#contador {{ background: #FFF2CC; color: #7A5C00; border: 1px solid #F1C232; border-radius: 10px;
                  padding: 2px 10px; font-weight: bold; }}
QFrame#separador {{ background: {BORDE}; }}
QFrame#leyenda {{ background: white; border: 1px solid {BORDE}; border-radius: 10px; }}
QFrame#leyenda QLabel {{ border: none; background: transparent; color: #404040; }}
QLabel#gris {{ color: {GRIS_TEXTO}; }}
QLabel#seccion {{ font-size: 11pt; font-weight: bold; }}

QLineEdit, QComboBox {{ padding: 3px 6px; border: 1px solid #C8CFDA; border-radius: 4px; background: white;
                       min-height: 20px; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {AZUL}; }}
QComboBox QAbstractItemView {{ selection-background-color: {AZUL}; selection-color: white; }}
QPushButton {{ padding: 5px 14px; border: 1px solid #B4BCCB; border-radius: 4px; background: white;
              font-weight: bold; }}
QPushButton:hover {{ background: #EEF3FA; border-color: {AZUL}; }}
QPushButton#exportar {{ background: #217346; color: white; border: none; }}
QPushButton#exportar:hover {{ background: #185C37; }}
QPushButton#actualizar {{ background: #FFC000; color: #1F1F1F; border: none; font-size: 10pt; padding: 7px 16px; }}
QPushButton#actualizar:hover {{ background: #FFD966; }}
QPushButton#actualizar:disabled {{ background: #BFBFBF; color: #595959; }}

QFrame#marcoTabla {{ background: white; border: 1px solid #C9D2E0; }}
QTableView, QTableWidget {{ background: white; gridline-color: #E3E7EE; border: none;
                            selection-background-color: {AZUL}; selection-color: white; }}
QHeaderView::section {{ background: {AZUL_CLARO}; color: #1F1F1F; font-weight: bold; padding: 2px 4px;
                        border: none; border-right: 1px solid #C2D3EA; border-bottom: 1px solid #9DB4D8; }}
QHeaderView::section:hover {{ background: #BDD7EE; }}
QFrame#ancla {{ background: #8EA9DB; }}
QPlainTextEdit {{ background: white; border: 1px solid {BORDE}; font-family: Consolas; font-size: 9pt; }}
QPlainTextEdit#formula {{ background: #FBFCFE; border: 1px solid #C5D5F0; border-radius: 4px; font-size: 11pt;
                         padding: 6px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid #8A94A6; border-radius: 3px; background: white; }}
QCheckBox::indicator:checked {{ background: {AZUL}; border-color: {AZUL}; }}
QScrollBar:vertical {{ background: #EEF1F5; width: 14px; margin: 0; border: none; }}
QScrollBar:horizontal {{ background: #EEF1F5; height: 14px; margin: 0; border: none; }}
QScrollBar::handle:vertical {{ background: #B8C2D3; min-height: 30px; border-radius: 5px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #B8C2D3; min-width: 30px; border-radius: 5px; margin: 2px; }}
QScrollBar::handle:hover {{ background: #8EA0BD; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QSplitter::handle {{ background: {BORDE}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}
QScrollArea {{ background: {FONDO}; border: none; }}

QFrame#ficha {{ background: white; border: 1px solid {BORDE}; border-radius: 6px; }}
QLabel#fichaTitulo {{ font-size: 11pt; font-weight: bold; color: {AZUL}; }}
QLabel#grande {{ font-size: 18pt; font-weight: bold; color: {AZUL_OSCURO}; }}
QLabel#paso {{ color: {AZUL}; font-size: 8pt; font-weight: bold; }}
QLabel#tag {{ background: #FFF4CE; color: #7A5C00; border-radius: 4px; padding: 3px 8px; font-size: 8pt;
             font-weight: bold; }}
QLabel#codigo {{ font-family: Consolas; font-size: 9pt; color: #5F6368; }}
QLabel#numero {{ font-size: 13pt; font-weight: bold; }}
QLabel#quita {{ color: #C00000; font-weight: bold; }}
QLabel#circulo {{ background: {AZUL}; color: white; border-radius: 13px; font-weight: bold; }}
QLabel#resultado {{ font-size: 11pt; font-weight: bold; color: {AZUL_OSCURO}; }}
QLabel#valor {{ font-family: Consolas; font-size: 10pt; }}
QLabel#resultadoValor {{ font-family: Consolas; font-size: 12pt; font-weight: bold; background: #FFF2CC;
                        border-radius: 4px; padding: 2px 8px; }}
QPushButton#chip {{ background: #E8F0FE; color: {AZUL_OSCURO}; border: 1px solid #C5D5F0; border-radius: 11px;
                   padding: 3px 11px; font-weight: normal; }}
QPushButton#chip:hover {{ background: #D2E3FC; border-color: {AZUL}; }}
QPushButton#chipOrigen {{ background: #F1F3F4; color: #3C4043; border: 1px solid #DADCE0; border-radius: 11px;
                         padding: 3px 11px; font-weight: normal; }}
QPushButton#chipQuitar {{ background: #FFF2CC; color: #5C4400; border: 1px solid #F1C232; border-radius: 11px;
                         padding: 3px 11px; }}
QPushButton#chipQuitar:hover {{ background: #FFE599; }}
QTreeWidget {{ background: white; border: 1px solid {BORDE}; }}
QTreeWidget::item {{ padding: 3px 2px; }}
QTreeWidget::item:selected {{ background: {AZUL}; color: white; }}
QToolTip {{ background: white; color: #1F1F1F; border: 1px solid {BORDE}; padding: 4px; }}
"""


def a_texto(valor, decimales=DECIMALES):
    """Cómo se ve un valor en la tabla. decimales: 2, 4 o "Todos" (el valor completo, hasta 10 decimales)."""
    if valor is None or (isinstance(valor, float) and np.isnan(valor)) or valor is pd.NaT:
        return ""
    if isinstance(valor, (bool, np.bool_)):
        return "SI" if valor else "NO"
    if isinstance(valor, (int, float, np.integer, np.floating)):
        if str(decimales) == "Todos":
            return f"{valor:,.10f}".rstrip("0").rstrip(".")
        return f"{valor:,.{int(decimales)}f}"
    if isinstance(valor, (dt.date, dt.datetime, pd.Timestamp)):
        return valor.strftime("%Y-%m-%d")
    return str(valor).strip()


def envolver(texto, ancho_px, medidas):
    """Parte el texto en líneas que quepan en ancho_px (por palabras)."""
    lineas, actual = [], ""
    for palabra in texto.split():
        prueba = f"{actual} {palabra}".strip()
        if not actual or medidas.horizontalAdvance(prueba) <= ancho_px:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    return lineas + ([actual] if actual else [])


def etiqueta(texto="", nombre=None):
    lbl = QLabel(texto)
    if nombre:
        lbl.setObjectName(nombre)
    return lbl


def tarjeta(titulo, valor="", color=None, nota=""):
    """Recuadro con un título chico, un valor grande y (opcional) una nota. color = borde izquierdo.
    Devuelve (recuadro, etiqueta del valor)."""
    caja = QFrame()
    caja.setObjectName("tarjeta")
    if color:
        caja.setStyleSheet(f"QFrame#tarjeta {{ border-left: 5px solid {color}; }}")
    capa = QVBoxLayout(caja)
    capa.setContentsMargins(14, 7, 18, 7)
    capa.setSpacing(0)
    capa.addWidget(etiqueta(titulo, "tarjetaTitulo"))
    lbl = etiqueta(valor, "tarjetaValor")
    capa.addWidget(lbl)
    if nota:
        capa.addWidget(etiqueta(nota, "tarjetaNota"))
    return caja, lbl


def tabla_simple(columnas, anchos):
    """Tabla de solo lectura (pestañas Filtros y Cálculos)."""
    tabla = QTableWidget(0, len(columnas))
    tabla.setHorizontalHeaderLabels(columnas)
    tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
    tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
    tabla.setSelectionMode(QAbstractItemView.SingleSelection)
    tabla.setAlternatingRowColors(True)
    tabla.setStyleSheet(f"alternate-background-color: {FILA_PAR};")
    tabla.verticalHeader().setVisible(False)
    tabla.verticalHeader().setDefaultSectionSize(ALTO_FILA)
    tabla.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for i, ancho in enumerate(anchos):
        tabla.setColumnWidth(i, ancho)
    tabla.horizontalHeader().setStretchLastSection(True)
    return tabla



# Ayuda de la pestaña Cálculos: si la fórmula tiene <patrón>, se explica qué significa (como en Excel).
AYUDA_SQL = [
    (r"\bCASE\b", "<b>CASE WHEN</b> condición <b>THEN</b> a <b>ELSE</b> b <b>END</b> = <b>SI</b>(condición; a; b) de Excel. "
                  "Con varios WHEN se revisan en orden y se usa el primero que se cumple."),
    (r"\bCOALESCE\s*\(", "<b>COALESCE</b>(x, 0) = si x está vacío usa 0 (como una celda vacía que cuenta como 0, "
                         "o SI.ERROR(x; 0))."),
    (r"\bNULLIF\s*\(", "<b>NULLIF</b>(b, 0) = si b es 0 lo deja vacío. Se usa al dividir: a / NULLIF(b, 0) no da error "
                       "cuando b es 0 (da vacío, y con COALESCE queda 0)."),
    (r"\bGREATEST\s*\(", "<b>GREATEST</b>(a, b) = <b>MAX</b>(a; b) de Excel: el mayor de los valores."),
    (r"\bLEAST\s*\(", "<b>LEAST</b>(a, b) = <b>MIN</b>(a; b) de Excel: el menor de los valores."),
    (r"\bPAR\s*\(", "<b>PAR</b>(x) = <b>REDONDEA.PAR</b>(x) de Excel: sube al número par siguiente (7.3 → 8, 8 → 8)."),
    (r"\bROUND\s*\(", "<b>ROUND</b>(x, n) = <b>REDONDEAR</b>(x; n) de Excel."),
    (r"\bCEIL\s*\(", "<b>CEIL</b>(x) = <b>REDONDEAR.MAS</b> al entero: 7.1 → 8."),
    (r"\bAVG\s*\(", "<b>AVG</b>(x) = <b>PROMEDIO</b> de Excel."),
    (r"\bFILTER\s*\(", "<b>MAX</b>(x) <b>FILTER (WHERE</b> condición<b>)</b> = el máximo de x, pero solo de las filas que "
                       "cumplen la condición (como MAX.SI.CONJUNTO)."),
    (r"\bOVER\s*\(", "<b>OVER (PARTITION BY</b> columna<b>)</b> = se calcula juntando las filas que tienen el mismo valor en "
                     "esa columna (por ejemplo el mismo ítem en las otras empresas), no solo la fila del ítem."),
    (r"ddmrp_parametros", "<b>(SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = N)</b> = el parámetro "
                          "número N de la tabla de parámetros del DDMRP (se cambia en esa tabla, no aquí)."),
    (r"\bAND\b|\bOR\b", "<b>AND</b> / <b>OR</b> = <b>Y</b>(…) / <b>O</b>(…) de Excel."),
    (r"\bIS\s+(NOT\s+)?NULL\b", "<b>IS NULL</b> = está vacío;  <b>IS NOT NULL</b> = tiene valor."),
    (r"<>", "<b>&lt;&gt;</b> = distinto de."),
    (r"\bUPPER\s*\(|\bTRIM\s*\(", "<b>UPPER</b>(x) = MAYUSC(x);  <b>TRIM</b>(x) = quita los espacios de los extremos."),
    (r"\|\|", "<b>a || b</b> = une textos (como &amp; en Excel)."),
]


def seccion(titulo, subtitulo=""):
    """Recuadro blanco con título (y subtítulo gris). Devuelve (recuadro, capa donde va el contenido)."""
    caja = QFrame()
    caja.setObjectName("ficha")
    capa = QVBoxLayout(caja)
    capa.setContentsMargins(16, 12, 16, 14)
    capa.setSpacing(6)
    capa.addWidget(etiqueta(titulo, "fichaTitulo"))
    if subtitulo:
        lbl = etiqueta(subtitulo, "gris")
        lbl.setWordWrap(True)
        capa.addWidget(lbl)
    return caja, capa


class BarraEmbudo(QWidget):
    """Barra horizontal: qué parte del total queda (pestaña Filtros)."""
    def __init__(self, fraccion):
        super().__init__()
        self.fraccion = max(0.0, min(1.0, fraccion))
        self.setFixedHeight(18)
        self.setMinimumWidth(160)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#E8EDF5"))
        p.drawRoundedRect(0, 2, self.width(), 14, 5, 5)
        p.setBrush(QColor(AZUL))
        p.drawRoundedRect(0, 2, max(4, int(self.width() * self.fraccion)), 14, 5, 5)
        p.end()


class FlujoLayout(QLayout):
    """Pone los elementos uno al lado del otro y pasa a la línea siguiente cuando no caben (chips)."""
    def __init__(self, espacio=6):
        super().__init__()
        self.elementos = []
        self.espacio = espacio
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.elementos.append(item)

    def count(self):
        return len(self.elementos)

    def itemAt(self, i):
        return self.elementos[i] if 0 <= i < len(self.elementos) else None

    def takeAt(self, i):
        return self.elementos.pop(i) if 0 <= i < len(self.elementos) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, ancho):
        return self._ordenar(QRect(0, 0, ancho, 0), probar=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._ordenar(rect, probar=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        tam = QSize()
        for item in self.elementos:
            tam = tam.expandedTo(item.minimumSize())
        return tam

    def _ordenar(self, rect, probar):
        x, y, alto_linea = rect.x(), rect.y(), 0
        for item in self.elementos:
            tam = item.sizeHint()
            if x + tam.width() > rect.right() and alto_linea > 0:
                x, y, alto_linea = rect.x(), y + alto_linea + self.espacio, 0
            if not probar:
                item.setGeometry(QRect(QPoint(x, y), tam))
            x += tam.width() + self.espacio
            alto_linea = max(alto_linea, tam.height())
        return y + alto_linea - rect.y()


class ResaltadorFormula(QSyntaxHighlighter):
    """Colores para la fórmula estilo Excel: [columnas], funciones, "textos", números y VACÍO."""
    def __init__(self, documento):
        super().__init__(documento)

        def formato(color, negrita=False, fondo=None):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if negrita:
                f.setFontWeight(QFont.Bold)
            if fondo:
                f.setBackground(QColor(fondo))
            return f

        self.reglas = [
            (re.compile(r"\b\d+(\.\d+)?\b"), formato("#B45F06")),
            (re.compile(r"[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ.]*(?=\()"), formato("#8E24AA", negrita=True)),
            (re.compile(r"\b(VACÍO|VERDADERO|FALSO|mismo)\b"), formato("#0B57D0", negrita=True)),
            (re.compile(r'"[^"]*"'), formato("#188038")),
            (re.compile(r"\[[^\]]*\]"), formato("#1F3864", fondo="#E8F0FE")),
            (re.compile(r"^="), formato("#0B57D0", negrita=True)),
        ]
        self.titulo = formato(AZUL_OSCURO, negrita=True)

    def highlightBlock(self, texto):
        if self.currentBlock().blockNumber() == 0:               # primera línea: el nombre de la columna
            self.setFormat(0, len(texto), self.titulo)
            return
        for patron, formato in self.reglas:
            for m in patron.finditer(texto):
                self.setFormat(m.start(), m.end() - m.start(), formato)


class ResaltadorSQL(QSyntaxHighlighter):
    """Colores para leer SQL: palabras de SQL, funciones, columnas, textos, números y comentarios."""
    def __init__(self, documento):
        super().__init__(documento)

        def formato(color, negrita=False, cursiva=False, fondo=None):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if negrita:
                f.setFontWeight(QFont.Bold)
            if cursiva:
                f.setFontItalic(True)
            if fondo:
                f.setBackground(QColor(fondo))
            return f

        palabras = ("SELECT|FROM|WHERE|WITH|AS|CASE|WHEN|THEN|ELSE|END|AND|OR|NOT|IS|NULL|IN|FILTER|OVER|PARTITION|BY|"
                    "ORDER|GROUP|MATERIALIZED|LEFT|JOIN|ON|DISTINCT|UNION|ALL|LIMIT|BETWEEN|LIKE|ILIKE|EXISTS|ASC|DESC")
        self.reglas = [
            (re.compile(rf"\b({palabras})\b", re.IGNORECASE), formato("#0B57D0", negrita=True)),
            (re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()"), formato("#8E24AA", negrita=True)),
            (re.compile(r"\b\d+(\.\d+)?\b"), formato("#B45F06")),
            (re.compile(r"'[^']*'"), formato("#188038")),
            (re.compile(r'"[^"]*"'), formato("#1F3864", fondo="#E8F0FE")),
            (re.compile(r"--.*$"), formato("#7F7F7F", cursiva=True)),
        ]

    def highlightBlock(self, texto):
        for patron, formato in self.reglas:
            for m in patron.finditer(texto):
                self.setFormat(m.start(), m.end() - m.start(), formato)


# =============================================================================
# Modelo de la tabla de datos: las filas que se ven (ya filtradas y ordenadas)
# =============================================================================
class ModeloTabla(QAbstractTableModel):
    def __init__(self, ventana):
        super().__init__()
        self.v = ventana
        self.filas, self.fondos, self.alineacion = [], [], []

    def rowCount(self, padre=QModelIndex()):
        return 0 if padre.isValid() else len(self.filas)

    def columnCount(self, padre=QModelIndex()):
        return 0 if padre.isValid() else len(self.v.columnas)

    def data(self, indice, rol=Qt.DisplayRole):
        if rol == Qt.DisplayRole:
            return self.filas[indice.row()][indice.column()]
        if rol == Qt.BackgroundRole:
            return self.fondos[indice.row()]
        if rol == Qt.TextAlignmentRole:
            return self.alineacion[indice.column()]
        return None

    def headerData(self, seccion, orientacion, rol=Qt.DisplayRole):
        if orientacion != Qt.Horizontal:
            return None
        if rol == Qt.DisplayRole:
            return self.v.texto_encabezado(seccion)
        if rol == Qt.ToolTipRole:
            return self.v.columnas[seccion] + "\n(clic para ordenar)"
        return None

    def cargar(self, filas, fondos):
        """Cambia las filas sin reiniciar la tabla (se mantienen anchos, columnas ocultas y posición)."""
        antes, ahora = len(self.filas), len(filas)
        if ahora < antes:
            self.beginRemoveRows(QModelIndex(), ahora, antes - 1)
            self.filas, self.fondos = filas, fondos
            self.endRemoveRows()
        elif ahora > antes:
            self.beginInsertRows(QModelIndex(), antes, ahora - 1)
            self.filas, self.fondos = filas, fondos
            self.endInsertRows()
        else:
            self.filas, self.fondos = filas, fondos
        if ahora:
            self.dataChanged.emit(self.index(0, 0), self.index(ahora - 1, self.columnCount() - 1))


# =============================================================================
# Franja de grupos (arriba de los encabezados): botones + / - como en Excel
# =============================================================================
class FranjaGrupos(QWidget):
    def __init__(self, ventana, vista, columnas_tabla):
        super().__init__()
        self.v, self.vista, self.columnas_tabla = ventana, vista, columnas_tabla
        self.botones = []
        self.setFixedHeight(ALTO_BARRA_GRUPOS)
        self.setMouseTracking(True)

    def paintEvent(self, _):
        """Grupo abierto = línea sobre sus columnas que termina en un botón [-]; grupo cerrado = botón [+].
        El botón va sobre la columna que sigue al grupo."""
        v, encabezado = self.v, self.vista.horizontalHeader()
        posicion = {}
        for col in self.columnas_tabla:
            i = v.pos[col]
            if not encabezado.isSectionHidden(i):
                x0 = encabezado.sectionViewportPosition(i)
                posicion[col] = (x0, x0 + encabezado.sectionSize(i))
        self.botones = []
        if not posicion:
            return
        fin = max(x1 for _, x1 in posicion.values())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = ALTO_BARRA_GRUPOS // 2
        p.setPen(QPen(QColor("#7F7F7F"), 1))
        for g in v.grupos:
            if g["columnas"][0] not in self.columnas_tabla:
                continue
            ultima = v.pos[g["columnas"][-1]]
            siguiente = next((c for c in v.columnas[ultima + 1:] if c in posicion), None)
            propias = [c for c in g["columnas"] if c in posicion]
            if siguiente is not None:
                xb = posicion[siguiente][0] + 10
            elif propias:
                xb = posicion[propias[-1]][1] - 10
            else:
                xb = fin - 10
            if g["abierto"] and propias:
                x0 = posicion[propias[0]][0] + 3
                p.drawLine(x0, y, xb - 7, y)
                p.drawLine(x0, y, x0, y + 6)
            self.botones.append((QRect(xb - 7, y - 7, 14, 14), g))
        fuente = QFont(LETRA, 9, QFont.Bold)
        p.setFont(fuente)
        for rect, g in self.botones:                                  # botones encima de las líneas
            p.setBrush(QColor(BLANCO))
            p.setPen(QPen(QColor("#7F7F7F"), 1))
            p.drawRect(rect)
            p.setPen(QColor("#404040"))
            p.drawText(rect, Qt.AlignCenter, "-" if g["abierto"] else "+")
        p.end()

    def _grupo_en(self, punto):
        return next((g for rect, g in self.botones if rect.adjusted(-2, -2, 2, 2).contains(punto)), None)

    def mousePressEvent(self, evento):
        g = self._grupo_en(evento.position().toPoint())
        if g is not None:
            self.v.abrir_cerrar(g)

    def mouseMoveEvent(self, evento):
        g = self._grupo_en(evento.position().toPoint())
        self.setCursor(Qt.PointingHandCursor if g else Qt.ArrowCursor)
        if g:
            self.v.estado.setText(f"Grupo de columnas: {g['nombre']}  (clic para abrir / cerrar)")
        else:
            self.v._texto_estado()

    def leaveEvent(self, _):
        self.v._texto_estado()


class MarcoTabla(QFrame):
    """Marco de la tabla: al cambiar de tamaño vuelve a calcular el ancho de la parte anclada."""
    def __init__(self, al_cambiar):
        super().__init__()
        self.setObjectName("marcoTabla")
        self.al_cambiar = al_cambiar

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self.al_cambiar()


class VentanaDDMRP:
    def __init__(self, df, embudo, filtros_ddmrp, sql, formulas, grupos_columnas, filtros_ventana,
                 columnas_ocultas=(), colores_fila=(), indicadores=(), columna_ancla=None, recargar=None,
                 formulas_excel=None):
        """recargar: función que vuelve a leer todo (datos del ítem y cálculos) y devuelve
        (df, embudo, sql, formulas). La usa el botón 'Actualizar datos'.
        formulas_excel: {columna: fórmula de Excel} para el botón 'Excel de validación'."""
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setStyle("Fusion")
        try:
            self.app.styleHints().setColorScheme(Qt.ColorScheme.Light)
        except AttributeError:
            pass
        paleta = QPalette()                                      # colores claros aunque Windows esté en modo oscuro
        for rol, color in ((QPalette.Window, FONDO), (QPalette.WindowText, "#1F1F1F"), (QPalette.Base, BLANCO),
                           (QPalette.AlternateBase, FILA_PAR), (QPalette.Text, "#1F1F1F"), (QPalette.Button, BLANCO),
                           (QPalette.ButtonText, "#1F1F1F"), (QPalette.Highlight, AZUL), (QPalette.HighlightedText, BLANCO),
                           (QPalette.ToolTipBase, BLANCO), (QPalette.ToolTipText, "#1F1F1F"),
                           (QPalette.PlaceholderText, "#8A8A8A"), (QPalette.Light, BLANCO), (QPalette.Midlight, "#E3E7EE"),
                           (QPalette.Mid, "#C8CFDA"), (QPalette.Dark, "#A0A8B5"), (QPalette.Shadow, "#7F7F7F")):
            paleta.setColor(rol, QColor(color))
        self.app.setPalette(paleta)
        self.app.setFont(QFont(LETRA, 9))
        self.app.setStyleSheet(ESTILO)

        self.recargar = recargar
        self.formulas_excel = dict(formulas_excel or {})
        self.filtros_ddmrp = filtros_ddmrp
        self.colores_fila = list(colores_fila)
        self.decimales_actual = str(DECIMALES)
        self._cargar(df, embudo, sql, formulas, DECIMALES)
        self.pos = {c: i for i, c in enumerate(self.columnas)}
        self.filtros_ventana = [(e, c) for e, c in filtros_ventana if c in self.columnas]
        self.ocultas = [c for c in columnas_ocultas if c in self.columnas]
        self.indicadores = [i for i in indicadores if i[1] in self.columnas]
        self.grupos = []
        for g in grupos_columnas:
            cols = [c for c in g["columnas"] if c in self.columnas]
            posiciones = [self.columnas.index(c) for c in cols]
            if not cols or posiciones != list(range(posiciones[0], posiciones[0] + len(cols))):
                raise ValueError(f"Grupo '{g['nombre']}': sus columnas deben existir y estar seguidas")
            self.grupos.append({"nombre": g["nombre"], "columnas": cols, "abierto": g.get("abierto", False)})
        # columnas ancladas: desde la primera hasta columna_ancla (no se mueven con la barra horizontal)
        self.columna_ancla = columna_ancla if columna_ancla in self.columnas else None
        corte = self.columnas.index(self.columna_ancla) + 1 if self.columna_ancla else 0
        self.fijas, self.moviles = self.columnas[:corte], self.columnas[corte:]
        for g in self.grupos:
            if set(g["columnas"]) & set(self.fijas) and set(g["columnas"]) & set(self.moviles):
                raise ValueError(f"Grupo '{g['nombre']}': no puede quedar partido por la columna anclada")
        self.orden = {}                                          # columna -> True si está descendente
        self._pausa = False                                      # evita filtrar varias veces al limpiar
        self._actualizando = False
        self.encabezados = {}                                    # columna -> líneas del encabezado

        self.root = QMainWindow()
        self.root.setWindowTitle(TITULO_VENTANA)
        self.root.resize(1450, 820)
        central = QWidget()
        central.setObjectName("fondo")
        self.root.setCentralWidget(central)
        capa = QVBoxLayout(central)
        capa.setContentsMargins(0, 0, 0, 0)
        capa.setSpacing(0)

        capa.addWidget(self._barra_titulo())
        self.pestanas = QTabWidget()
        cuerpo = QWidget()
        capa_cuerpo = QVBoxLayout(cuerpo)
        capa_cuerpo.setContentsMargins(10, 8, 10, 10)
        capa_cuerpo.addWidget(self.pestanas)
        capa.addWidget(cuerpo, 1)
        self.tab_datos, self.tab_filtros, self.tab_calculos = QWidget(), QWidget(), QWidget()
        for tab in (self.tab_datos, self.tab_filtros, self.tab_calculos):
            QVBoxLayout(tab).setContentsMargins(10, 10, 10, 8)
        self.pestanas.addTab(self.tab_datos, "Datos del ítem")
        self.pestanas.addTab(self.tab_filtros, "Filtros")
        self.pestanas.addTab(self.tab_calculos, "Cálculos")

        self._pestana_datos()
        self._contenido_filtros = self._contenido_calculos = None
        self._pestana_filtros()
        self._pestana_calculos()
        self.filtrar()

    def _cargar(self, df, embudo, sql, formulas, decimales):
        """Guarda los datos en la ventana: valores, textos, columnas numéricas, color de cada fila y la hora."""
        self.datos = df.reset_index(drop=True)                  # valores originales (para ordenar y sumar)
        self.columnas = list(self.datos.columns)
        self.embudo, self.sql, self.formulas = embudo, sql, formulas
        self.fecha_datos = dt.datetime.now()                     # cuándo se leyeron los datos
        self._preparar_textos(decimales)                         # lo que se ve
        # columnas "numéricas": la mayoría de sus valores son números (a la derecha y se ordenan como número)
        self.numericas = [c for c in self.columnas
                          if pd.to_numeric(self.datos[c], errors="coerce").notna().mean() > 0.5
                          and not self.datos[c].map(lambda v: isinstance(v, (bool, np.bool_))).any()]
        # color de cada fila (el último que se cumple gana, como en el Excel)
        self.color_fila = pd.Series("", index=self.datos.index)
        for nombre, _, _, condicion in self.colores_fila:
            self.color_fila[condicion(self.datos).fillna(False).values] = nombre

    def _preparar_textos(self, decimales):
        """Texto de cada celda (con los decimales elegidos) y el texto para el buscador (columna por columna: rápido)."""
        textos = {}
        for col in self.datos.columns:
            serie = self.datos[col]
            if pd.api.types.is_float_dtype(serie) or pd.api.types.is_integer_dtype(serie):
                if str(decimales) == "Todos":
                    textos[col] = serie.map(lambda v: "" if v != v else f"{v:,.10f}".rstrip("0").rstrip("."))
                else:
                    formato = f"{{:,.{int(decimales)}f}}"
                    textos[col] = serie.map(lambda v: "" if v != v else formato.format(v))
            else:
                textos[col] = serie.map(lambda v: a_texto(v, decimales))
        self.textos = pd.DataFrame(textos, index=self.datos.index)
        busqueda = self.textos[self.columnas[0]]
        for col in self.columnas[1:]:
            busqueda = busqueda + " | " + self.textos[col]
        self.busqueda = busqueda.str.upper()

    def cambiar_decimales(self):
        """Selector 'Decimales': vuelve a escribir la tabla con 2, 4 o todos los decimales (no recalcula)."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            self._preparar_textos(self.decimales.currentText())
        finally:
            QApplication.restoreOverrideCursor()
        self.filtrar()

    # =========================================================================
    # Barra de título
    # =========================================================================
    def _barra_titulo(self):
        barra = QFrame()
        barra.setObjectName("barra")
        capa = QHBoxLayout(barra)
        capa.setContentsMargins(18, 10, 18, 10)
        izquierda = QVBoxLayout()
        izquierda.setSpacing(0)
        izquierda.addWidget(etiqueta(TITULO, "titulo"))
        self.lbl_subtitulo = etiqueta("", "subtitulo")
        izquierda.addWidget(self.lbl_subtitulo)
        capa.addLayout(izquierda)
        capa.addSpacing(40)
        # fecha y hora de los datos + botón para volver a leerlos
        caja = QFrame()
        caja.setObjectName("cajaFecha")
        capa_caja = QVBoxLayout(caja)
        capa_caja.setContentsMargins(12, 3, 12, 4)
        capa_caja.setSpacing(0)
        capa_caja.addWidget(etiqueta("DATOS AL", "chico"))
        self.lbl_fecha = etiqueta("", "fecha")
        capa_caja.addWidget(self.lbl_fecha)
        capa.addWidget(caja)
        self.boton_actualizar = QPushButton("⟳  Actualizar datos")
        self.boton_actualizar.setObjectName("actualizar")
        self.boton_actualizar.setCursor(Qt.PointingHandCursor)
        self.boton_actualizar.setEnabled(bool(self.recargar))
        self.boton_actualizar.clicked.connect(self.actualizar)
        capa.addSpacing(10)
        capa.addWidget(self.boton_actualizar)
        self._mostrar_fecha()
        capa.addStretch(1)
        # tarjetas con los filtros fijos del DDMRP (ya vienen filtrados desde la consulta)
        lbl = etiqueta("Filtros fijos:", "subtitulo")
        lbl.setStyleSheet("font-weight: bold;")
        capa.addWidget(lbl)
        for f in self.filtros_ddmrp:
            caja = QFrame()
            caja.setObjectName("fijo")
            capa_f = QVBoxLayout(caja)
            capa_f.setContentsMargins(10, 3, 10, 4)
            capa_f.setSpacing(0)
            capa_f.addWidget(etiqueta("✔ " + f["tarjeta"], "fijoTitulo"))
            capa_f.addWidget(etiqueta(f["valor"], "fijoValor"))
            capa.addSpacing(8)
            capa.addWidget(caja)
        return barra

    def _mostrar_fecha(self):
        self.lbl_fecha.setText(f"{self.fecha_datos:%d/%m/%Y  %H:%M:%S}")
        self.lbl_subtitulo.setText(f"Solo lectura  ·  {len(self.datos):,} ítems  ·  {len(self.formulas)} fórmulas")

    # =========================================================================
    # Actualizar datos: vuelve a leer los datos del ítem y a hacer los cálculos
    # (también toma los cambios de formulas_ddmrp_v1.sql). Mantiene filtros, orden, grupos y decimales.
    # =========================================================================
    def actualizar(self):
        if not self.recargar or self._actualizando:
            return
        self._actualizando = True
        self.boton_actualizar.setEnabled(False)
        self.boton_actualizar.setText("⟳  Actualizando...")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.estado.setText("Actualizando datos: leyendo el DWH y haciendo los cálculos...")
        resultado = {}

        def leer():                                              # en segundo plano: la ventana no se congela
            try:
                resultado["datos"] = self.recargar()
            except BaseException as error:                       # incluye sys.exit de errores de fórmulas
                resultado["error"] = error

        hilo = threading.Thread(target=leer, daemon=True)
        hilo.start()

        def esperar():
            if hilo.is_alive():
                QTimer.singleShot(200, esperar)
                return
            QApplication.restoreOverrideCursor()
            try:
                if "error" in resultado:
                    QMessageBox.critical(self.root, "Actualizar datos", f"No se pudo actualizar (los datos de antes "
                                                                        f"siguen en pantalla):\n\n{resultado['error']}")
                    return
                df, embudo, sql, formulas = resultado["datos"]
                faltan = [c for c in self.columnas if c not in df.columns]
                if faltan:
                    QMessageBox.critical(self.root, "Actualizar datos", f"Faltan columnas del reporte: {faltan}")
                    return
                self.estado.setText("Actualizando datos: preparando la tabla...")
                QApplication.processEvents()
                self._cargar(df[self.columnas], embudo, sql, formulas, self.decimales.currentText())
                self.modelo.alineacion = self._alineaciones()
                self._pestana_filtros()
                self._pestana_calculos()
                self._mostrar_fecha()
                self.filtrar()                                   # con los filtros y el orden que estaban
            finally:
                self._actualizando = False
                self.boton_actualizar.setEnabled(True)
                self.boton_actualizar.setText("⟳  Actualizar datos")
                self._texto_estado()

        esperar()

    # =========================================================================
    # Pestaña 1: Datos del ítem
    # =========================================================================
    def _indicadores(self, capa):
        """Tarjetas de arriba: ocupan todo el ancho, cada una con su color."""
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.lbl_indicador = {}
        caja, self.lbl_mostrados = tarjeta("ÍTEMS MOSTRADOS", color=COLORES_TARJETAS[0], nota="con los filtros de abajo")
        self.lbl_mostrados.setMinimumWidth(QFontMetrics(QFont(LETRA, 15, QFont.Bold)).horizontalAdvance(
            f"{len(self.datos):,} de {len(self.datos):,}") + 12)
        fila.addWidget(caja, 1)
        for k, (titulo, columna, tipo) in enumerate(self.indicadores, start=1):
            nota = "ítems con valor mayor a 0" if tipo == "items" else "unidades (suma)"
            caja, lbl = tarjeta(titulo.upper(), color=COLORES_TARJETAS[k % len(COLORES_TARJETAS)], nota=nota)
            caja.setToolTip(f"{columna}: {nota}")
            fila.addWidget(caja, 1)
            self.lbl_indicador[(titulo, columna, tipo)] = lbl
        capa.addLayout(fila)

    def _panel_filtros(self, capa):
        """Dos filas:  1) buscador + opciones + botones   2) los filtros por columna, todos del mismo ancho."""
        panel = QFrame()
        panel.setObjectName("panel")
        capa_panel = QVBoxLayout(panel)
        capa_panel.setContentsMargins(14, 10, 14, 10)
        capa_panel.setSpacing(8)

        # fila 1
        fila = QHBoxLayout()
        fila.setSpacing(8)
        self.texto = QLineEdit()
        self.texto.setObjectName("buscar")
        self.texto.setPlaceholderText("🔍  Buscar en todo: código, descripción, marca, proveedor...")
        self.texto.setClearButtonEnabled(True)
        self.texto.setMinimumWidth(320)
        self.texto.textChanged.connect(lambda _: self.filtrar())
        fila.addWidget(self.texto, 3)
        self.lbl_activos = etiqueta("", "contador")
        self.lbl_activos.setVisible(False)
        fila.addWidget(self.lbl_activos)
        boton = QPushButton("✕  Limpiar filtros")
        boton.clicked.connect(self.limpiar)
        fila.addWidget(boton)
        fila.addSpacing(6)
        fila.addWidget(self._separador())
        fila.addSpacing(6)
        fila.addWidget(etiqueta("DECIMALES", "campo"))
        self.decimales = QComboBox()
        self.decimales.addItems(OPCIONES_DECIMALES)
        self.decimales.setCurrentText(str(DECIMALES))
        self.decimales.setToolTip("Cuántos decimales se ven (el cálculo siempre usa todos)")
        self.decimales.currentTextChanged.connect(lambda _: self.cambiar_decimales())
        fila.addWidget(self.decimales)
        fila.addSpacing(8)
        self.ver_ocultas = QCheckBox("Mostrar columnas ocultas")
        self.ver_ocultas.toggled.connect(lambda _: self.aplicar_columnas())
        fila.addWidget(self.ver_ocultas)
        fila.addStretch(1)
        fila.addWidget(self._separador())
        fila.addSpacing(6)
        boton = QPushButton("Exportar a Excel")
        boton.setObjectName("exportar")
        boton.setToolTip("Guarda lo que se ve (filtros y orden actuales) con el formato del Excel final")
        boton.clicked.connect(lambda: self.exportar())
        fila.addWidget(boton)
        if self.formulas_excel:
            boton = QPushButton("Excel de validación")
            boton.setToolTip("Excel con las fórmulas del Excel original y la hoja VALIDACIÓN (fórmula de Excel vs programa)")
            boton.clicked.connect(lambda: self.exportar(validacion=True))
            fila.addWidget(boton)
        capa_panel.addLayout(fila)

        # fila 2: filtros por columna
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(10)
        rejilla.setVerticalSpacing(3)
        self.filtros = {}                                        # columna -> (ComboBox, valores de la lista)
        for i, (nombre, columna) in enumerate(self.filtros_ventana):
            rejilla.addWidget(etiqueta(nombre.upper(), "campo"), 0, i)
            combo = QComboBox()
            combo.setEditable(True)                              # también se puede escribir
            combo.setCompleter(None)
            combo.setInsertPolicy(QComboBox.NoInsert)
            combo.setMaxVisibleItems(25)
            combo.view().setTextElideMode(Qt.ElideNone)
            combo.setMinimumContentsLength(6)
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setToolTip(f"Filtrar por {columna}: elige de la lista o escribe (parte del texto)")
            combo.addItem(TODAS)
            combo.setEditText(TODAS)
            combo.currentTextChanged.connect(lambda _: self.filtrar())
            rejilla.addWidget(combo, 1, i)
            rejilla.setColumnStretch(i, 1)
            self.filtros[columna] = [combo, [TODAS]]
        capa_panel.addLayout(rejilla)
        capa.addWidget(panel)

    @staticmethod
    def _separador():
        linea = QFrame()
        linea.setObjectName("separador")
        linea.setFixedSize(1, 26)
        return linea

    def _marcar_filtros(self):
        """Resalta en amarillo los filtros que están puestos y muestra cuántos son."""
        activos = 0
        for campo, valor in [(self.texto, self.texto.text())] + [(c, c.currentText()) for c, _ in self.filtros.values()]:
            activo = bool(valor.strip()) and valor.strip().upper() != TODAS.upper()
            activos += activo
            if campo.property("activo") != activo:
                campo.setProperty("activo", activo)
                campo.style().unpolish(campo)
                campo.style().polish(campo)
        self.lbl_activos.setText(f"{activos} filtro{'s' if activos != 1 else ''} activo{'s' if activos != 1 else ''}")
        self.lbl_activos.setVisible(activos > 0)

    def _leyenda(self, capa):
        """Colores de fila como etiquetas (la explicación completa sale al pasar el mouse)."""
        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(etiqueta("COLOR DE FILA", "campo"))
        for nombre, color, explicacion, _ in self.colores_fila:
            chip = QFrame()
            chip.setObjectName("leyenda")
            chip.setToolTip(f"{nombre}: {explicacion}")
            capa_chip = QHBoxLayout(chip)
            capa_chip.setContentsMargins(8, 3, 10, 3)
            capa_chip.setSpacing(6)
            muestra = QLabel()
            muestra.setFixedSize(14, 14)
            muestra.setStyleSheet(f"background: {color}; border: 1px solid #7F7F7F; border-radius: 3px;")
            capa_chip.addWidget(muestra)
            texto = QLabel(f"<b>{nombre}</b>  {explicacion}")
            capa_chip.addWidget(texto)
            fila.addWidget(chip)
        fila.addStretch(1)
        capa.addLayout(fila)

    def _nueva_vista(self):
        vista = QTableView()
        vista.setModel(self.modelo)
        vista.setFrameShape(QFrame.NoFrame)
        vista.verticalHeader().setVisible(False)
        vista.verticalHeader().setDefaultSectionSize(ALTO_FILA)
        vista.verticalHeader().setMinimumSectionSize(ALTO_FILA)
        vista.setSelectionBehavior(QAbstractItemView.SelectRows)
        vista.setSelectionMode(QAbstractItemView.ExtendedSelection)
        vista.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        vista.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        vista.setWordWrap(False)
        vista.setTextElideMode(Qt.ElideRight)
        vista.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # las dos tablas tienen barra horizontal: así su alto útil es igual y bajan exactamente juntas
        vista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        encabezado = vista.horizontalHeader()
        encabezado.setSectionResizeMode(QHeaderView.Interactive)
        encabezado.setHighlightSections(False)
        encabezado.setSectionsClickable(True)
        encabezado.setDefaultAlignment(Qt.AlignCenter | Qt.TextWordWrap)
        encabezado.setMinimumSectionSize(36)
        encabezado.sectionClicked.connect(lambda i: self.ordenar(self.columnas[i]))
        return vista

    def _tabla_datos(self, capa):
        """Una tabla partida en dos que comparten los datos, la selección y la barra vertical:
             izquierda = columnas ANCLADAS (no se mueven con la barra horizontal)
             derecha   = el resto (con barra horizontal)
           Arriba de cada parte, la franja de grupos con los botones + / - como en Excel."""
        self.modelo = ModeloTabla(self)
        self.modelo.alineacion = self._alineaciones()
        self.vista_izq, self.vista_der = self._nueva_vista(), self._nueva_vista()
        self.vista_der.setSelectionModel(self.vista_izq.selectionModel())       # misma selección
        self.vista_izq.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)       # una sola barra vertical
        self.vista_der.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.vista_izq.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        barra_izq, barra_der = self.vista_izq.verticalScrollBar(), self.vista_der.verticalScrollBar()
        barra_izq.valueChanged.connect(barra_der.setValue)                     # bajan juntas (al mismo pixel)
        barra_der.valueChanged.connect(barra_izq.setValue)

        self.franja_izq = FranjaGrupos(self, self.vista_izq, self.fijas)
        self.franja_der = FranjaGrupos(self, self.vista_der, self.moviles)
        for vista, franja in ((self.vista_izq, self.franja_izq), (self.vista_der, self.franja_der)):
            vista.horizontalHeader().sectionResized.connect(lambda *_: self._redibujar())
            vista.horizontalScrollBar().valueChanged.connect(lambda _, f=franja: f.update())

        marco = MarcoTabla(self._redibujar)
        rejilla = QGridLayout(marco)
        rejilla.setContentsMargins(0, 0, 0, 0)
        rejilla.setSpacing(0)
        ancla = QFrame()
        ancla.setObjectName("ancla")
        ancla.setFixedWidth(3)                                                  # línea del anclaje
        rejilla.addWidget(self.franja_izq, 0, 0)
        rejilla.addWidget(self.franja_der, 0, 2)
        rejilla.addWidget(self.vista_izq, 1, 0)
        rejilla.addWidget(ancla, 1, 1)
        rejilla.addWidget(self.vista_der, 1, 2)
        rejilla.setColumnStretch(2, 1)
        rejilla.setRowStretch(1, 1)
        capa.addWidget(marco, 1)

    def _alineaciones(self):
        derecha, izquierda = Qt.AlignRight | Qt.AlignVCenter, Qt.AlignLeft | Qt.AlignVCenter
        return [derecha if c in self.numericas else izquierda for c in self.columnas]

    def _anchos_y_encabezados(self):
        """Ancho de cada columna (según su contenido) y encabezado en varias líneas, como en el Excel."""
        normal = QFontMetrics(QFont(LETRA, 9))
        negrita = QFontMetrics(QFont(LETRA, 9, QFont.Bold))
        self.encabezados = {}
        for col in self.columnas:
            mas_largo = max([""] + list(self.textos[col]), key=len)
            palabra = max(col.split(), key=lambda p: negrita.horizontalAdvance(p))
            ancho = max(normal.horizontalAdvance(mas_largo) + 20, negrita.horizontalAdvance(palabra) + 18, 48)
            ancho = min(ancho, ANCHO_MAX_COL)
            lineas = envolver(col, ancho - 12, negrita)
            while len(lineas) > LINEAS_ENCABEZADO and ancho < ANCHO_MAX_COL:
                ancho += 10
                lineas = envolver(col, ancho - 12, negrita)
            self.encabezados[col] = lineas
            for vista in (self.vista_izq, self.vista_der):
                vista.setColumnWidth(self.pos[col], ancho)
        alto = max(len(l) for l in self.encabezados.values()) * negrita.height() + 10
        for vista in (self.vista_izq, self.vista_der):
            vista.horizontalHeader().setFixedHeight(alto)

    def texto_encabezado(self, seccion):
        col = self.columnas[seccion]
        lineas = list(self.encabezados.get(col, [col]))
        if col in self.orden:
            lineas[-1] += " ▼" if self.orden[col] else " ▲"
        return "\n".join(lineas)

    def _redibujar(self):
        """Ancho de la parte anclada (lo que miden sus columnas visibles, máximo MAX_PARTE_FIJA del ancho:
        si no entra, tiene su propia barra horizontal) y franjas de grupos."""
        if not hasattr(self, "franja_der"):
            return
        ancho = self.vista_izq.horizontalHeader().length() + 2 * self.vista_izq.frameWidth()
        disponible = self.vista_izq.parentWidget().width()
        if disponible > 200:
            ancho = min(ancho, int(disponible * MAX_PARTE_FIJA))
        if self.vista_izq.width() != ancho:
            self.vista_izq.setFixedWidth(ancho)
            self.franja_izq.setFixedWidth(ancho)
        self.franja_izq.update()
        self.franja_der.update()

    def _pestana_datos(self):
        capa = self.tab_datos.layout()
        capa.setSpacing(8)
        self._indicadores(capa)
        self._panel_filtros(capa)
        self._leyenda(capa)
        self._tabla_datos(capa)
        self._anchos_y_encabezados()
        self.aplicar_columnas()
        pie = QHBoxLayout()
        self.estado = etiqueta("", "gris")
        pie.addWidget(self.estado)
        pie.addStretch(1)
        pie.addWidget(etiqueta("[+] abre un grupo de columnas · [-] lo cierra · clic en un encabezado para ordenar · "
                               "arrastra el borde de un encabezado para cambiar el ancho", "gris"))
        capa.addLayout(pie)
        self.vista_izq.selectionModel().currentRowChanged.connect(self._fila_elegida)
        self.texto.setFocus()

    # =========================================================================
    # Pestaña 2: Filtros (se vuelve a armar al actualizar los datos)
    #   1. ¿Qué ítems entran al reporte?  embudo de los filtros fijos del DDMRP
    #   2. Lo que estás viendo ahora       filtros puestos en 'Datos del ítem' (✕ para quitarlos)
    #   3. Consulta SQL                    la consulta completa, con colores, para copiar a pgAdmin
    # =========================================================================
    def _reemplazar(self, tab, anterior):
        if anterior is not None:
            tab.layout().removeWidget(anterior)
            anterior.deleteLater()
        nuevo = QWidget()
        capa = QVBoxLayout(nuevo)
        capa.setContentsMargins(0, 0, 0, 0)
        tab.layout().addWidget(nuevo)
        return nuevo, capa

    def _pestana_filtros(self):
        self._contenido_filtros, capa_tab = self._reemplazar(self.tab_filtros, self._contenido_filtros)
        desplazable = QScrollArea()
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.NoFrame)
        hoja = QWidget()
        hoja.setObjectName("fondo")
        capa = QVBoxLayout(hoja)
        capa.setContentsMargins(4, 4, 12, 4)
        capa.setSpacing(12)
        desplazable.setWidget(hoja)
        capa_tab.addWidget(desplazable)

        # --- 1. embudo ---
        ficha, cuerpo = seccion("1.  ¿Qué ítems entran al reporte?",
                                "Filtros fijos del DDMRP. Se aplican en la consulta a core.dim_item, uno tras otro: "
                                "cada barra muestra cuántos ítems quedan después de ese filtro.")
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(14)
        rejilla.setVerticalSpacing(10)
        total = max(self.embudo[0], 1)
        pasos = [("", "Todos los ítems", "core.dim_item completo", "", self.embudo[0], None)]
        for i, (f, n) in enumerate(zip(self.filtros_ddmrp, self.embudo[1:]), start=1):
            pasos.append((str(i), f["tarjeta"], f["descripcion"], f["sql"], n, self.embudo[i - 1] - n))
        for fila, (numero, nombre, descripcion, sql, quedan, quita) in enumerate(pasos):
            circulo = etiqueta(numero or "∑", "circulo")
            circulo.setAlignment(Qt.AlignCenter)
            circulo.setFixedSize(26, 26)
            rejilla.addWidget(circulo, fila, 0, Qt.AlignTop)
            textos = QVBoxLayout()
            textos.setSpacing(1)
            lbl = etiqueta(nombre)
            lbl.setStyleSheet("font-weight: bold; font-size: 10pt;")
            textos.addWidget(lbl)
            if descripcion:
                textos.addWidget(etiqueta(descripcion, "gris"))
            if sql:
                codigo = etiqueta(sql, "codigo")
                codigo.setTextInteractionFlags(Qt.TextSelectableByMouse)
                textos.addWidget(codigo)
            rejilla.addLayout(textos, fila, 1)
            rejilla.addWidget(BarraEmbudo(quedan / total), fila, 2)
            lbl = etiqueta(f"{quedan:,}", "numero")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            rejilla.addWidget(lbl, fila, 3)
            if quita is None:
                lbl = etiqueta("ítems", "gris")
            elif quita:
                lbl = etiqueta(f"quita {quita:,}", "quita")
            else:
                lbl = etiqueta("no quita ninguno", "gris")
            rejilla.addWidget(lbl, fila, 4)
        rejilla.setColumnStretch(2, 1)
        rejilla.setColumnMinimumWidth(1, 380)
        cuerpo.addLayout(rejilla)
        final = etiqueta(f"→  Entran al reporte {self.embudo[-1]:,} ítems.", "resultado")
        cuerpo.addWidget(final)
        capa.addWidget(ficha)

        # --- 2. lo que se está viendo ---
        ficha, cuerpo = seccion("2.  Lo que estás viendo en 'Datos del ítem'",
                                "Filtros puestos en la pestaña Datos del ítem. Clic en ✕ para quitar uno.")
        arriba = QHBoxLayout()
        caja, self.lbl_res_items = tarjeta("ÍTEMS MOSTRADOS")
        arriba.addWidget(caja)
        arriba.addSpacing(10)
        self.chips_filtros = FlujoLayout(espacio=6)
        contenedor = QWidget()
        contenedor.setLayout(self.chips_filtros)
        arriba.addWidget(contenedor, 1)
        cuerpo.addLayout(arriba)
        datos = QGridLayout()
        datos.setHorizontalSpacing(12)
        datos.setVerticalSpacing(4)
        self.lbl_filtro = {}
        for fila, nombre in enumerate(["Orden", "Grupos cerrados", "Columnas ocultas"]):
            lbl = etiqueta(nombre + ":")
            lbl.setStyleSheet("font-weight: bold;")
            datos.addWidget(lbl, fila, 0, Qt.AlignTop)
            self.lbl_filtro[nombre] = etiqueta("")
            self.lbl_filtro[nombre].setWordWrap(True)
            datos.addWidget(self.lbl_filtro[nombre], fila, 1)
        datos.setColumnStretch(1, 1)
        cuerpo.addLayout(datos)
        capa.addWidget(ficha)

        # --- 3. consulta SQL ---
        ficha, cuerpo = seccion("3.  Consulta SQL que se ejecuta",
                                "Datos de origen + todas las fórmulas, en una sola consulta de solo lectura. "
                                "Azul = palabras de SQL, morado = funciones, recuadro = columnas, verde = textos.")
        botones = QHBoxLayout()
        ver = QPushButton("Mostrar consulta")
        ver.setCheckable(True)
        botones.addWidget(ver)
        boton = QPushButton("Copiar consulta (para pgAdmin)")
        boton.clicked.connect(self.copiar_consulta)
        botones.addWidget(boton)
        botones.addStretch(1)
        cuerpo.addLayout(botones)
        caja = QPlainTextEdit(self.sql)
        caja.setReadOnly(True)
        caja.setLineWrapMode(QPlainTextEdit.NoWrap)
        caja.setMinimumHeight(420)
        caja._resaltador = ResaltadorSQL(caja.document())
        caja.setVisible(False)
        ver.toggled.connect(lambda si: (caja.setVisible(si), ver.setText("Ocultar consulta" if si else "Mostrar consulta")))
        cuerpo.addWidget(caja)
        capa.addWidget(ficha)
        capa.addStretch(1)
        self._actualizar_resumen()

    # =========================================================================
    # Pestaña 3: Cálculos (se vuelve a armar al actualizar los datos)
    #   izquierda: los pasos y sus columnas (con buscador)
    #   derecha:   ficha de la columna elegida: qué hace, la fórmula con colores, cómo leerla,
    #              qué columnas usa / dónde se usa (clic para ir) y un EJEMPLO con los valores de un ítem
    # =========================================================================
    def _pestana_calculos(self):
        self._contenido_calculos, capa = self._reemplazar(self.tab_calculos, self._contenido_calculos)
        # quién calcula cada columna: lista de posiciones en self.formulas (en orden)
        self.calculada_en = {}
        for i, f in enumerate(self.formulas):
            self.calculada_en.setdefault(f["columna"], []).append(i)
        self.usa = [list(dict.fromkeys(re.findall(r'"([^"]+)"', f["sql"]))) for f in self.formulas]
        self.legibles = [ddmrp_v1_legible.a_formula(f["sql"]) for f in self.formulas]      # estilo Excel

        arriba = QHBoxLayout()
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(etiqueta("¿Cómo se calcula cada columna?", "seccion"))
        textos.addWidget(etiqueta(f"{len(self.formulas)} fórmulas en {len(dict.fromkeys(f['paso'] for f in self.formulas))} "
                                  "pasos. Cada paso usa lo calculado en los anteriores. Elige una columna a la izquierda; "
                                  "las fórmulas se cambian en formulas_ddmrp_v1.sql.", "gris"))
        arriba.addLayout(textos, 1)
        arriba.addWidget(etiqueta("ÍTEM DE EJEMPLO", "campo"))
        self.combo_ejemplo = QComboBox()
        self.combo_ejemplo.setEditable(True)
        self.combo_ejemplo.setInsertPolicy(QComboBox.NoInsert)
        self.combo_ejemplo.setMinimumContentsLength(48)
        self.combo_ejemplo.setToolTip("Escribe un código o parte de la descripción. También puedes seleccionar una fila "
                                      "en 'Datos del ítem'.")
        for idx in self.datos.index:
            self.combo_ejemplo.addItem(" · ".join(str(self.datos.at[idx, c]) for c in ("CODIGO_ITEM", "EMPRESA", "DESCRIPCION")
                                                  if c in self.datos.columns), idx)
        completar = self.combo_ejemplo.completer()
        completar.setFilterMode(Qt.MatchContains)
        completar.setCompletionMode(QCompleter.PopupCompletion)
        self.combo_ejemplo.view().setTextElideMode(Qt.ElideNone)
        self.combo_ejemplo.activated.connect(lambda i: self._elegir_ejemplo(self.combo_ejemplo.itemData(i)))
        arriba.addWidget(self.combo_ejemplo)
        capa.addLayout(arriba)

        division = QSplitter(Qt.Horizontal)
        izquierda = QWidget()
        capa_izq = QVBoxLayout(izquierda)
        capa_izq.setContentsMargins(0, 0, 0, 0)
        self.buscar_formula = QLineEdit()
        self.buscar_formula.setPlaceholderText("Buscar columna o texto en la fórmula (ej. REDONDEA.PAR)...")
        self.buscar_formula.setClearButtonEnabled(True)
        capa_izq.addWidget(self.buscar_formula)
        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setIndentation(14)
        self.items_arbol = {}
        negrita = QFont(LETRA, 9, QFont.Bold)
        pasos = {}
        for i, f in enumerate(self.formulas):
            if f["paso"] not in pasos:
                nodo = QTreeWidgetItem([f"Paso {f['paso']}"])
                nodo.setFont(0, negrita)
                nodo.setForeground(0, QBrush(QColor(AZUL)))
                nodo.setFlags(Qt.ItemIsEnabled)
                self.arbol.addTopLevelItem(nodo)
                pasos[f["paso"]] = nodo
            hijo = QTreeWidgetItem([f["columna"]])
            hijo.setData(0, Qt.UserRole, i)
            hijo.setToolTip(0, f["descripcion"])
            if f["columna"].startswith("_"):
                hijo.setForeground(0, QBrush(QColor("#7F7F7F")))
            pasos[f["paso"]].addChild(hijo)
            self.items_arbol[i] = hijo
        self.arbol.expandAll()
        self.arbol.currentItemChanged.connect(
            lambda item, _: item is not None and item.data(0, Qt.UserRole) is not None
            and self._ver_formula(item.data(0, Qt.UserRole)))
        self.buscar_formula.textChanged.connect(self._buscar_en_arbol)
        capa_izq.addWidget(self.arbol, 1)
        division.addWidget(izquierda)

        self.panel_ficha = QScrollArea()
        self.panel_ficha.setWidgetResizable(True)
        self.panel_ficha.setFrameShape(QFrame.NoFrame)
        division.addWidget(self.panel_ficha)
        division.setSizes([360, 1100])
        division.setStretchFactor(1, 1)
        capa.addWidget(division, 1)

        if getattr(self, "item_ejemplo", None) not in self.datos.index:
            self.item_ejemplo = self.datos.index[0] if len(self.datos) else None
        self._marcar_ejemplo()
        actual = getattr(self, "formula_actual", None)
        self.formula_actual = None
        primera = actual if actual is not None and actual < len(self.formulas) else next(
            (i for i, f in enumerate(self.formulas) if not f["columna"].startswith("_")), 0)
        if self.formulas:
            self.arbol.setCurrentItem(self.items_arbol[primera])

    @staticmethod
    def _ajustar_alto(caja):
        try:
            alto = caja.document().size().height() * caja.fontMetrics().lineSpacing()
        except RuntimeError:                                      # la ficha ya se cambió
            return
        caja.setFixedHeight(int(min(420, alto + 24)))

    def _buscar_en_arbol(self, texto):
        texto = texto.strip().upper()
        for p in range(self.arbol.topLevelItemCount()):
            nodo = self.arbol.topLevelItem(p)
            alguno = False
            for h in range(nodo.childCount()):
                hijo = nodo.child(h)
                f = self.formulas[hijo.data(0, Qt.UserRole)]
                j = hijo.data(0, Qt.UserRole)
                ve = (not texto or texto in f["columna"].upper() or texto in (self.legibles[j] or "").upper()
                      or texto in f["sql"].upper() or texto in f["descripcion"].upper())
                hijo.setHidden(not ve)
                alguno |= ve
            nodo.setHidden(not alguno)

    def _elegir_ejemplo(self, idx):
        if idx is None or idx not in self.datos.index:
            return
        self.item_ejemplo = idx
        self._marcar_ejemplo()
        if self.formula_actual is not None:
            self._ver_formula(self.formula_actual, forzar=True)

    def _marcar_ejemplo(self):
        if self.item_ejemplo is None:
            return
        i = self.combo_ejemplo.findData(self.item_ejemplo)
        if i >= 0:
            self.combo_ejemplo.blockSignals(True)
            self.combo_ejemplo.setCurrentIndex(i)
            self.combo_ejemplo.blockSignals(False)

    def _fila_elegida(self, actual, _anterior):
        """Al seleccionar una fila en 'Datos del ítem', ese ítem pasa a ser el ejemplo de 'Cálculos'."""
        if actual.isValid() and actual.row() < len(self.indices):
            self._elegir_ejemplo(self.indices[actual.row()])

    def _ir_a(self, i):
        self.buscar_formula.clear()
        self.arbol.setCurrentItem(self.items_arbol[i])

    def _origen(self, columna, antes_de):
        """Fórmula que calculó 'columna' antes de la fórmula 'antes_de' (None = dato de origen)."""
        return next((j for j in reversed(self.calculada_en.get(columna, [])) if j < antes_de), None)

    def _valor(self, columna):
        if self.item_ejemplo is None or columna not in self.datos.columns:
            return None
        return a_texto(self.datos.at[self.item_ejemplo, columna], "Todos") or "(vacío)"

    def _ver_formula(self, i, forzar=False):
        if i == self.formula_actual and not forzar:
            return
        self.formula_actual = i
        f = self.formulas[i]
        col = f["columna"]
        hoja = QWidget()
        hoja.setObjectName("fondo")
        capa = QVBoxLayout(hoja)
        capa.setContentsMargins(14, 4, 8, 8)
        capa.setSpacing(10)

        # encabezado: paso, nombre y etiquetas
        capa.addWidget(etiqueta(f"PASO {f['paso'].upper()}", "paso"))
        fila = QHBoxLayout()
        titulo = etiqueta(col, "grande")
        titulo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        fila.addWidget(titulo)
        veces = self.calculada_en[col]
        if col.startswith("_"):
            fila.addWidget(etiqueta("AUXILIAR: se usa en otras fórmulas, no se muestra en la tabla", "tag"))
        if len(veces) > 1:
            n = veces.index(i) + 1
            fila.addWidget(etiqueta(f"se calcula {len(veces)} veces · esta es la {n}ª"
                                    + (" (la final)" if n == len(veces) else ""), "tag"))
        elif col not in self.datos.columns and not col.startswith("_"):
            fila.addWidget(etiqueta("no está en las columnas del reporte", "tag"))
        fila.addStretch(1)
        capa.addLayout(fila)

        # qué hace
        ficha, cuerpo = seccion("¿Qué hace?")
        lbl = etiqueta(f["descripcion"] or "(sin explicación en formulas_ddmrp_v1.sql: se puede agregar con un "
                                           "comentario  -- ...  encima de la fórmula)")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 10pt;")
        cuerpo.addWidget(lbl)
        capa.addWidget(ficha)

        # fórmula (estilo Excel) y, en un botón, cómo está escrita en el .sql
        formula = self.legibles[i]
        ficha, cuerpo = seccion("Fórmula", "[COLUMNA] = valor de esa columna para el ítem · verde = texto · "
                                           "morado = función")
        caja = QPlainTextEdit(f"{col}\n{formula}" if formula else f"{f['sql']}\n    AS \"{col}\"")
        caja.setObjectName("formula")
        caja.setReadOnly(True)
        caja.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        caja._resaltador = ResaltadorFormula(caja.document()) if formula else ResaltadorSQL(caja.document())
        cuerpo.addWidget(caja)
        pie = QHBoxLayout()
        pie.addWidget(etiqueta(f"Se calcula con formulas_ddmrp_v1.sql, línea {f['linea']} (ahí se cambia).", "gris"))
        pie.addStretch(1)
        ver_sql = QPushButton("Ver cómo está escrita en el .sql")
        ver_sql.setCheckable(True)
        pie.addWidget(ver_sql)
        cuerpo.addLayout(pie)
        codigo = QPlainTextEdit(f"{f['sql']}\n    AS \"{col}\"")
        codigo.setReadOnly(True)
        codigo.setLineWrapMode(QPlainTextEdit.NoWrap)
        codigo._resaltador = ResaltadorSQL(codigo.document())
        codigo.setFixedHeight(min(360, (f["sql"].count("\n") + 2) * codigo.fontMetrics().lineSpacing() + 22))
        codigo.setVisible(False)
        ver_sql.toggled.connect(lambda si: (codigo.setVisible(si), ver_sql.setText(
            "Ocultar el .sql" if si else "Ver cómo está escrita en el .sql")))
        cuerpo.addWidget(codigo)
        capa.addWidget(ficha)
        QTimer.singleShot(0, lambda c=caja: self._ajustar_alto(c))
        despues_de_formula = capa.count()                         # aquí va el ejemplo (justo debajo de la fórmula)

        # cómo leerla: solo lo que usa esta fórmula
        ayudas = ([texto for patron, texto in ddmrp_v1_legible.AYUDA if re.search(patron, formula)] if formula else
                  [texto for patron, texto in AYUDA_SQL if re.search(patron, f["sql"], re.IGNORECASE)])
        if ayudas:
            ficha, cuerpo = seccion("Cómo leer esta fórmula", "Lo que significa cada parte")
            for texto in ayudas:
                lbl = QLabel(texto)
                lbl.setWordWrap(True)
                lbl.setTextFormat(Qt.RichText)
                cuerpo.addWidget(lbl)
            capa.addWidget(ficha)

        # usa / se usa en
        usa = [c for c in self.usa[i]]
        usada_por = [j for j in range(i + 1, len(self.formulas))
                     if col in self.usa[j] and self._origen(col, j) == i]
        ficha, cuerpo = seccion("Relación con otras columnas", "Clic en una columna calculada para ver su fórmula")
        rejilla = QGridLayout()
        rejilla.setHorizontalSpacing(10)
        rejilla.setVerticalSpacing(6)
        rejilla.addWidget(etiqueta("USA", "campo"), 0, 0, Qt.AlignTop)
        flujo = FlujoLayout(espacio=6)
        for c in usa:
            j = self._origen(c, i)
            if j is None:
                b = QPushButton(f"{c}  · dato de origen")
                b.setObjectName("chipOrigen")
                b.setToolTip("Viene de la consulta de datos de origen (SQL_ITEMS en ddmrp_consolidado_v1.py)")
            else:
                b = QPushButton(f"{c}  · paso {self.formulas[j]['paso'].split('·')[0].strip()}")
                b.setObjectName("chip")
                b.setToolTip(self.formulas[j]["descripcion"])
                b.clicked.connect(lambda _=False, j=j: self._ir_a(j))
            flujo.addWidget(b)
        contenedor = QWidget()
        contenedor.setLayout(flujo)
        rejilla.addWidget(contenedor if usa else etiqueta("(ninguna columna: es un valor fijo)", "gris"), 0, 1)
        rejilla.addWidget(etiqueta("SE USA EN", "campo"), 1, 0, Qt.AlignTop)
        flujo = FlujoLayout(espacio=6)
        for j in usada_por:
            b = QPushButton(self.formulas[j]["columna"])
            b.setObjectName("chip")
            b.setToolTip(self.formulas[j]["descripcion"])
            b.clicked.connect(lambda _=False, j=j: self._ir_a(j))
            flujo.addWidget(b)
        contenedor = QWidget()
        contenedor.setLayout(flujo)
        rejilla.addWidget(contenedor if usada_por else etiqueta("(ninguna fórmula: es un resultado final del reporte)",
                                                                "gris"), 1, 1)
        rejilla.setColumnStretch(1, 1)
        cuerpo.addLayout(rejilla)
        capa.addWidget(ficha)

        # ejemplo con un ítem
        if self.item_ejemplo is not None:
            nombre = " · ".join(str(self.datos.at[self.item_ejemplo, c]) for c in ("CODIGO_ITEM", "EMPRESA", "DESCRIPCION")
                                if c in self.datos.columns)
            ficha, cuerpo = seccion(f"Ejemplo con un ítem:  {nombre}",
                                    "Valores con todos los decimales. Cambia el ítem arriba a la derecha o "
                                    "seleccionando una fila en 'Datos del ítem'.")
            rejilla = QGridLayout()
            rejilla.setHorizontalSpacing(16)
            rejilla.setVerticalSpacing(3)
            fila = 0
            aviso = False
            for c in usa:
                valor = self._valor(c)
                rejilla.addWidget(etiqueta(c), fila, 0)
                if valor is None:
                    lbl = etiqueta("(auxiliar: no se guarda en la tabla)", "gris")
                else:
                    lbl = etiqueta(valor, "valor")
                    lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
                    calculos = self.calculada_en.get(c, [])
                    if calculos and calculos[-1] != self._origen(c, i):
                        lbl.setText(valor + "  *")
                        aviso = True
                rejilla.addWidget(lbl, fila, 1)
                fila += 1
            linea = QFrame()
            linea.setFrameShape(QFrame.HLine)
            linea.setStyleSheet(f"color: {BORDE};")
            rejilla.addWidget(linea, fila, 0, 1, 2)
            fila += 1
            rejilla.addWidget(etiqueta(f"= {col}", "resultado"), fila, 0)
            valor = self._valor(col)
            lbl = etiqueta(valor if valor is not None else "(auxiliar: no se guarda en la tabla)", "resultadoValor")
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            rejilla.addWidget(lbl, fila, 1)
            rejilla.setColumnStretch(2, 1)
            cuerpo.addLayout(rejilla)
            if aviso or len(veces) > 1:
                cuerpo.addWidget(etiqueta("* La tabla guarda el valor FINAL de cada columna. Esta columna (o alguna que "
                                          "usa) se vuelve a calcular en otro paso, así que el valor mostrado puede ser "
                                          "el de ese otro paso.", "gris"))
            capa.insertWidget(despues_de_formula, ficha)
        capa.addStretch(1)
        self.panel_ficha.setWidget(hoja)

    def copiar_consulta(self):
        QGuiApplication.clipboard().setText("SET jit = off;   -- más rápido (solo esta sesión)\n\n" + self.sql)
        QMessageBox.information(self.root, "Consulta SQL",
                                "Consulta copiada. Pégala en pgAdmin para ejecutarla (solo lectura).")

    # =========================================================================
    # Acciones
    # =========================================================================
    def abrir_cerrar(self, grupo):
        """Clic en el botón + / - de un grupo: lo abre o lo cierra."""
        grupo["abierto"] = not grupo["abierto"]
        self.aplicar_columnas()

    def aplicar_columnas(self):
        """Columnas visibles: las de un grupo cerrado no se muestran; las ocultas solo con 'Mostrar columnas ocultas'.
        Cada parte de la tabla muestra solo sus columnas (ancladas a la izquierda, el resto a la derecha)."""
        cerradas = {c for g in self.grupos if not g["abierto"] for c in g["columnas"]}
        ocultas = set() if self.ver_ocultas.isChecked() else set(self.ocultas)
        fijas = set(self.fijas)
        for col, i in self.pos.items():
            escondida = col in cerradas or col in ocultas
            self.vista_izq.setColumnHidden(i, escondida or col not in fijas)
            self.vista_der.setColumnHidden(i, escondida or col in fijas)
        self._redibujar()
        if hasattr(self, "lbl_filtro"):
            self._actualizar_resumen()

    def exportar(self, validacion=False, ruta=None):
        """Exporta a Excel lo que se ve (filas filtradas, en el mismo orden) con el formato del Excel final.
        validacion=True: Excel de validación (columnas con fórmulas de Excel + hojas VALIDACIÓN y VALORES PROGRAMA)."""
        titulo = "Excel de validación" if validacion else "Exportar a Excel"
        hoy = dt.date.today().strftime("%d-%m-%Y")
        carpeta = CARPETA_REPORTES / hoy
        if ruta is None:
            inicio = carpeta if carpeta.exists() else CARPETA_REPORTES if CARPETA_REPORTES.exists() else Path.home()
            nombre = (NOMBRE_VALIDACION if validacion else NOMBRE_EXCEL).format(fecha=hoy)
            ruta, _ = QFileDialog.getSaveFileName(self.root, titulo, str(inicio / nombre), "Excel (*.xlsx)")
        if not ruta:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.estado.setText(f"Exportando {len(self.indices):,} ítems a Excel...")
        QApplication.processEvents()
        try:
            ddmrp_v1_excel.exportar(
                ruta, self.datos.loc[self.indices], self.color_fila.loc[self.indices].tolist(), self.colores_fila,
                self.grupos, [] if self.ver_ocultas.isChecked() else self.ocultas, self.columna_ancla, self.fecha_datos,
                formulas_excel=self.formulas_excel if validacion else None)
        except PermissionError:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self.root, titulo, f"No se pudo guardar (¿está abierto en Excel?):\n{ruta}")
            return
        except Exception as error:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self.root, titulo, f"No se pudo exportar:\n{error}")
            return
        finally:
            self._texto_estado()
        QApplication.restoreOverrideCursor()
        extra = ("\n\nEn la hoja VALIDACIÓN: 'OK' = la fórmula de Excel da lo mismo que el programa, "
                 "'DIF' (rojo) = diferente. La fila 1 dice cuántas diferencias hay por columna." if validacion else "")
        respuesta = QMessageBox.question(self.root, titulo,
                                         f"Se exportaron {len(self.indices):,} ítems a:\n{ruta}{extra}\n\n¿Abrir el archivo?")
        if respuesta == QMessageBox.Yes:
            os.startfile(ruta)

    @staticmethod
    def coincide(serie, valor):
        """Exacto si lo escrito es un valor de la columna, si no 'contiene'. Vacío o (Todas) = sin filtro.
        (Vacío) = los ítems que no tienen valor en esa columna."""
        valor = valor.strip().upper()
        if not valor or valor == TODAS.upper():
            return pd.Series(True, index=serie.index)
        valores = serie.str.upper()
        if valor == VACIO.upper():
            return valores.str.strip() == ""
        if (valores == valor).any():
            return valores == valor
        return valores.str.contains(valor, regex=False)

    def _poner_lista(self, columna, valores):
        """Cambia la lista desplegable sin tocar lo que está escrito (ni volver a filtrar)."""
        combo, actuales = self.filtros[columna]
        if valores == actuales:
            return
        escrito, cursor = combo.currentText(), combo.lineEdit().cursorPosition()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(valores)
        combo.setEditText(escrito)
        combo.lineEdit().setCursorPosition(cursor)
        combo.blockSignals(False)
        medidas = combo.fontMetrics()
        combo.view().setMinimumWidth(max(medidas.horizontalAdvance(v) for v in valores) + 40)
        self.filtros[columna][1] = valores

    def filtrar(self):
        if self._pausa:
            return
        textos = self.textos
        mascaras = {col: self.coincide(textos[col], combo.currentText()) for col, (combo, _) in self.filtros.items()}
        buscado = self.texto.text().strip().upper()
        busqueda = (self.busqueda.str.contains(buscado, regex=False) if buscado
                    else pd.Series(True, index=textos.index))

        # cada lista desplegable muestra solo los valores que quedan con los DEMÁS filtros
        for col in self.filtros:
            otros = busqueda.copy()
            for c, m in mascaras.items():
                if c != col:
                    otros &= m
            valores = sorted(textos.loc[otros, col].unique())
            self._poner_lista(col, [TODAS] + [v for v in valores if v.strip()] + ([VACIO] if "" in valores else []))

        total = busqueda.copy()
        for m in mascaras.values():
            total &= m
        self.indices = list(textos.index[total])
        self.aplicar_orden()
        self.pintar()

    def aplicar_orden(self):
        """Ordena las filas visibles por la columna elegida (números como número, textos como texto)."""
        for col, descendente in self.orden.items():
            if col in self.numericas:
                valores = pd.to_numeric(self.datos.loc[self.indices, col], errors="coerce")
            else:
                valores = self.textos.loc[self.indices, col]
            self.indices = list(valores.sort_values(ascending=not descendente, kind="stable",
                                                    na_position="last").index)

    def ordenar(self, col):
        descendente = not self.orden.get(col, True)
        self.orden = {col: descendente}
        self.modelo.headerDataChanged.emit(Qt.Horizontal, 0, len(self.columnas) - 1)    # flecha ▲ / ▼
        self.aplicar_orden()
        self.pintar()

    def pintar(self):
        colores = self.color_fila.loc[self.indices].tolist()
        brochas = {nombre: QBrush(QColor(color)) for nombre, color, _, _ in self.colores_fila}
        par = QBrush(QColor(FILA_PAR))
        fondos = [brochas.get(color) if color else (par if i % 2 else None) for i, color in enumerate(colores)]
        self.modelo.cargar(self.textos.loc[self.indices, self.columnas].values.tolist(), fondos)
        # indicadores
        self.lbl_mostrados.setText(f"{len(self.indices):,} de {len(self.textos):,}")
        for (titulo, columna, tipo), lbl in self.lbl_indicador.items():
            valores = pd.to_numeric(self.datos.loc[self.indices, columna], errors="coerce")
            lbl.setText(f"{(valores > 0).sum():,}" if tipo == "items" else f"{valores.sum():,.0f}")
        self._marcar_filtros()
        self._texto_estado()
        self._actualizar_resumen()

    def _texto_estado(self):
        self.estado.setText(f"Mostrando {len(self.indices):,} de {len(self.textos):,} ítems   ·   "
                            f"'Exportar a Excel' guarda lo que se ve, con los filtros y el orden actuales")

    def _actualizar_resumen(self):
        """Pestaña Filtros, sección 2: lo que está aplicado en la pestaña Datos del ítem."""
        if not hasattr(self, "indices") or not hasattr(self, "chips_filtros"):
            return
        while self.chips_filtros.count():
            viejo = self.chips_filtros.takeAt(0).widget()
            if viejo is not None:
                viejo.hide()                                     # se esconde ya (se borra después)
                viejo.deleteLater()
        activos = []
        buscado = self.texto.text().strip()
        if buscado:
            activos.append((f"Buscar: '{buscado}'", self.texto.clear))
        for nombre, columna in self.filtros_ventana:
            valor = self.filtros[columna][0].currentText().strip()
            if valor and valor.upper() != TODAS.upper():
                activos.append((f"{nombre}: {valor}", lambda c=columna: self.filtros[c][0].setEditText(TODAS)))
        if not activos:
            self.chips_filtros.addWidget(etiqueta("Sin filtros: se ven todos los ítems.", "gris"))
        for texto, quitar in activos:
            chip = QPushButton(f"{texto}   ✕")
            chip.setObjectName("chipQuitar")
            chip.setToolTip("Quitar este filtro")
            chip.clicked.connect(lambda _=False, q=quitar: q())
            self.chips_filtros.addWidget(chip)
        self.lbl_res_items.setText(f"{len(self.indices):,} de {len(self.textos):,}")
        orden = ", ".join(f"{c} ({'mayor a menor' if d else 'menor a mayor'})" for c, d in self.orden.items())
        self.lbl_filtro["Orden"].setText(orden or "EMPRESA, CODIGO_ITEM (por defecto)")
        cerrados = ", ".join(g["nombre"] for g in self.grupos if not g["abierto"])
        self.lbl_filtro["Grupos cerrados"].setText(cerrados or "(ninguno)")
        ocultas = "se muestran" if self.ver_ocultas.isChecked() else (", ".join(self.ocultas) or "(ninguna)")
        self.lbl_filtro["Columnas ocultas"].setText(ocultas)

    def limpiar(self):
        self._pausa = True
        for combo, _ in self.filtros.values():
            combo.setEditText(TODAS)
        self.texto.clear()
        self._pausa = False
        self.filtrar()

    def abrir(self):
        self.root.showMaximized()
        self.app.exec()
