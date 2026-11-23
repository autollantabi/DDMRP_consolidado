#ExportarExcel
# Exporta core.ddmrp_llantas_mes (DDMRP mensualizado) a Excel con el formato del archivo
# DDMRP_GRUPOVI_LLANTAS_V16: colores de fila, colores de columna, encabezados amarillos de las
# columnas nuevas, columnas ocultas y agrupadas, y formato de números.
# Las columnas se buscan por NOMBRE (no por letra), así el formato no se daña si cambia el orden.
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, PatternFill
from openpyxl.utils import get_column_letter

# Raíz del proyecto = carpeta donde está este script (DDMRP_consolidado)
RAIZ_PROYECTO = Path(__file__).resolve().parent
# config.py puede estar en la raíz o dentro de la carpeta "conection"
sys.path.insert(0, str(RAIZ_PROYECTO))
sys.path.insert(0, str(RAIZ_PROYECTO / "conection"))
from config import get_engine_postgres_dwh

# --- 1. CONSULTA SQL ---
# los filtros (LLANTAS y LLANTAS MOTO, activos y de compra) ya vienen de llantas_mes.py
query = """
select * from core.ddmrp_llantas_mes;
"""

# --- 2. NOMBRE DEL ARCHIVO ---
# Reporte de Pedidos Mensualizado (Marcas) (Empresa) (fecha de creación DD-MM-AAAA).xlsx
MARCAS  = "NEUMATICOS"
EMPRESA = "TODAS"
HOY     = date.today().strftime("%d-%m-%Y")
# Carpeta "REPORTES DDMRP" en la raíz del proyecto (se crea sola si no existe)
CARPETA_REPORTES = RAIZ_PROYECTO / "REPORTES DDMRP"
CARPETA = CARPETA_REPORTES / HOY
output_file = CARPETA / f"Reporte de Pedidos Mensualizado ({MARCAS}) ({EMPRESA}) ({HOY}).xlsx"

# --- 3. COLUMNAS (nombres en core.ddmrp_llantas_mes) ---
COL_DIAS_INV_90D = "DIAS INV 90D"
COL_DIAS_INV_1A  = "DIAS INV 1 AÑO"
COL_DIF_PICO     = "DIF. MAX AÑO vs TOT. AÑO"
COL_BARRAS       = "BARRAS"
# columnas que en la tabla son texto porque mezclan palabras y números: los números se pasan a número
COLUMNAS_TEXTO_NUMERO = ["VALIDADOR", "MES DE STOCK PROYECT MAX ADU DLT"]

# --- 4. COLORES ---
NARANJA     = PatternFill("solid", fgColor="FFC000")
ROJO        = PatternFill("solid", fgColor="FF0000")
VERDE       = PatternFill("solid", fgColor="92D050")
GRIS_CLARO  = PatternFill("solid", fgColor="D9D9D9")
GRIS_OSCURO = PatternFill("solid", fgColor="A6A6A6")
AZUL        = PatternFill("solid", fgColor="9BC2E6")
AMARILLO    = PatternFill("solid", fgColor="FFFF00")

# 1. NARANJA: DIAS INV 90D < 68
# 2. ROJO:    DIAS INV 90D < 68  y  DIAS INV 1 AÑO < 275   (se pinta encima del naranja)
# 3. VERDE:   DIF. MAX AÑO vs TOT. AÑO = 'SI'              (se pinta al final, encima de los otros)
LIMITE_DIAS_90D = 68
LIMITE_DIAS_1A  = 275

# 4. columnas ocultas SIN agrupar
COLUMNAS_OCULTAS = ["ACTIVO", "ARTICULO_COMPRA"]

# 5. color de columnas completas (datos y encabezado; se pinta después de las filas)
COLOR_COLUMNAS = {
    "DEMANDA MES - AÑO":                GRIS_CLARO,
    "DEMANDA MES 90D":                  GRIS_CLARO,
    "EN STOCK":                         GRIS_OSCURO,
    "# MESES EN STOCK":                 GRIS_OSCURO,
    "STOCK TOTAL":                      AZUL,
    "MESES EN STOCK TOTAL":             AZUL,
    "VALIDADOR":                        AZUL,
    "MES DE STOCK PROYECT MAX ADU DLT": AZUL,
    "MESES EN PISO X CATEGORIA":        AZUL,
    "MESES EN PISO + DLT X CATEGORIA":  AZUL,
}

