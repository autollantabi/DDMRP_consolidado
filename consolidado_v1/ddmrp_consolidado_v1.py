# =============================================================================
# DDMRP LLANTAS CONSOLIDADO - v1
#
# SOLO LECTURA: no crea tablas ni modifica nada en el DWH. Lee los datos (de las tablas resumen
# tal como están hoy en el DWH), hace todos los cálculos del Excel "Reporte de Pedidos Consolidado
# (final, revisado 12-11-2026)" en UNA consulta SQL y los muestra en una ventana (con botón para
# exportar a Excel).
#
# ARCHIVOS (carpeta DDMRP\consolidado_v1):
#   ddmrp_consolidado_v1.py  (este)  filtros, datos de origen, columnas del reporte y programa  <- se ejecuta este
#   formulas_ddmrp_v1.sql            TODAS las fórmulas, en SQL, una por columna  <- cambiar fórmulas aquí
#   ddmrp_v1_motor.py                arma la consulta con las fórmulas (no se toca)
#   ddmrp_v1_ventana.py              cómo se dibuja la ventana, con Qt (PySide6) (normalmente no se toca)
#   ddmrp_v1_legible.py              pestaña Cálculos: muestra cada fórmula del .sql como fórmula de Excel (solo muestra)
#   ddmrp_v1_excel.py                botón "Exportar a Excel": formato del Excel final (colores, formatos, anchos)
# Usa además (no se mueven, son compartidos con los otros scripts del DDMRP):
#   DDMRP\conection\config.py                     conexión al DWH
#   DDMRP\tablas_resumen\ddmrp_proveedor_item.py  marcas de IKONIX -> proveedor (solo se leen constantes)
#
# SECCIONES DE ESTE ARCHIVO:
#   1. FILTROS DEL DDMRP ..... qué ítems entran (salen como tarjetas en la ventana)
#   2. DATOS DE ORIGEN ....... consulta SQL: de qué tabla sale cada dato (sin cálculos)
#   3. REPORTE ............... columnas en el orden del Excel, grupos y columnas ocultas como el Excel,
#                              colores de fila, indicadores y filtros de la ventana
#   4. PROGRAMA .............. lee -> muestra (normalmente no se toca)
# =============================================================================
import sys
from decimal import Decimal
from pathlib import Path

import pandas as pd
import psycopg2

CARPETA_V1 = Path(__file__).resolve().parent                     # ...\DDMRP\consolidado_v1
CARPETA_DDMRP = CARPETA_V1.parent                                 # ...\Scripts\DDMRP
sys.path.insert(0, str(CARPETA_DDMRP / "conection"))              # config.py (conexión al DWH)
sys.path.insert(0, str(CARPETA_DDMRP / "tablas_resumen"))         # constantes de IKONIX
from config import POSTGRES

import ddmrp_v1_motor as motor
import ddmrp_v1_ventana

ARCHIVO_FORMULAS = CARPETA_V1 / "formulas_ddmrp_v1.sql"


# =============================================================================
# 1. FILTROS DEL DDMRP
#    Se aplican en la consulta (WHERE), en este orden, unidos con AND.
#      tarjeta / valor: lo que se ve en la tarjeta de la ventana
#      sql:             la condición tal cual va en el WHERE (b = core.dim_item)
# =============================================================================
FILTROS_DDMRP = [
    {"tarjeta": "ACTIVO",             "valor": "SI",
     "sql": "b.dit_activo = 'SI'",                           "descripcion": "Ítem activo"},
    {"tarjeta": "ARTÍCULO DE COMPRA", "valor": "Y",
     "sql": "b.dit_compra = 'Y'",                            "descripcion": "Ítem de compra"},
    {"tarjeta": "GRUPOS",             "valor": "LLANTAS · LLANTAS MOTO",
     "sql": "b.dit_grupo IN ('HERRAMIENTAS')",    "descripcion": "Grupos del DDMRP de llantas"},
]


