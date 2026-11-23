# =============================================================================
# DDMRP CONSOLIDADO v1 - EXPORTAR A EXCEL
#
# Lo usa el botón "Exportar a Excel" de la ventana. Guarda lo que se ve en la ventana (filas filtradas,
# en el mismo orden) con el formato del Excel "Reporte de Pedidos Consolidado (final, revisado 12-11-2026)":
#   fila 1: SUBTOTAL de las columnas de cantidades (cambia al filtrar en Excel)
#   fila 2: encabezados (texto ajustado, colores) con filtro
#   colores de fila (naranja / rojo / verde), colores de columna, formatos de número, anchos,
#   columnas agrupadas (+ / -) y ocultas como están en la ventana, y la hoja EXPLICACIÓN COLORES.
# Los valores se guardan como números (no como fórmulas) con TODOS los decimales; se ven con el formato
# de la columna (2 decimales) y en Excel, "Aumentar decimales" muestra el resto.
#
# EXCEL DE VALIDACIÓN (botón "Excel de validación", formulas_excel = FORMULAS_EXCEL_VALIDACION):
#   el mismo Excel, pero las columnas que en el Excel original son fórmulas van como FÓRMULAS DE EXCEL
#   (Excel las calcula al abrir), y se agregan dos hojas:
#     VALIDACIÓN        por ítem y columna: "OK" si la fórmula de Excel da lo mismo que el programa,
#                       "DIF" si no (en rojo). Fila 1: cuántos "DIF" hay en cada columna.
#     VALORES PROGRAMA  lo que calculó el programa (SQL) en esas columnas, misma fila que en Sheet1
# =============================================================================
import datetime as dt
import re

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ----------------------------------------------------------------------------- formato (igual al Excel final)
GRIS_CLARO, GRIS_OSCURO, AZUL, AMARILLO = "D9D9D9", "A6A6A6", "9BC2E6", "FFFF00"
VERDE_TOG, AZUL_AGUA, AZUL_AGUA_CLARO = "00B050", "93CDDD", "B7DEE8"

# encabezado Y datos de la columna
COLOR_COLUMNA = {
    "DEMANDA MES - AÑO": GRIS_CLARO, "DEMANDA MES 90D": GRIS_CLARO, "EN STOCK": GRIS_OSCURO,
    "STOCK TOTAL": AZUL, "TAMAÑO BUFFER (TOG)": VERDE_TOG, "FLUJO NETO (NFP)": AZUL_AGUA,
    "PEDIDO SUGERIDO AJUSTADO A PISO": AMARILLO,
}
# solo los datos (el encabezado va en COLOR_ENCABEZADO)
COLOR_DATOS = {
    "# MESES EN STOCK CON MAX ADU": GRIS_OSCURO, "MESES STOCK EN SEGÚN ADU": GRIS_OSCURO,
    "# MESES EN STOCK TOTALSEGUN ADU": AZUL, "# MES INV TOTAL SEGUN DEMANDA 90D": AZUL,
    "# MESES EN STOCK TOTAL CON MAX ADU": AZUL, "# MES DE STOCK PROYECT MAX ADU DLT": AZUL, "VALIDADOR": AZUL,
    "MESES EN PISO X CATEGORIA": AZUL, "MESES EN PISO + DLT X CATEGORIA CON MAX ADU": AZUL,
    "MESES X PEDIR TOTAL": AZUL, "MESES X PEDIR PARA PISO": AZUL,
}
# solo el encabezado
COLOR_ENCABEZADO = {c: AMARILLO for c in [
    "ADU BASE", "ADU 90 DÍAS", "MAX ADU", "# MESES EN STOCK CON MAX ADU", "MESES STOCK EN SEGÚN ADU",
    "# MESES EN TRANSITO", "# MESES EN PEDIDOS", "# MESES EN BACK ORDERS", "# MESES EN STOCK TOTALSEGUN ADU",
    "# MES INV TOTAL SEGUN DEMANDA 90D", "# MESES EN STOCK TOTAL CON MAX ADU", "STOCK PROYECTADO DLT CON MAX ADU",
    "# MES DE STOCK PROYECT MAX ADU DLT", "VALIDADOR", "MESES EN PISO X CATEGORIA",
    "MESES EN PISO + DLT X CATEGORIA CON MAX ADU", "MESES X PEDIR TOTAL", "MESES X PEDIR PARA PISO",
    "TAMAÑO 3 MESES SEGÚN MAX ADU", "PEDIDO ESTANDAR DDMRP", "FLUJO NETO (NFP) AJUSTADO", "PEDIDO AJUSTADO DDMRP",
    "FLUJO NETO (NFP) AJUSTADO JP", "PEDIDO AJUSTADO DDMRP JP", "# DE MESES DEL PEDIDO SEGÚN MAX ADU"]}