# 6. encabezado en amarillo: columnas nuevas del DDMRP mensualizado (se pinta al final)
ENCABEZADO_AMARILLO = [
    "# MESES EN STOCK", "# MESES EN TRANSITO", "# MESES EN PEDIDOS", "# MESES EN BACK ORDERS",
    "MESES EN STOCK TOTAL", "STOCK PROYECTADO DLT", "VALIDADOR", "MES DE STOCK PROYECT MAX ADU DLT",
    "MESES EN PISO X CATEGORIA", "MESES EN PISO + DLT X CATEGORIA", "MESES X PEDIR TOTAL",
    "ADU BASE", "ADU 90 DÍAS", "Ratio de cambio", "ZONA VERDE",
    "PEDIDO ESTANDAR DDMRP", "FLUJO NETO (NFP) AJUSTADO", "PEDIDO AJUSTADO DDMRP",
    "PEDIDO SUGERIDO AJUSTADO A PISO", "# DE MESES DEL PEDIDO",
]

# 7. columnas que se agrupan y quedan ocultas: cada línea va desde su primera hasta su última columna
#    (las columnas deben estar seguidas en el reporte)
GRUPOS = [
    ("CODIGO_ITEM", "PROV2"),
    ("GRUPO", "PROPIEDAD"),
    ("RIN", "RIN"),
    ("SERIE", "ANCHO"),
    ("BARRAS", "DISEÑO"),
    ("TRANSITO 15D", "TRANSITO >45D"),
    ("# MESES EN TRANSITO", "# MESES EN TRANSITO"),
    ("Pedidos15D", "Pedidos>45D"),
    ("# MESES EN PEDIDOS", "# MESES EN PEDIDOS"),
    ("Backorders_15D", "Backorders>30D"),
    ("# MESES EN BACK ORDERS", "# MESES EN BACK ORDERS"),
    ("LTF", "VF"),
    ("ADU SIN PICOS", "ADU SIN PICOS"),
    ("ZONA ROJA BASE", "LIMITE ZONA AMARILLA (TOY)"),
    ("ZONA VERDE", "ZONA VERDE"),
]

# 8. formato de números (las demás columnas quedan en General)
FORMATO_NUMEROS = {
    "# MESES EN STOCK":                 "0.00",
    "# MESES EN TRANSITO":              "0.00",
    "# MESES EN PEDIDOS":               "0.00",
    "# MESES EN BACK ORDERS":           "0.00",
    "MESES EN STOCK TOTAL":             "0.00",
    "MES DE STOCK PROYECT MAX ADU DLT": "0.00",
    "MESES EN PISO X CATEGORIA":        "0.00",
    "MESES EN PISO + DLT X CATEGORIA":  "0.00",
    "MESES X PEDIR TOTAL":              "0.00",
    "ADU BASE":                         "0.00",
    "ADU 90 DÍAS":                      "#,##0.00",
    "Ratio de cambio":                  "0.00%",
    "ZONA ROJA BASE":                   "0",
    "ZONA ROJA SEGURIDAD":              "0",
    "ZONA ROJA (TOR)":                  "0",
    "ZONA AMARILLA":                    "0",
    "LIMITE ZONA AMARILLA (TOY)":       "0",
    "ZONA VERDE":                       "0",
    "TAMAÑO BUFFER (TOG)":              "0",
    "FLUJO NETO (NFP)":                 "0",
    "PEDIDO ESTANDAR DDMRP":            "#,##0",
    "FLUJO NETO (NFP) AJUSTADO":        "#,##0",
    "PEDIDO AJUSTADO DDMRP":            "#,##0",
    "PEDIDO SUGERIDO AJUSTADO A PISO":  "0.00",
    "# DE MESES DEL PEDIDO":            "0.00",
    "ULTIMA COMPRA":                    "yyyy-mm-dd",
    "ULTIMA VENTA":                     "yyyy-mm-dd",
}

ALTO_ENCABEZADO = 75   # alto de la fila 1, con texto ajustado


def pintar_columna(ws, col, n_filas, relleno, desde_fila=1):
    for (celda,) in ws.iter_rows(min_col=col, max_col=col, min_row=desde_fila, max_row=n_filas + 1):
        celda.fill = relleno