# =============================================================================
# 2. DATOS DE ORIGEN
#    Una fila por ítem con los datos tal como vienen de las tablas (sin cálculos: los cálculos
#    están en formulas_ddmrp_v1.sql). {FILTROS} se reemplaza por las condiciones de la sección 1.
#    Las columnas que empiezan con "_" son auxiliares: se usan en las fórmulas pero no se muestran.
#
#    Tablas (todas se leen tal como están en el DWH; las actualizan las opciones del DDMRP.bat):
#      b  = core.dim_item                 datos del ítem, costos y precio
#      p  = core.ddmrp_proveedor_item     proveedor 1 y 2
#      t  = core.ddmrp_medidas_top        TOP
#      f  = core.ddmrp_abc                CLASIF. PARETO (si el ítem está en 2 líneas, la mejor: A < B < C < D)
#      v  = core.vw_ddmrp_ventas          ventas (vista: se calcula al momento con los últimos 365 / 90 días)
#      i  = core.ddmrp_inventario         días con inventario
#      s  = core.ddmrp_bodegas            stock en bodegas
#      e  = core.vw_ddmrp_trans_ped       tránsitos, pedidos y backorders
#      vp = core.ddmrp_ventas_picos       CV, ADU sin picos y ADU con picos
#      dl = DLT del proveedor del ítem    (core.vw_ddmrp_item_proveedor + core.ddmrp_proveedores_dlt)
#      ik = DLT de IKONIX por marca       (marca -> proveedor de ddmrp_proveedor_item.py)
# =============================================================================
SQL_DLT_PROVEEDOR = """
SELECT ddmrp_empresa                          AS empresa,
       ddmrp_codigo_proveedor                 AS cod_proveedor,
       ROUND(AVG(ddmrp_dlt_max)::numeric, 2)  AS dlt_max,     -- todos los tiempos (incluye backorder)
       ROUND(AVG(ddmrp_dlt_min)::numeric, 2)  AS dlt_min      -- sin el tiempo de backorder
FROM core.ddmrp_proveedores_dlt
WHERE ddmrp_dlt_max > 0                                       -- proveedores sin DLT no cuentan
GROUP BY ddmrp_empresa, ddmrp_codigo_proveedor
"""