COLOR_ENCABEZADO.update({"PEDIDO ESTANDAR DDMRP AJUS TAMAÑO MAX 3 MESES": AZUL_AGUA_CLARO,
                         "PEDIDO AJUSTADO DDMRP AJUS TAMAÑO MAX 3 MESES": AZUL_AGUA_CLARO})

# fila 1: SUBTOTAL(109; ...) = suma de lo que queda visible con el filtro de Excel
COLUMNAS_SUBTOTAL = [
    "ADU BASE", "STOCK TOTAL", "STOCK PROYECTADO DLT CON MAX ADU", "ZONA ROJA BASE", "ZONA ROJA SEGURIDAD",
    "ZONA ROJA (TOR)", "ZONA AMARILLA", "LIMITE ZONA AMARILLA (TOY)", "ZONA VERDE", "TAMAÑO BUFFER (TOG)",
    "FLUJO NETO (NFP)", "TAMAÑO 3 MESES SEGÚN MAX ADU", "PEDIDO ESTANDAR DDMRP",
    "PEDIDO ESTANDAR DDMRP AJUS TAMAÑO MAX 3 MESES", "FLUJO NETO (NFP) AJUSTADO", "PEDIDO AJUSTADO DDMRP",
    "PEDIDO AJUSTADO DDMRP AJUS TAMAÑO MAX 3 MESES", "FLUJO NETO (NFP) AJUSTADO JP", "PEDIDO AJUSTADO DDMRP JP",
    "PEDIDO SUGERIDO AJUSTADO A PISO",
]

FORMATO_NUMERO = {
    "ADU BASE": "0.00", "ADU 90 DÍAS": "#,##0.00", "MAX ADU": "#,##0.00",
    "# MESES EN STOCK CON MAX ADU": "0.00", "MESES STOCK EN SEGÚN ADU": "0.00", "# MESES EN TRANSITO": "0.00",
    "# MESES EN PEDIDOS": "0.00", "# MESES EN BACK ORDERS": "0.00", "# MESES EN STOCK TOTALSEGUN ADU": "0.00",
    "# MESES EN STOCK TOTAL CON MAX ADU": "0.00", "# MES DE STOCK PROYECT MAX ADU DLT": "0.00",
    "MESES EN PISO X CATEGORIA": "0.00", "MESES EN PISO + DLT X CATEGORIA CON MAX ADU": "0.00",
    "MESES X PEDIR TOTAL": "0.00", "MESES X PEDIR PARA PISO": "0.00",
    "ZONA ROJA BASE": "0", "ZONA ROJA SEGURIDAD": "0", "ZONA ROJA (TOR)": "0", "ZONA AMARILLA": "0",
    "LIMITE ZONA AMARILLA (TOY)": "0", "ZONA VERDE": "0", "TAMAÑO BUFFER (TOG)": "0", "FLUJO NETO (NFP)": "0",
    "TAMAÑO 3 MESES SEGÚN MAX ADU": "#,##0", "PEDIDO ESTANDAR DDMRP": "#,##0",
    "PEDIDO ESTANDAR DDMRP AJUS TAMAÑO MAX 3 MESES": "#,##0", "FLUJO NETO (NFP) AJUSTADO": "#,##0",
    "PEDIDO AJUSTADO DDMRP": "#,##0", "PEDIDO AJUSTADO DDMRP AJUS TAMAÑO MAX 3 MESES": "#,##0",
    "FLUJO NETO (NFP) AJUSTADO JP": "#,##0", "PEDIDO AJUSTADO DDMRP JP": "#,##0",
    "PEDIDO SUGERIDO AJUSTADO A PISO": "0.00", "# DE MESES DEL PEDIDO SEGÚN MAX ADU": "0.00",
    "ULTIMA COMPRA": "yyyy-mm-dd", "ULTIMA VENTA": "yyyy-mm-dd",
}

