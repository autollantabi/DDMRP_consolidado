#ExportarExcel
# Exporta core.ddmrp_llantas_consolidado (DDMRP normal + mensualizado) a Excel con el formato del
# archivo REORDENADO_UNIFICADO.xlsx: colores de fila, colores de columna, colores de encabezado,
# anchos, columnas ocultas/agrupadas y formato de números.
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
# los filtros (LLANTAS y LLANTAS MOTO, activos y de compra) ya vienen de ddmrp_consolidado.py
query = """
select * from core.ddmrp_llantas_consolidado;
"""

# --- 2. NOMBRE DEL ARCHIVO ---
# Reporte de Pedidos Consolidado (Marcas) (Empresa) (fecha de creación DD-MM-AAAA).xlsx
MARCAS  = "NEUMATICOS"
EMPRESA = "TODAS"
HOY     = date.today().strftime("%d-%m-%Y")
# Carpeta "REPORTES DDMRP" en la raíz del proyecto (se crea sola si no existe)
CARPETA_REPORTES = RAIZ_PROYECTO / "REPORTES DDMRP"
CARPETA = CARPETA_REPORTES / HOY
output_file = CARPETA / f"Reporte de Pedidos Consolidado ({MARCAS}) ({EMPRESA}) ({HOY}).xlsx"

# --- 3. COLUMNAS (nombres en core.ddmrp_llantas_consolidado) ---
COL_DIAS_INV_90D = "DIAS INV 90D"
COL_DIAS_INV_1A  = "DIAS INV 1 AÑO"
COL_DIF_PICO     = "DIF. MAX AÑO vs TOT. AÑO"
COL_BARRAS       = "BARRAS"
# columnas que en la tabla son texto porque mezclan palabras y números: los números se pasan a número
COLUMNAS_TEXTO_NUMERO = ["MES DE STOCK PROYECT MAX ADU DLT", "PEDIDO SUGERIDO JP"]

# --- 4. COLORES ---
NARANJA       = PatternFill("solid", fgColor="FFC000")
ROJO          = PatternFill("solid", fgColor="FF0000")
VERDE         = PatternFill("solid", fgColor="92D050")
GRIS_CLARO    = PatternFill("solid", fgColor="D9D9D9")
GRIS_OSCURO   = PatternFill("solid", fgColor="A6A6A6")
AZUL          = PatternFill("solid", fgColor="9BC2E6")
AMARILLO      = PatternFill("solid", fgColor="FFFF00")
TOMATE_PALIDO = PatternFill("solid", fgColor="F8CBAD")

# 1. NARANJA: DIAS INV 90D < 68
# 2. ROJO:    DIAS INV 90D < 68  y  DIAS INV 1 AÑO < 275   (se pinta encima del naranja)
# 3. VERDE:   DIF. MAX AÑO vs TOT. AÑO = 'SI'              (se pinta al final, encima de los otros)
LIMITE_DIAS_90D = 68
LIMITE_DIAS_1A  = 275

# 4. color de los DATOS de columnas completas (se pinta encima del color de la fila)
COLOR_DATOS = {
    "DEMANDA MES - AÑO":                           GRIS_CLARO,
    "DEMANDA MES 90D":                             GRIS_CLARO,
    "EN STOCK":                                    GRIS_OSCURO,
    "# MESES EN STOCK CON MAX ADU":                GRIS_OSCURO,
    "STOCK TOTAL":                                 AZUL,
    "MESES EN STOCK TOTAL CON MAX ADU":            AZUL,
    "MES INV TOTAL SEGUN DEMANDA 90D":             AZUL,        # oculta (como en el reporte normal)
    "MES DE STOCK PROYECT MAX ADU DLT":            AZUL,
    "VALIDADOR":                                   AZUL,
    "MESES EN PISO X CATEGORIA":                   AZUL,
    "MESES EN PISO + DLT X CATEGORIA CON MAX ADU": AZUL,
    "MESES X PEDIR TOTAL":                         AZUL,
    "PEDIDO SUGERIDO JP":                          TOMATE_PALIDO,
    "PEDIDO SUGERIDO AJUSTADO A PISO":             AMARILLO,
}