SQL_ITEMS = """
SELECT
    -- datos del ítem
    b.dit_empresa                                         AS "EMPRESA",
    b.dit_codigo                                          AS "CODIGO_ITEM",
    b.dit_codigoproveedor                                 AS "CODIGO PROVEEDOR",
    p.cod_prov1                                           AS "COD. PROV1",
    p.nom_prov1                                           AS "PROV1",
    p.cod_prov2                                           AS "COD. PROV2",
    p.nom_prov2                                           AS "PROV2",
    b.dit_nombre                                          AS "DESCRIPCION",
    b.dit_grupo                                           AS "GRUPO",
    b.dit_propiedad                                       AS "PROPIEDAD",
    b.dit_rin                                             AS "RIN",
    b.dit_serie                                           AS "SERIE",
    b.dit_ancho                                           AS "ANCHO",
    b.dit_nombrefabricante                                AS "MARCA",
    b.dit_codigobarras                                    AS "BARRAS",
    b.dit_disenio                                         AS "DISEÑO",
    b.dit_antiguedad                                      AS "ANT.",
    COALESCE(t.top, 'NO')                                 AS "TOP",
    f.segmento_final                                      AS "CLASIF. PARETO",
    b.dit_activo                                          AS "ACTIVO",
    b.dit_compra                                          AS "ARTICULO_COMPRA",
    -- ventas
    COALESCE(v."365D", 0)::numeric                        AS "UN (#) - AÑO",
    COALESCE(v.max_cantidad_anio, 0)::numeric             AS "PICO ULT. AÑO X FACTURA",
    COALESCE(v.supera_umbral, 'NO')                       AS "DIF. MAX AÑO vs TOT. AÑO",
    COALESCE(v."90D", 0)::numeric                         AS "UN (#) - 90D",
    COALESCE(v."MES", 0)::numeric                         AS "UNIDADES MES ACTUAL",
    v.ultima_venta                                        AS "ULTIMA VENTA",
    -- días con inventario (antes de la homologación y del mínimo de 1 día: ver fórmulas)
    COALESCE(i.ddmrp_stock_inv_1anio, 0)::numeric         AS "DIAS INV 1 AÑO",
    COALESCE(i."ddmrp_stock_inv_90D", 0)::numeric         AS "DIAS INV 90D",
    -- stock, tránsitos, pedidos y backorders
    s.sum::numeric                                        AS "EN STOCK",
    (COALESCE(e."Transito15D", 0) + COALESCE(e."Transito30D", 0)
     + COALESCE(e."Transito45D", 0) + COALESCE(e."Transito>45D", 0))::numeric AS "TRANSITOS TOTAL",
    e."Transito15D"::numeric                              AS "TRANSITO 15D",
    e."Transito30D"::numeric                              AS "TRANSITO 30D",
    e."Transito45D"::numeric                              AS "TRANSITO 45D",
    e."Transito>45D"::numeric                             AS "TRANSITO >45D",
    e.pedido::numeric                                     AS "PEDIDOS",
    e."Pedidos15D"::numeric                               AS "Pedidos15D",
    e."Pedidos30D"::numeric                               AS "Pedidos30D",
    e."Pedidos45D"::numeric                               AS "Pedidos45D",
    e."Pedidos>45D"::numeric                              AS "Pedidos>45D",
    e."Backorder"::numeric                                AS "BACKORDERS",
    e."Backorder15D"::numeric                             AS "Backorders_15D",
    e."Backorder30D"::numeric                             AS "Backorders_30D",
    e."Backorder>30D"::numeric                            AS "Backorders>30D",
    -- costos y precio (antes de la homologación: ver fórmulas)
    ROUND(COALESCE(b.dit_ultimofob, 0), 2)                AS "ULTIMO FOB",
    ROUND(COALESCE(b.dit_costopromedio, 0), 2)            AS "COSTO PROM",
    ROUND(COALESCE(b.dit_ultimocosto, 0), 2)              AS "ULT. COSTO",
    ROUND(COALESCE(b.dit_listaprecios_a, 0), 2)           AS "P. LISTA",
    b.dit_ultingreso                                      AS "ULTIMA COMPRA",
    -- auxiliares (no se muestran)
    COALESCE(ik.dlt_max, dl.dlt_max)                      AS "_DLT MAX PROVEEDOR",
    COALESCE(ik.dlt_min, dl.dlt_min)                      AS "_DLT MIN PROVEEDOR",
    vp.desviacion_estandar                                AS "_CV",
    (vp.hev_codigoitem IS NOT NULL)                       AS "_EN VENTAS PICOS",
    vp."ADU_SIN_PICOS"                                    AS "_ADU SIN PICOS",
    vp."ADU_CON_PICOS"                                    AS "_ADU CON PICOS"
FROM core.dim_item b
LEFT JOIN core.ddmrp_proveedor_item p ON p.empresa = b.dit_empresa AND p.codigo_item = b.dit_codigo
LEFT JOIN core.ddmrp_medidas_top    t ON t.dit_empresa = b.dit_empresa AND t.dit_codigo = b.dit_codigo
LEFT JOIN (SELECT empresa, codigo_item, MIN(segmento_final) AS segmento_final
           FROM core.ddmrp_abc GROUP BY empresa, codigo_item
          )                         f ON f.empresa = b.dit_empresa AND f.codigo_item = b.dit_codigo
LEFT JOIN core.vw_ddmrp_ventas      v ON v.hev_empresa = b.dit_empresa AND v.hev_codigoitem = b.dit_codigo
LEFT JOIN core.ddmrp_inventario     i ON i.ddmpr_empresa = b.dit_empresa AND i.ddmrp_item = b.dit_identificador
LEFT JOIN core.ddmrp_bodegas        s ON s.empresa = b.dit_empresa AND s.codigo = b.dit_codigo
LEFT JOIN core.vw_ddmrp_trans_ped   e ON e.dit_empresa = b.dit_empresa AND e.dit_codigo = b.dit_codigo
LEFT JOIN (SELECT DISTINCT hev_empresa, hev_codigoitem, desviacion_estandar, "ADU_SIN_PICOS", "ADU_CON_PICOS"
           FROM core.ddmrp_ventas_picos
          )                         vp ON vp.hev_empresa = b.dit_empresa AND vp.hev_codigoitem = b.dit_codigo
LEFT JOIN (SELECT ip.empresa, ip.codigoitem,
                  ROUND(AVG(pr.dlt_max), 2) AS dlt_max, ROUND(AVG(pr.dlt_min), 2) AS dlt_min
           FROM core.vw_ddmrp_item_proveedor ip
           JOIN ({SQL_DLT_PROVEEDOR}) pr ON pr.empresa = ip.empresa AND pr.cod_proveedor = ip.heim_codigoproveedor
           GROUP BY ip.empresa, ip.codigoitem
          )                         dl ON dl.empresa = b.dit_empresa AND dl.codigoitem = b.dit_codigo
LEFT JOIN (SELECT m.marca, pr.dlt_max, pr.dlt_min
           FROM (VALUES {MARCAS_IKONIX}) AS m(marca, cod_proveedor)
           JOIN ({SQL_DLT_PROVEEDOR}) pr ON pr.empresa = '{EMPRESA_IKONIX}' AND pr.cod_proveedor = m.cod_proveedor
          )                         ik ON b.dit_empresa = '{EMPRESA_IKONIX}' AND UPPER(TRIM(b.dit_nombrefabricante)) = ik.marca
WHERE {FILTROS}
"""