# Las demás columnas con números que tienen decimales se muestran con este formato (el valor guardado
# tiene TODOS los decimales: en Excel, "Aumentar decimales" los muestra). Las de números enteros quedan en General.
FORMATO_DECIMALES = "#,##0.00"


def formato_automatico(serie):
    numeros = pd.to_numeric(serie, errors="coerce").dropna()
    if numeros.empty or len(numeros) < 0.5 * serie.notna().sum():
        return None                                        # columna de texto
    return None if (numeros == numeros.round(0)).all() else FORMATO_DECIMALES


ANCHO_POR_DEFECTO = 13
ANCHOS = {
    "CODIGO_ITEM": 11.44, "COD. PROV1": 15.11, "PROV1": 41.44, "COD. PROV2": 11.44, "DESCRIPCION": 51, "ANT.": 8,
    "TOP": 6.89, "CLASIF. PARETO": 7.55, "UN (#) - AÑO": 6.66, "PICO ULT. AÑO X FACTURA": 8.33,
    "DIF. MAX AÑO vs TOT. AÑO": 6.89, "DIAS INV 1 AÑO": 6.11, "DEMANDA MES - AÑO": 9.89, "ADU BASE": 9.11,
    "UN (#) - 90D": 7, "DIAS INV 90D": 5.11, "DEMANDA MES 90D": 9.89, "ADU 90 DÍAS": 6.33, "MAX ADU": 6.33,
    "% VARIACIÓN DEMANDA": 7.33, "UNIDADES MES ACTUAL": 7, "EN STOCK": 9.89, "# MESES EN STOCK CON MAX ADU": 8.11,
    "MESES STOCK EN SEGÚN ADU": 8.11, "TRANSITOS TOTAL": 10.55, "VALIDADOR": 31.44, "DLT": 6.44,
    "FLUJO NETO (NFP)": 11.33,
}
ALTO_ENCABEZADO = 86.4

HOJA_EXPLICACION = "EXPLICACIÓN COLORES"
HOJA_VALORES     = "VALORES PROGRAMA"
HOJA_VALIDACION  = "VALIDACIÓN"
TOLERANCIA       = "0.000001"      # diferencia máxima para decir que dos números son iguales
FILA = "\x00"                      # marca del número de fila dentro de una fórmula


def plantilla_formula(formula, pos):
    """'=MAX([ADU BASE],[ADU 90 DÍAS])' -> '=MAX(AA<fila>,AE<fila>)' (la fila se pone al escribir cada celda)."""
    def letra(m):
        if m.group(1) not in pos:
            raise ValueError(f"La fórmula de Excel usa la columna [{m.group(1)}], que no está en el reporte:\n{formula}")
        return get_column_letter(pos[m.group(1)]) + FILA
    return re.sub(r"\[([^\]]+)\]", letra, formula)


def _valor(v):
    """Valor para la celda: vacíos como celda vacía, fechas como fecha."""
    if v is None or v is pd.NaT or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_, bool)):
        return "SI" if v else "NO"
    return v