# 5. color del ENCABEZADO (fila 1), como en el Excel unificado
COLOR_ENCABEZADO = {
    "DEMANDA MES - AÑO":                           GRIS_CLARO,
    "ADU BASE":                                    AMARILLO,
    "DEMANDA MES 90D":                             GRIS_CLARO,
    "ADU 90 DÍAS":                                 AMARILLO,
    "Ratio de cambio":                             AMARILLO,    # oculta
    "EN STOCK":                                    GRIS_OSCURO,
    "# MESES EN STOCK CON MAX ADU":                AMARILLO,
    "# MESES EN TRANSITO":                         AMARILLO,    # oculta
    "# MESES EN PEDIDOS":                          AMARILLO,    # oculta
    "# MESES EN BACK ORDERS":                      AMARILLO,    # oculta
    "STOCK TOTAL":                                 AZUL,
    "MESES EN STOCK TOTAL CON MAX ADU":            AMARILLO,
    "MES INV TOTAL SEGUN DEMANDA 90D":             AZUL,        # oculta
    "STOCK PROYECTADO DLT CON MAX ADU":            AMARILLO,
    "MES DE STOCK PROYECT MAX ADU DLT":            AMARILLO,
    "VALIDADOR":                                   AMARILLO,
    "MESES EN PISO X CATEGORIA":                   AMARILLO,
    "MESES EN PISO + DLT X CATEGORIA CON MAX ADU": AMARILLO,
    "MESES X PEDIR TOTAL":                         AMARILLO,
    "PEDIDO ESTANDAR DDMRP":                       AMARILLO,    # oculta
    "FLUJO NETO (NFP) AJUSTADO":                   AMARILLO,
    "PEDIDO AJUSTADO DDMRP":                       AMARILLO,    # oculta
    "NUEVO TAMAÑO PEDIDO":                         AMARILLO,
    "PEDIDO SUGERIDO JP":                          TOMATE_PALIDO,
    "PEDIDO SUGERIDO AJUSTADO A PISO":             AMARILLO,
    "# DE MESES DEL PEDIDO SEGÚN MAX ADU":         AMARILLO,
}

# 6. columnas ocultas SIN agrupar (en el Excel unificado está oculta)
COLUMNAS_OCULTAS = ["FLUJO NETO (NFP) AJUSTADO"]

# 7. columnas que no están en el Excel unificado: agrupadas y ocultas junto a las relacionadas
#    (cada línea va desde su primera hasta su última columna; deben estar seguidas en el reporte)
GRUPOS = [
    ("GRUPO", "DISEÑO"),
    ("ACTIVO", "ARTICULO_COMPRA"),
    ("Ratio de cambio", "ADU"),
    ("TRANSITO 15D", "# MESES EN TRANSITO"),
    ("Pedidos15D", "# MESES EN PEDIDOS"),
    ("Backorders_15D", "# MESES EN BACK ORDERS"),
    ("MES INV TOTAL SEGUN DEMANDA 90D", "MES INV TOTAL SEGUN DEMANDA 90D"),
    ("LTF", "VF"),
    ("PEDIDO ESTANDAR DDMRP", "PEDIDO ESTANDAR DDMRP"),
    ("PEDIDO AJUSTADO DDMRP", "PEDIDO AJUSTADO DDMRP"),
    ("NFP JP", "PROD CON STOCK SIN VENTAS"),
]

# 8. formato de números (las demás columnas quedan en General), como en el Excel unificado
FORMATO_NUMEROS = {
    "ADU BASE":                                    "0.00",
    "ADU 90 DÍAS":                                 "#,##0.00",
    "Ratio de cambio":                             "0.00%",
    "# MESES EN STOCK CON MAX ADU":                "0.00",
    "# MESES EN TRANSITO":                         "0.00",
    "# MESES EN PEDIDOS":                          "0.00",
    "# MESES EN BACK ORDERS":                      "0.00",
    "MESES EN STOCK TOTAL CON MAX ADU":            "0.00",
    "MES DE STOCK PROYECT MAX ADU DLT":            "0.00",
    "MESES EN PISO X CATEGORIA":                   "0.00",
    "MESES EN PISO + DLT X CATEGORIA CON MAX ADU": "0.00",
    "MESES X PEDIR TOTAL":                         "0.00",
    "TAMAÑO BUFFER (TOG)":                         "0",
    "FLUJO NETO (NFP)":                            "0",
    "PEDIDO ESTANDAR DDMRP":                       "#,##0",
    "TAMAÑO PEDIDO":                               "#,##0",
    "FLUJO NETO (NFP) AJUSTADO":                   "#,##0",
    "PEDIDO AJUSTADO DDMRP":                       "#,##0",
    "NUEVO TAMAÑO PEDIDO":                         "#,##0",
    "TAMAÑO 3 MESES INVT. SEGÚN ADU 90D":          "#,##0",
    "PEDIDO SUGERIDO JP":                          "#,##0",
    "PEDIDO SUGERIDO AJUSTADO A PISO":             "0.00",
    "# DE MESES DEL PEDIDO SEGÚN MAX ADU":         "0.00",
    "ULTIMA COMPRA":                               "yyyy-mm-dd",
    "ULTIMA VENTA":                                "yyyy-mm-dd",
}