# =============================================================================
# 3. REPORTE
# =============================================================================
# Columnas que se muestran, en el orden del Excel final (las que no están aquí no se muestran)
COLUMNAS_REPORTE = [
    "EMPRESA", "CODIGO_ITEM", "CODIGO PROVEEDOR", "COD. PROV1", "PROV1", "COD. PROV2", "PROV2",
    "DESCRIPCION", "GRUPO", "PROPIEDAD", "RIN", "SERIE", "ANCHO", "MARCA", "BARRAS", "DISEÑO", "ANT.",
    "TOP", "CLASIF. PARETO", "ACTIVO", "ARTICULO_COMPRA",
    "UN (#) - AÑO", "PICO ULT. AÑO X FACTURA", "DIF. MAX AÑO vs TOT. AÑO", "DIAS INV 1 AÑO", "DEMANDA MES - AÑO",
    "ADU BASE", "UN (#) - 90D", "DIAS INV 90D", "DEMANDA MES 90D", "ADU 90 DÍAS", "MAX ADU", "ADU SIN PICOS",
    "% VARIACIÓN DEMANDA", "UNIDADES MES ACTUAL",
    "EN STOCK", "# MESES EN STOCK CON MAX ADU", "MESES STOCK EN SEGÚN ADU",
    "TRANSITOS TOTAL", "TRANSITO 15D", "TRANSITO 30D", "TRANSITO 45D", "TRANSITO >45D", "# MESES EN TRANSITO",
    "PEDIDOS", "Pedidos15D", "Pedidos30D", "Pedidos45D", "Pedidos>45D", "# MESES EN PEDIDOS",
    "BACKORDERS", "Backorders_15D", "Backorders_30D", "Backorders>30D", "# MESES EN BACK ORDERS",
    "STOCK TOTAL", "# MESES EN STOCK TOTALSEGUN ADU", "# MES INV TOTAL SEGUN DEMANDA 90D",
    "# MESES EN STOCK TOTAL CON MAX ADU", "STOCK PROYECTADO DLT CON MAX ADU", "# MES DE STOCK PROYECT MAX ADU DLT",
    "VALIDADOR", "MESES EN PISO X CATEGORIA", "MESES EN PISO + DLT X CATEGORIA CON MAX ADU", "MESES X PEDIR TOTAL",
    "MESES X PEDIR PARA PISO", "DLT", "LTF", "VF",
    "ZONA ROJA BASE", "ZONA ROJA SEGURIDAD", "ZONA ROJA (TOR)", "ZONA AMARILLA", "LIMITE ZONA AMARILLA (TOY)",
    "ZONA VERDE", "TAMAÑO BUFFER (TOG)", "FLUJO NETO (NFP)", "TAMAÑO 3 MESES SEGÚN MAX ADU",
    "PEDIDO ESTANDAR DDMRP", "PEDIDO ESTANDAR DDMRP AJUS TAMAÑO MAX 3 MESES",
    "FLUJO NETO (NFP) AJUSTADO", "PEDIDO AJUSTADO DDMRP", "PEDIDO AJUSTADO DDMRP AJUS TAMAÑO MAX 3 MESES",
    "FLUJO NETO (NFP) AJUSTADO JP", "PEDIDO AJUSTADO DDMRP JP",
    "PEDIDO SUGERIDO AJUSTADO A PISO", "# DE MESES DEL PEDIDO SEGÚN MAX ADU",
    "ULTIMO FOB", "ULTIMA COMPRA", "COSTO PROM", "ULT. COSTO", "P. LISTA", "P. LISTA VS ULT.COSTO",
    "ULTIMA VENTA", "OBSERVACIONES",
]

# Columnas que en la fórmula son texto porque mezclan números y palabras ("INFINITO"):
# los números se muestran y exportan como número
COLUMNAS_TEXTO_CON_NUMEROS = ["# MES DE STOCK PROYECT MAX ADU DLT"]

# En estas columnas el vacío (NULL) de la fórmula se muestra como en Excel
VACIO_COMO = {
    "MESES X PEDIR PARA PISO":         "E",
    "PEDIDO ESTANDAR DDMRP":           "E",
    "PEDIDO AJUSTADO DDMRP":           "E",
    "PEDIDO AJUSTADO DDMRP JP":        "E",
    "PEDIDO SUGERIDO AJUSTADO A PISO": "#¡VALOR!",
}