def exportar(ruta, df, color_fila, colores_fila, grupos, ocultas, ancla=None, fecha_datos=None, formulas_excel=None):
    """Guarda df (las filas y columnas a exportar, en orden) en ruta.
       color_fila:   nombre del color de cada fila ("" = sin color), mismo índice que df
       colores_fila: [(nombre, "#RRGGBB", explicación, condición)] (de ddmrp_consolidado_v1.py)
       grupos:       [{"nombre", "columnas", "abierto"}] (estado actual de la ventana)
       ocultas:      columnas ocultas sin grupo
       ancla:        última columna anclada (Inmovilizar paneles): no se mueve al desplazarse a la derecha
       formulas_excel: {columna: fórmula de Excel con [COLUMNA]} -> Excel de validación (ver arriba)"""
    columnas = list(df.columns)
    pos = {c: i + 1 for i, c in enumerate(columnas)}
    formulas_excel = {c: f for c, f in (formulas_excel or {}).items() if c in pos}
    plantillas = {pos[c]: plantilla_formula(f, pos) for c, f in formulas_excel.items()}   # n° de columna -> fórmula
    ultima_fila = len(df) + 2
    relleno = lambda color: PatternFill("solid", fgColor=color.lstrip("#").upper())
    rellenos_fila = {nombre: relleno(color) for nombre, color, _, _ in colores_fila}

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # fila 1: subtotales | fila 2: encabezados
    for col in COLUMNAS_SUBTOTAL:
        if col in pos:
            letra = get_column_letter(pos[col])
            ws.cell(1, pos[col], f"=SUBTOTAL(109,{letra}3:{letra}{ultima_fila})")
    for col, i in pos.items():
        celda = ws.cell(2, i, col)
        celda.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[2].height = ALTO_ENCABEZADO

    # datos (desde la fila 3) con el color de su fila
    for r, (fila, color) in enumerate(zip(df.itertuples(index=False, name=None), color_fila), start=3):
        fill = rellenos_fila.get(color)
        for i, v in enumerate(fila, start=1):
            formula = plantillas.get(i)
            celda = ws.cell(r, i, formula.replace(FILA, str(r)) if formula else _valor(v))
            if fill is not None:
                celda.fill = fill

    # colores de columna (encima del color de fila), formatos de número y anchos
    for col, i in pos.items():
        color_datos = COLOR_COLUMNA.get(col) or COLOR_DATOS.get(col)
        formato = FORMATO_NUMERO.get(col) or formato_automatico(df[col])
        if color_datos or formato:
            fill = relleno(color_datos) if color_datos else None
            for (celda,) in ws.iter_rows(min_row=3, max_row=ultima_fila, min_col=i, max_col=i):
                if fill is not None:
                    celda.fill = fill
                if formato:
                    celda.number_format = formato
        color_enc = COLOR_ENCABEZADO.get(col) or COLOR_COLUMNA.get(col)
        if color_enc:
            ws.cell(2, i).fill = relleno(color_enc)
        if formato:
            ws.cell(1, i).number_format = formato
        ws.column_dimensions[get_column_letter(i)].width = ANCHOS.get(col, ANCHO_POR_DEFECTO)

    # grupos (Datos > Agrupar) y columnas ocultas, como están en la ventana
    for g in grupos:
        cols = [c for c in g["columnas"] if c in pos]
        if cols:
            ws.column_dimensions.group(get_column_letter(pos[cols[0]]), get_column_letter(pos[cols[-1]]),
                                       outline_level=1, hidden=not g["abierto"])
    for col in ocultas:
        if col in pos:
            ws.column_dimensions[get_column_letter(pos[col])].hidden = True

    ws.auto_filter.ref = f"A2:{get_column_letter(len(columnas))}{ultima_fila}"
    # inmovilizar: filas 1-2 (subtotales y encabezados) y las columnas hasta la anclada
    ws.freeze_panes = f"{get_column_letter(pos[ancla] + 1)}3" if ancla in pos else "A3"

    # hoja con la explicación de los colores de fila
    hoja = wb.create_sheet(HOJA_EXPLICACION)
    for r, (nombre, color, explicacion, _) in enumerate(colores_fila, start=2):
        celda = hoja.cell(r, 1, f"{nombre} = {explicacion.upper()}")
        celda.fill = relleno(color)
    hoja.column_dimensions["A"].width = 90
    fecha = f"datos al {fecha_datos:%d/%m/%Y %H:%M:%S}  ·  " if fecha_datos else ""
    hoja.cell(len(colores_fila) + 3, 1, f"DDMRP Consolidado v1  ·  {fecha}exportado el {dt.datetime.now():%d/%m/%Y %H:%M}"
              ).font = Font(italic=True, color="595959")

    if formulas_excel:
        _hojas_validacion(wb, df, list(formulas_excel), pos, ultima_fila)
    wb.save(ruta)
    return ruta


def _encabezados(hoja, nombres):
    for j, col in enumerate(nombres, start=1):
        celda = hoja.cell(2, j, col)
        celda.font, celda.fill = Font(bold=True), PatternFill("solid", fgColor=GRIS_CLARO)
        celda.alignment = Alignment(wrap_text=True, vertical="center")
        hoja.column_dimensions[get_column_letter(j)].width = 40 if col == "DESCRIPCION" else 14
    hoja.row_dimensions[2].height = ALTO_ENCABEZADO