def dar_formato(ws, df):
    """Aplica el formato del V16: filas, colores de columna, encabezados, ocultas, grupos y números."""
    columnas = list(df.columns)
    pos = {c: i + 1 for i, c in enumerate(columnas)}
    letra = {c: get_column_letter(i) for c, i in pos.items()}
    n_cols, n_filas = len(columnas), len(df)
    faltan = []

    # 1-3. pintar filas (la fila 1 es el encabezado: los datos empiezan en la 2)
    dias_90d = pd.to_numeric(df[COL_DIAS_INV_90D], errors="coerce")
    dias_1a = pd.to_numeric(df[COL_DIAS_INV_1A], errors="coerce")
    naranja = dias_90d < LIMITE_DIAS_90D
    rojo = naranja & (dias_1a < LIMITE_DIAS_1A)
    verde = df[COL_DIF_PICO] == "SI"
    for i in range(n_filas):
        if verde.iat[i]:
            relleno = VERDE
        elif rojo.iat[i]:
            relleno = ROJO
        elif naranja.iat[i]:
            relleno = NARANJA
        else:
            continue
        for celda in ws[i + 2][:n_cols]:
            celda.fill = relleno
    print(f"Filas pintadas: naranja {int((naranja & ~rojo & ~verde).sum())} | "
          f"rojo {int((rojo & ~verde).sum())} | verde {int(verde.sum())}")

    # 4. ocultar columnas sin agrupar
    for c in COLUMNAS_OCULTAS:
        if c in letra:
            ws.column_dimensions[letra[c]].hidden = True
        else:
            faltan.append(c)

    # 5. colorear columnas completas
    for c, relleno in COLOR_COLUMNAS.items():
        if c in pos:
            pintar_columna(ws, pos[c], n_filas, relleno)
        else:
            faltan.append(c)

    # 6. encabezado amarillo de las columnas nuevas
    for c in ENCABEZADO_AMARILLO:
        if c in pos:
            ws.cell(row=1, column=pos[c]).fill = AMARILLO
        else:
            faltan.append(c)

    # 7. agrupar y ocultar
    for desde, hasta in GRUPOS:
        if desde in letra and hasta in letra:
            ws.column_dimensions.group(letra[desde], letra[hasta], outline_level=1, hidden=True)
        else:
            faltan.extend(c for c in (desde, hasta) if c not in letra)

    # 8. formato de números
    for c, formato in FORMATO_NUMEROS.items():
        if c not in pos:
            faltan.append(c)
            continue
        for (celda,) in ws.iter_rows(min_col=pos[c], max_col=pos[c], min_row=2, max_row=n_filas + 1):
            celda.number_format = formato

    # encabezado: texto ajustado, fila alta y filtro en todas las columnas
    for celda in ws[1][:n_cols]:
        celda.alignment = Alignment(wrap_text=True)
    ws.row_dimensions[1].height = ALTO_ENCABEZADO
    ws.auto_filter.ref = f"A1:{get_column_letter(n_cols)}{n_filas + 1}"

    if faltan:
        print("Columnas del formato que no están en el reporte (se saltan):", ", ".join(dict.fromkeys(faltan)))


# Hoja con la explicación de los colores de las filas (texto en A2:A4, cada uno con su color)
HOJA_EXPLICACION = "EXPLICACIÓN COLORES"
EXPLICACION_COLORES = [
    ("NARANJA = DIAS INV 90D MENOR A 68 DIAS", NARANJA),
    ("ROJO = DIAS INV 1 AÑO MENOR A 275 DIAS", ROJO),
    ("VERDE = DIF PICO VTAS ULT AÑO VS # VTAS ULT AÑO = SI", VERDE),
]


def agregar_explicacion(wb):
    """Agrega la hoja EXPLICACIÓN COLORES."""
    ws = wb.create_sheet(HOJA_EXPLICACION)
    for fila, (texto, relleno) in enumerate(EXPLICACION_COLORES, start=2):
        celda = ws.cell(row=fila, column=1, value=texto)
        celda.fill = relleno
    ws.column_dimensions["A"].width = 75


def texto_a_numero(serie):
    """'12.50' -> 12.5; los textos ('INFINITO', 'REVISAR PARA INACTIVAR', ...) quedan igual."""
    numeros = pd.to_numeric(serie, errors="coerce")
    return numeros.astype(object).where(numeros.notna(), serie)


try:
    print("Conectando a PostgreSQL y ejecutando consulta...")
    engine = get_engine_postgres_dwh()

    # Cargar el resultado directamente en un DataFrame de Pandas
    df = pd.read_sql_query(query, engine)

    # VALIDADOR y MES DE STOCK: los números se exportan como número (no como texto)
    for c in COLUMNAS_TEXTO_NUMERO:
        if c in df.columns:
            df[c] = texto_a_numero(df[c])

    # ordenar por BARRAS de la A a la Z (vacíos al final)
    df = df.sort_values(COL_BARRAS, na_position="last", kind="stable").reset_index(drop=True)

    print(f"Exportando {len(df)} filas a Excel...")
    CARPETA.mkdir(parents=True, exist_ok=True)

    # Exportar a Excel (index=False evita exportar el número de fila implícito de Pandas)
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
        dar_formato(writer.sheets["Sheet1"], df)
        agregar_explicacion(writer.book)

    print(f"¡Éxito! Archivo guardado correctamente como '{output_file}'")

except Exception as e:
    print(f"Ocurrió un error durante el proceso: {e}")
    sys.exit(1)