# Grupos de columnas, igual que en el Excel final (Datos > Agrupar). Arriba de los encabezados sale
# el botón [+] (grupo cerrado: clic para desplegar) o la línea del grupo con [-] (abierto: clic para cerrar).
# También se exportan así al Excel.
#   abierto: False = cerrado al abrir la ventana (como en el Excel), True = desplegado
#   Las columnas de un grupo deben estar seguidas en COLUMNAS_REPORTE.
GRUPOS_COLUMNAS = [
    # cerrados (ocultos en el Excel)
    {"nombre": "CÓDIGOS Y PROVEEDOR", "abierto": False,
     "columnas": ["CODIGO_ITEM", "CODIGO PROVEEDOR", "COD. PROV1", "PROV1", "COD. PROV2", "PROV2"]},
    {"nombre": "RIN A DISEÑO", "abierto": False,
     "columnas": ["RIN", "SERIE", "ANCHO", "MARCA", "BARRAS", "DISEÑO"]},
    {"nombre": "ACTIVO / COMPRA", "abierto": False, "columnas": ["ACTIVO", "ARTICULO_COMPRA"]},
    # abiertos (agrupados pero visibles en el Excel)
    {"nombre": "ADU SIN PICOS", "abierto": True, "columnas": ["ADU SIN PICOS"]},
    {"nombre": "MESES EN STOCK", "abierto": True,
     "columnas": ["# MESES EN STOCK CON MAX ADU", "MESES STOCK EN SEGÚN ADU"]},
    {"nombre": "DETALLE TRÁNSITOS", "abierto": True,
     "columnas": ["TRANSITO 15D", "TRANSITO 30D", "TRANSITO 45D", "TRANSITO >45D", "# MESES EN TRANSITO"]},
    {"nombre": "DETALLE PEDIDOS", "abierto": True,
     "columnas": ["Pedidos15D", "Pedidos30D", "Pedidos45D", "Pedidos>45D", "# MESES EN PEDIDOS"]},
    {"nombre": "DETALLE BACKORDERS", "abierto": True,
     "columnas": ["Backorders_15D", "Backorders_30D", "Backorders>30D", "# MESES EN BACK ORDERS"]},
    {"nombre": "MESES STOCK TOTAL", "abierto": True,
     "columnas": ["# MESES EN STOCK TOTALSEGUN ADU", "# MES INV TOTAL SEGUN DEMANDA 90D"]},
    {"nombre": "VALIDADOR", "abierto": True, "columnas": ["VALIDADOR"]},
    {"nombre": "LTF / VF", "abierto": True, "columnas": ["LTF", "VF"]},
    {"nombre": "ZONAS", "abierto": True,
     "columnas": ["ZONA ROJA BASE", "ZONA ROJA SEGURIDAD", "ZONA ROJA (TOR)", "ZONA AMARILLA",
                  "LIMITE ZONA AMARILLA (TOY)", "ZONA VERDE"]},
    {"nombre": "PEDIDO ESTANDAR", "abierto": True, "columnas": ["PEDIDO ESTANDAR DDMRP"]},
    {"nombre": "PEDIDO AJUSTADO", "abierto": True, "columnas": ["FLUJO NETO (NFP) AJUSTADO", "PEDIDO AJUSTADO DDMRP"]},
    {"nombre": "NFP AJUSTADO JP", "abierto": True, "columnas": ["FLUJO NETO (NFP) AJUSTADO JP"]},
]

# Columnas ancladas: desde EMPRESA hasta esta columna (inclusive) no se mueven al desplazarse a la
# derecha, en la ventana y en el Excel exportado (Inmovilizar paneles). None = sin anclar.
COLUMNA_ANCLA = "ANT."

# Columnas ocultas sin grupo (en el Excel: clic derecho > Ocultar). Se ven con "Mostrar columnas ocultas".
COLUMNAS_OCULTAS = ["DIF. MAX AÑO vs TOT. AÑO"]

# Color de las filas, igual que en el Excel (hoja EXPLICACIÓN COLORES). Se aplican en orden:
# si una fila cumple varias, queda el color de la ÚLTIMA (el verde va encima de todos).
#   (nombre, color, explicación, condición sobre la tabla d)
COLORES_FILA = [
    ("NARANJA", "#FFC000", "DIAS INV 90D menor a 68 días",
     lambda d: pd.to_numeric(d["DIAS INV 90D"], errors="coerce").fillna(0) < 68),
    ("ROJO",    "#F4A7A7", "DIAS INV 90D menor a 68 y DIAS INV 1 AÑO menor a 275 días",   # rojo suave (Excel: FF0000)
     lambda d: (pd.to_numeric(d["DIAS INV 90D"], errors="coerce").fillna(0) < 68)
             & (pd.to_numeric(d["DIAS INV 1 AÑO"], errors="coerce").fillna(0) < 275)),
    ("VERDE",   "#92D050", "DIF. MAX AÑO vs TOT. AÑO = SI (una factura pesa más del 40 % de las ventas del año)",
     lambda d: d["DIF. MAX AÑO vs TOT. AÑO"] == "SI"),
]

# Indicadores de arriba de la tabla (se recalculan con los filtros):
#   (título, columna, "items" = cuántos ítems tienen valor > 0 | "suma" = suma de la columna)
INDICADORES = [
    ("Ítems con pedido a piso",         "PEDIDO SUGERIDO AJUSTADO A PISO", "items"),
    ("Pedido ajustado DDMRP",           "PEDIDO AJUSTADO DDMRP",           "suma"),
    ("Pedido ajustado DDMRP JP",        "PEDIDO AJUSTADO DDMRP JP",        "suma"),
    ("Pedido sugerido ajustado a piso", "PEDIDO SUGERIDO AJUSTADO A PISO", "suma"),
]