def _hojas_validacion(wb, df, cols, pos, ultima_fila):
    """Hojas VALIDACIÓN y VALORES PROGRAMA (ver arriba). Las filas son las mismas que en Sheet1."""
    fijas = [c for c in ["EMPRESA", "CODIGO_ITEM", "DESCRIPCION"] if c in pos]
    n = len(fijas)

    # VALORES PROGRAMA: lo que calculó el programa, con todos los decimales
    valores = wb.create_sheet(HOJA_VALORES)
    valores.cell(1, 1, "Valores calculados por el programa (SQL), con todos los decimales").font = Font(italic=True)
    _encabezados(valores, fijas + cols)
    for r, fila in enumerate(df[fijas + cols].itertuples(index=False, name=None), start=3):
        for j, v in enumerate(fila, start=1):
            valores.cell(r, j, _valor(v))
    valores.freeze_panes = f"{get_column_letter(n + 1)}3"

    # VALIDACIÓN: fórmula de Excel (Sheet1) vs valor del programa, celda por celda
    hoja = wb.create_sheet(HOJA_VALIDACION, 1)                       # segunda hoja, junto a Sheet1
    col_total = n + 1                                                # cuántos "DIF" tiene el ítem
    _encabezados(hoja, fijas + ["# DIF DEL ÍTEM"] + cols)
    comparar = []
    for k, col in enumerate(cols):
        a = f"Sheet1!{get_column_letter(pos[col])}{FILA}"                       # fórmula de Excel
        b = f"'{HOJA_VALORES}'!{get_column_letter(n + 1 + k)}{FILA}"            # valor del programa
        comparar.append(
            f'=IF(ISERROR({a}),IF(ISERROR({b}),"OK",IF({b}="#¡VALOR!","OK","DIF")),'
            f'IF(AND(ISNUMBER({a}),ISNUMBER({b})),IF(ABS({a}-{b})<={TOLERANCIA},"OK","DIF"),'
            f'IF(({a}&"")=({b}&""),"OK","DIF")))')
    primera_col, ultima_col = get_column_letter(n + 2), get_column_letter(n + 1 + len(cols))
    for r in range(3, ultima_fila + 1):
        for j in range(1, n + 1):
            hoja.cell(r, j, f"=Sheet1!{get_column_letter(pos[fijas[j - 1]])}{r}")
        hoja.cell(r, col_total, f'=COUNTIF({primera_col}{r}:{ultima_col}{r},"DIF")')
        for k, formula in enumerate(comparar):
            hoja.cell(r, n + 2 + k, formula.replace(FILA, str(r)))
    # fila 1: ítems con alguna diferencia y cuántos "DIF" hay en cada columna
    negrita = Font(bold=True)
    hoja.cell(1, n, "# DIF:").font = negrita
    letra_total = get_column_letter(col_total)
    hoja.cell(1, col_total, f'=COUNTIF({letra_total}3:{letra_total}{ultima_fila},">0")').font = negrita
    for k in range(len(cols)):
        letra = get_column_letter(n + 2 + k)
        hoja.cell(1, n + 2 + k, f'=COUNTIF({letra}3:{letra}{ultima_fila},"DIF")').font = negrita
    rojo = PatternFill("solid", fgColor="F4A7A7")
    hoja.conditional_formatting.add(f"{primera_col}3:{ultima_col}{ultima_fila}",
                                    CellIsRule(operator="equal", formula=['"DIF"'], fill=rojo))
    hoja.conditional_formatting.add(f"{letra_total}1:{ultima_col}1",
                                    CellIsRule(operator="greaterThan", formula=["0"], fill=rojo))
    hoja.conditional_formatting.add(f"{letra_total}3:{letra_total}{ultima_fila}",
                                    CellIsRule(operator="greaterThan", formula=["0"], fill=rojo))
    hoja.auto_filter.ref = f"A2:{ultima_col}{ultima_fila}"
    hoja.freeze_panes = f"{get_column_letter(col_total + 1)}3"