# 9. ancho de columnas, como en el Excel unificado (las que no están quedan con ANCHO_POR_DEFECTO)
ANCHO_POR_DEFECTO = 13
ANCHOS = {
    "CODIGO_ITEM": 11.44, "COD. PROV1": 15.11, "PROV1": 41.44, "COD. PROV2": 11.44,
    "DESCRIPCION": 51, "ANT.": 8, "TOP": 6.89, "CLASIF. PARETO": 7.55, "UN (#) - AÑO": 6.66,
    "PICO ULT. AÑO X FACTURA": 8.33, "DIF. MAX AÑO vs TOT. AÑO": 6.89, "DIAS INV 1 AÑO": 6.11,
    "DEMANDA MES - AÑO": 9.89, "ADU BASE": 5.33, "UN (#) - 90D": 7, "DIAS INV 90D": 5.11,
    "DEMANDA MES 90D": 9.89, "ADU 90 DÍAS": 6.33, "% VARIACIÓN DEMANDA": 7.33, "EN STOCK": 9.89,
    "# MESES EN STOCK CON MAX ADU": 8.11, "TRANSITOS TOTAL": 10.55, "VALIDADOR": 31.44, "DLT": 6.44,
    "TAMAÑO BUFFER (TOG)": 11.33, "FLUJO NETO (NFP)": 9.33,
}

ALTO_ENCABEZADO = 86.4   # alto de la fila 1, con texto ajustado


def pintar_columna(ws, col, n_filas, relleno):
    for (celda,) in ws.iter_rows(min_col=col, max_col=col, min_row=2, max_row=n_filas + 1):
        celda.fill = relleno


def dar_formato(ws, df):
    """Aplica el formato del Excel unificado: filas, columnas, encabezados, ocultas, grupos, números y anchos."""
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

    # 4. color de datos de columnas completas
    for c, relleno in COLOR_DATOS.items():
        if c in pos:
            pintar_columna(ws, pos[c], n_filas, relleno)
        else:
            faltan.append(c)

    # 5. color del encabezado
    for c, relleno in COLOR_ENCABEZADO.items():
        if c in pos:
            ws.cell(row=1, column=pos[c]).fill = relleno
        else:
            faltan.append(c)

    # 6. ocultar columnas sin agrupar
    for c in COLUMNAS_OCULTAS:
        if c in letra:
            ws.column_dimensions[letra[c]].hidden = True
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

    # 9. anchos (no se cambian las columnas ocultas por grupo)
    ocultas_grupo = set()
    for desde, hasta in GRUPOS:
        if desde in pos and hasta in pos:
            ocultas_grupo.update(range(pos[desde], pos[hasta] + 1))
    for c in columnas:
        if pos[c] not in ocultas_grupo and c not in COLUMNAS_OCULTAS:
            ws.column_dimensions[letra[c]].width = ANCHOS.get(c, ANCHO_POR_DEFECTO)
    faltan.extend(c for c in ANCHOS if c not in pos)

    # encabezado: texto ajustado arriba, fila alta y filtro en todas las columnas
    for celda in ws[1][:n_cols]:
        celda.alignment = Alignment(wrap_text=True, vertical="top")
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
    """'12.50' -> 12.5; los textos ('INFINITO', ...) quedan igual."""
    numeros = pd.to_numeric(serie, errors="coerce")
    return numeros.astype(object).where(numeros.notna(), serie)


def main():
    print("Conectando a PostgreSQL y ejecutando consulta...")
    engine = get_engine_postgres_dwh()
    df = pd.read_sql_query(query, engine)

    # columnas texto que tienen números: los números se exportan como número (no como texto)
    for c in COLUMNAS_TEXTO_NUMERO:
        if c in df.columns:
            df[c] = texto_a_numero(df[c])

    # ordenar por BARRAS de la A a la Z (vacíos al final)
    df = df.sort_values(COL_BARRAS, na_position="last", kind="stable").reset_index(drop=True)

    print(f"Exportando {len(df)} filas a Excel...")
    CARPETA.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
        dar_formato(writer.sheets["Sheet1"], df)
        agregar_explicacion(writer.book)
    print(f"¡Éxito! Archivo guardado correctamente como '{output_file}'")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Ocurrió un error durante el proceso: {e}")
        sys.exit(1)