# Filtros de la ventana: (etiqueta, columna). Lista desplegable donde también se puede escribir:
# si lo escrito es un valor de la lista filtra exacto, si no filtra "contiene".
FILTROS_VENTANA = [
    ("Empresa",     "EMPRESA"),
    ("Código ítem", "CODIGO_ITEM"),
    ("Grupo",       "GRUPO"),
    ("Propiedad",   "PROPIEDAD"),
    ("Marca",       "MARCA"),
    ("Diseño",      "DISEÑO"),
    ("Antigüedad",  "ANT."),
    ("Clasificación", "CLASIF. PARETO"),
]

# Botón "Excel de validación": arma el Excel como el original ("Reporte de Pedidos Consolidado (final,
# revisado 12-11-2026)"): estas 24 columnas van como FÓRMULAS DE EXCEL (copiadas del Excel original) y las
# demás como valores. Excel las calcula al abrir y la hoja VALIDACIÓN compara cada una con el valor que
# calculó el programa (hoja VALORES PROGRAMA): "OK" si es igual, "DIF" si no.
# Se escriben con el NOMBRE de la columna entre corchetes: [ADU BASE] = la celda de ADU BASE de esa fila.
FORMULAS_EXCEL_VALIDACION = {
    "MAX ADU":                            '=MAX([ADU BASE],[ADU 90 DÍAS])',
    "MESES STOCK EN SEGÚN ADU":           '=IFERROR(([EN STOCK]/[ADU BASE])/30,0)',
    "# MESES EN STOCK TOTALSEGUN ADU":    '=IFERROR(([STOCK TOTAL]/[ADU BASE])/30,0)',
    "# MESES EN STOCK TOTAL CON MAX ADU": '=IFERROR([STOCK TOTAL]/[MAX ADU]/30,0)',
    "STOCK PROYECTADO DLT CON MAX ADU":   '=+[STOCK TOTAL]-([DLT]*[MAX ADU])',
    "MESES X PEDIR PARA PISO": (
        '=IFERROR(IF([STOCK PROYECTADO DLT CON MAX ADU]<=0,[MESES EN PISO X CATEGORIA],'
        'IF(AND([STOCK PROYECTADO DLT CON MAX ADU]>0,([STOCK PROYECTADO DLT CON MAX ADU]/[MAX ADU]/30)>[MESES EN PISO X CATEGORIA]),[MESES EN PISO X CATEGORIA],'
        'IF(AND([STOCK PROYECTADO DLT CON MAX ADU]>0,([STOCK PROYECTADO DLT CON MAX ADU]/[MAX ADU]/30)<[MESES EN PISO X CATEGORIA]),'
        '[MESES EN PISO X CATEGORIA]-([STOCK PROYECTADO DLT CON MAX ADU]/[MAX ADU]/30),"E"))),0)'),
    "ZONA ROJA BASE":                     '=[DLT]*[ADU BASE]*[LTF]',
    "ZONA ROJA SEGURIDAD":                '=[ZONA ROJA BASE]*[VF]',
    "ZONA ROJA (TOR)":                    '=[ZONA ROJA BASE]+[ZONA ROJA SEGURIDAD]',
    "ZONA AMARILLA":                      '=[DLT]*[ADU BASE]',
    "LIMITE ZONA AMARILLA (TOY)":         '=[ZONA AMARILLA]+[ZONA ROJA (TOR)]',
    "ZONA VERDE":                         '=[ADU 90 DÍAS]*30',
    "TAMAÑO BUFFER (TOG)":                '=[ZONA VERDE]+[LIMITE ZONA AMARILLA (TOY)]',
    "TAMAÑO 3 MESES SEGÚN MAX ADU":       '=[MAX ADU]*90',
    "PEDIDO ESTANDAR DDMRP": (
        '=IF(AND([TAMAÑO BUFFER (TOG)]=0,[FLUJO NETO (NFP)]=0),0,'
        'IF(AND([TAMAÑO BUFFER (TOG)]>=0,[FLUJO NETO (NFP)]>=0,[FLUJO NETO (NFP)]>[TAMAÑO BUFFER (TOG)]),0,'
        'IF(AND([TAMAÑO BUFFER (TOG)]>=0,[FLUJO NETO (NFP)]>=0,[FLUJO NETO (NFP)]<[TAMAÑO BUFFER (TOG)]),'
        'EVEN([TAMAÑO BUFFER (TOG)]-[FLUJO NETO (NFP)]),"E")))'),
    "PEDIDO ESTANDAR DDMRP AJUS TAMAÑO MAX 3 MESES": (
        '=IF(AND([PEDIDO ESTANDAR DDMRP]=0,[TAMAÑO 3 MESES SEGÚN MAX ADU]=0),0,'
        'IF(AND([PEDIDO ESTANDAR DDMRP]>[TAMAÑO 3 MESES SEGÚN MAX ADU]),[TAMAÑO 3 MESES SEGÚN MAX ADU],[PEDIDO ESTANDAR DDMRP]))'),
    "FLUJO NETO (NFP) AJUSTADO": (
        '=IF(([FLUJO NETO (NFP)]-([DLT]*[MAX ADU]))<0,0,[FLUJO NETO (NFP)]-([DLT]*[MAX ADU]))'),
    "PEDIDO AJUSTADO DDMRP": (
        '=IF(AND([TAMAÑO BUFFER (TOG)]=0,[FLUJO NETO (NFP) AJUSTADO]=0),0,'
        'IF(AND([TAMAÑO BUFFER (TOG)]>=0,[FLUJO NETO (NFP) AJUSTADO]>=0,[FLUJO NETO (NFP) AJUSTADO]>[TAMAÑO BUFFER (TOG)]),0,'
        'IF(AND([TAMAÑO BUFFER (TOG)]>=0,[FLUJO NETO (NFP) AJUSTADO]>=0,[FLUJO NETO (NFP) AJUSTADO]<[TAMAÑO BUFFER (TOG)]),'
        'EVEN([TAMAÑO BUFFER (TOG)]-[FLUJO NETO (NFP) AJUSTADO]),"E")))'),
    "PEDIDO AJUSTADO DDMRP AJUS TAMAÑO MAX 3 MESES": (
        '=IF(AND([PEDIDO AJUSTADO DDMRP]=0,[TAMAÑO 3 MESES SEGÚN MAX ADU]=0),0,'
        'IF(AND([PEDIDO AJUSTADO DDMRP]>[TAMAÑO 3 MESES SEGÚN MAX ADU]),[TAMAÑO 3 MESES SEGÚN MAX ADU],[PEDIDO AJUSTADO DDMRP]))'),
    "FLUJO NETO (NFP) AJUSTADO JP": (
        '=IF(([FLUJO NETO (NFP)]-(([MAX ADU]*[DLT])/3))<0,0,[FLUJO NETO (NFP)]-(([MAX ADU]*[DLT])/3))'),
    "PEDIDO AJUSTADO DDMRP JP": (
        '=IF(AND([TAMAÑO BUFFER (TOG)]=0,[FLUJO NETO (NFP) AJUSTADO JP]=0),0,'
        'IF(AND([TAMAÑO BUFFER (TOG)]>=0,[FLUJO NETO (NFP) AJUSTADO JP]>=0,[FLUJO NETO (NFP) AJUSTADO JP]>[TAMAÑO BUFFER (TOG)]),0,'
        'IF(AND([TAMAÑO BUFFER (TOG)]>=0,[FLUJO NETO (NFP) AJUSTADO JP]>=0,[FLUJO NETO (NFP) AJUSTADO JP]<[TAMAÑO BUFFER (TOG)]),'
        'EVEN([TAMAÑO BUFFER (TOG)]-[FLUJO NETO (NFP) AJUSTADO JP]),"E")))'),
    "PEDIDO SUGERIDO AJUSTADO A PISO":    '=EVEN([MESES X PEDIR PARA PISO]*[MAX ADU]*30)',
    "# DE MESES DEL PEDIDO SEGÚN MAX ADU": '=IFERROR([PEDIDO SUGERIDO AJUSTADO A PISO]/[MAX ADU]/30,0)',
}


# =============================================================================
# 4. PROGRAMA (normalmente no se toca)
# =============================================================================
def sql_origen():
    """La consulta de los datos de origen con los filtros del DDMRP y las marcas de IKONIX."""
    import ddmrp_proveedor_item                           # una sola definición de las marcas de IKONIX
    marcas = ", ".join(f"('{m}', '{p}')" for m, p in ddmrp_proveedor_item.MARCA_PROVEEDOR_IKONIX.items())
    return (SQL_ITEMS.replace("{SQL_DLT_PROVEEDOR}", SQL_DLT_PROVEEDOR.strip())
            .replace("{MARCAS_IKONIX}", marcas)
            .replace("{EMPRESA_IKONIX}", ddmrp_proveedor_item.EMPRESA_DLT_POR_MARCA)
            .replace("{FILTROS}", "\n  AND ".join(f["sql"] for f in FILTROS_DDMRP)))


def sql_embudo():
    """Cuántos ítems de core.dim_item quedan después de cada filtro (aplicados uno tras otro)."""
    conteos = ["COUNT(*)"] + [
        "COUNT(*) FILTER (WHERE " + " AND ".join(f["sql"] for f in FILTROS_DDMRP[:i + 1]) + ")"
        for i in range(len(FILTROS_DDMRP))
    ]
    return f"SELECT {', '.join(conteos)} FROM core.dim_item b"


def a_numero(valor):
    """Texto con número ('12.5') -> número; lo demás ('INFINITO') queda igual."""
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, str):
        try:
            return float(valor)
        except ValueError:
            return valor
    return valor


def leer_datos():
    """Arma la consulta con las fórmulas y la ejecuta (solo lectura).
    Devuelve (tabla, conteo por filtro, consulta completa, fórmulas)."""
    pasos = motor.leer_formulas(ARCHIVO_FORMULAS)
    consulta, _ = motor.armar_consulta(sql_origen(), pasos)
    with psycopg2.connect(**POSTGRES) as conn:
        conn.set_session(readonly=True)
        with conn.cursor() as cur:
            # sin JIT: con una consulta tan larga PostgreSQL tarda ~15 s en "compilarla" (solo esta conexión)
            cur.execute("SET jit = off")
            cur.execute(consulta)
            df = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
            cur.execute(sql_embudo())
            embudo = list(cur.fetchone())    # [total dim_item, después del filtro 1, del 2, ...]
    for col in df.columns:                                 # números de PostgreSQL -> número
        if df[col].map(lambda v: isinstance(v, Decimal)).any():
            df[col] = df[col].map(lambda v: float(v) if isinstance(v, Decimal) else v)
    for col in COLUMNAS_TEXTO_CON_NUMEROS:                 # texto que mezcla números y palabras
        if col in df.columns:
            df[col] = df[col].map(a_numero)
    for col, texto in VACIO_COMO.items():
        if col in df.columns:
            df[col] = df[col].astype(object).where(df[col].notna(), texto)
    formulas = [f for p in pasos for f in p["formulas"]]
    return df, embudo, consulta, formulas


def resumen_consola(df, embudo, formulas):
    print("=" * 80)
    print("DDMRP CONSOLIDADO v1 (solo lectura)")
    print("=" * 80)
    print(f"core.dim_item (sin filtro): {embudo[0]:,}")
    for f, n in zip(FILTROS_DDMRP, embudo[1:]):
        print(f"   + {f['sql']:45} -> {n:,}")
    print(f"Ítems repetidos (EMPRESA + CODIGO_ITEM): {df.duplicated(['EMPRESA', 'CODIGO_ITEM']).sum()}")
    print(f"Fórmulas: {len(formulas)} (archivo {ARCHIVO_FORMULAS.name}) | columnas del reporte: {len(COLUMNAS_REPORTE)}")
    for col in ["PEDIDO SUGERIDO AJUSTADO A PISO", "PEDIDO AJUSTADO DDMRP JP"]:
        valores = pd.to_numeric(df[col], errors="coerce")
        print(f"{col}: {(valores > 0).sum():,} ítems con pedido | {valores.sum():,.0f} unidades")
    print("\nÍtems por empresa y grupo:")
    print(df.groupby(["EMPRESA", "GRUPO"]).size().unstack(fill_value=0).to_string())
    print("\nAbriendo la ventana...")


def main():
    try:
        df, embudo, consulta, formulas = leer_datos()
    except motor.ErrorFormulas as error:
        sys.exit(f"\nERROR en {ARCHIVO_FORMULAS.name}: {error}")
    except psycopg2.Error as error:
        sys.exit(f"\nERROR al ejecutar la consulta (revisa {ARCHIVO_FORMULAS.name}):\n{error}")
    faltan = [c for c in COLUMNAS_REPORTE if c not in df.columns]
    if faltan:
        sys.exit(f"Columnas del reporte que no existen (revisa {ARCHIVO_FORMULAS.name} o SQL_ITEMS): {faltan}")
    resumen_consola(df, embudo, formulas)
    ddmrp_v1_ventana.VentanaDDMRP(
        df[COLUMNAS_REPORTE], embudo,
        filtros_ddmrp=FILTROS_DDMRP,
        sql=consulta,
        formulas=formulas,
        grupos_columnas=GRUPOS_COLUMNAS,
        columnas_ocultas=COLUMNAS_OCULTAS,
        filtros_ventana=FILTROS_VENTANA,
        colores_fila=COLORES_FILA,
        indicadores=INDICADORES,
        columna_ancla=COLUMNA_ANCLA,
        recargar=leer_datos,            # botón "Actualizar datos": vuelve a leer datos y fórmulas
        formulas_excel=FORMULAS_EXCEL_VALIDACION,   # botón "Excel de validación"
    ).abrir()


if __name__ == "__main__":
    main()
