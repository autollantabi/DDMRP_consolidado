import logging
import sys
import time
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent / "tablas_resumen"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "conection"))
import ddmrp_abc
import ddmrp_bodega
import ddmrp_inventario
import ddmrp_medidas_top
import ddmrp_proveedor_item
#import ddmrp_proveedores
import ddmrp_proveedores_dlt
import ddmrp_ventas_picos
from config import POSTGRES
# tabla marca -> proveedor de IKONIX: una sola definición, en ddmrp_proveedor_item.py
from ddmrp_proveedor_item import EMPRESA_DLT_POR_MARCA, MARCA_PROVEEDOR_IKONIX
# homologación ROADWING PESADO (STOX -> AUTOLLANTA): una sola definición, en ddmrp_ventas_picos.py
from ddmrp_ventas_picos import ROADWING_DESTINO, ROADWING_ORIGEN, ROADWING_PROPIEDAD

# Tablas resumen: corren antes, en este orden
PROCESOS = [
    ("ddmrp_bodega", ddmrp_bodega.ejecutar),
    ("ddmrp_inventario", ddmrp_inventario.ejecutar),
    ("ddmrp_ventas_picos", ddmrp_ventas_picos.ejecutar),
    #("ddmrp_proveedores", ddmrp_proveedores.ejecutar),
    ("ddmrp_proveedores_dlt", ddmrp_proveedores_dlt.ejecutar),
    ("ddmrp_proveedor_item", ddmrp_proveedor_item.ejecutar),     # proveedor 1 y 2 por ítem
    ("ddmrp_medidas_top", ddmrp_medidas_top.ejecutar),
    ("ddmrp_abc", ddmrp_abc.ejecutar),
]

PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_llantas_mes"
TABLA     = f"{PG_SCHEMA}.{PG_TABLA}"

# Parámetros en core.ddmrp_parametros (ddmrp_valor_num) que usa este script
ID_CICLO_PEDIDO = 3    # Ciclo de pedido (días)            -> ZONA VERDE
ID_LTF_BAJO     = 4    # LTF bajo  (0.2): DLT > 100         -> LTF
ID_LTF_MEDIO    = 5    # LTF medio (0.4): 60 < DLT <= 100   -> LTF
ID_LTF_ALTO     = 6    # LTF alto  (0.6): DLT <= 60         -> LTF
ID_VF_BAJO      = 7    # VF bajo   (0.2): CV <= 0.5         -> VF
ID_VF_MEDIO     = 8    # VF medio  (0.4): 0.5 < CV <= 1     -> VF
ID_VF_ALTO      = 9    # VF alto   (0.6): CV > 1            -> VF

# Mensualizado (Excel DDMRP_GRUPOVI_LLANTAS_V16): se pide para tener en piso a lo más
# 3 meses (CLASIF. PARETO A o B) o 2 meses (el resto), más lo que cubre el DLT.
DIAS_MES          = 30   # días de un mes en todas las fórmulas
MESES_PISO_AB     = 3    # MESES EN PISO X CATEGORIA para PARETO A y B
MESES_PISO_OTROS  = 2    # MESES EN PISO X CATEGORIA para el resto (C, D o vacío)

# IKONIX no importa: MAXXIMUNDO le importa y los códigos de ítem son distintos entre
# empresas, así que el DLT de IKONIX se asigna por MARCA -> proveedor
# (el DLT de esos proveedores está en ddmrp_proveedores_dlt con empresa = 'IKONIX').
# EMPRESA_DLT_POR_MARCA y MARCA_PROVEEDOR_IKONIX se importan de ddmrp_proveedor_item.py

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("llantas_mes")


def parametro(id_parametro):
    """Subconsulta que trae el valor de un parámetro de core.ddmrp_parametros."""
    return f"(SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {id_parametro})"


# =============================================================================
# TABLA BASE: una fila por ítem de dim_item con los datos que vienen de las tablas resumen.
# Tiene TODAS las columnas, en el mismo orden que el Excel DDMRP_GRUPOVI_LLANTAS_V16;
# las que van en 0 / NULL se llenan después con las fórmulas [n].
# =============================================================================
SQL_DDMRP = """
SELECT
	b.dit_empresa AS "EMPRESA",
	b.dit_codigo AS "CODIGO_ITEM",
    b.dit_codigoproveedor as "CODIGO PROVEEDOR",
    NULL::varchar AS "COD. PROV1",
    NULL::varchar AS "PROV1",
    NULL::varchar AS "COD. PROV2",
    NULL::varchar AS "PROV2",
	b.dit_nombre AS "DESCRIPCION",
	b.dit_grupo AS "GRUPO",
    b.dit_propiedad AS "PROPIEDAD",
	b.dit_rin as "RIN",
	b.dit_serie as "SERIE",
	b.dit_ancho AS "ANCHO",
	b.dit_nombrefabricante AS "MARCA",
	b.dit_codigobarras AS "BARRAS",
	b.dit_disenio AS "DISEÑO",
    b.dit_antiguedad AS "ANT.",
	'NO'::text AS "TOP",
	f.segmento_final AS "CLASIF. PARETO",
	b.dit_activo AS "ACTIVO",
	b.dit_compra AS "ARTICULO_COMPRA",
    ROUND(COALESCE(a."365D", 0)::numeric, 2) AS "UN (#) - AÑO",
    ROUND(COALESCE(a.max_cantidad_anio, 0)::numeric, 2) AS "PICO ULT. AÑO X FACTURA",
    COALESCE(a.supera_umbral, 'NO') AS "DIF. MAX AÑO vs TOT. AÑO",
    ROUND(COALESCE(c.ddmrp_stock_inv_1anio, 0)::numeric, 2) AS "DIAS INV 1 AÑO",
	0::numeric AS "DEMANDA MES - AÑO",   -- [3]
    0::numeric AS "ADU BASE",                         -- [12]
    ROUND(COALESCE(a."90D", 0)::numeric, 2) AS "UN (#) - 90D",
    ROUND(COALESCE(c."ddmrp_stock_inv_90D", 0)::numeric, 2) AS "DIAS INV 90D",
	0::numeric AS "DEMANDA MES 90D",     -- [4]
    0::numeric AS "ADU 90 DÍAS",                      -- [12]
	0::numeric AS "% VARIACIÓN DEMANDA",       -- [5]
    ROUND(COALESCE(a."MES", 0)::numeric, 2) AS "UNIDADES MES ACTUAL",
	ROUND(d.sum::numeric, 2) AS "EN STOCK",
    0::numeric AS "# MESES EN STOCK",                 -- [M1]
    ROUND((COALESCE(e."Transito15D", 0) + COALESCE(e."Transito30D", 0)
     + COALESCE(e."Transito45D", 0) + COALESCE(e."Transito>45D", 0))::numeric, 2) AS "TRANSITOS TOTAL",
    ROUND(e."Transito15D"::numeric, 2) AS "TRANSITO 15D",
	ROUND(e."Transito30D"::numeric, 2) AS "TRANSITO 30D",
	ROUND(e."Transito45D"::numeric, 2) AS "TRANSITO 45D",
	ROUND(e."Transito>45D"::numeric, 2) AS "TRANSITO >45D",
    0::numeric AS "# MESES EN TRANSITO",              -- [M1]
	ROUND(e.pedido::numeric, 2) AS "PEDIDOS",
    ROUND(e."Pedidos15D"::numeric, 2) AS "Pedidos15D",
	ROUND(e."Pedidos30D"::numeric, 2) AS "Pedidos30D",
	ROUND(e."Pedidos45D"::numeric, 2) AS "Pedidos45D",
	ROUND(e."Pedidos>45D"::numeric, 2) AS "Pedidos>45D",
    0::numeric AS "# MESES EN PEDIDOS",               -- [M1]
	ROUND(e."Backorder"::numeric, 2) AS "BACKORDERS",
    ROUND(e."Backorder15D"::numeric, 2) AS "Backorders_15D",
    ROUND(e."Backorder30D"::numeric, 2) AS "Backorders_30D",
    ROUND(e."Backorder>30D"::numeric, 2) AS "Backorders>30D",
    0::numeric AS "# MESES EN BACK ORDERS",           -- [M1]
    0::numeric AS "STOCK TOTAL",                      -- [2]
    0::numeric AS "MESES EN STOCK TOTAL",             -- [M1]
    0::numeric AS "STOCK PROYECTADO DLT",             -- [13]
    NULL::varchar AS "MES DE STOCK PROYECT MAX ADU DLT",  -- [M3]
    NULL::varchar AS "VALIDADOR",                     -- [M3]
    0::numeric AS "MESES EN PISO X CATEGORIA",        -- [M2]
    0::numeric AS "MESES EN PISO + DLT X CATEGORIA",  -- [M2]
    0::numeric AS "MESES X PEDIR TOTAL",              -- [M4]
    0::numeric AS "DLT",                              -- [7] [8] [9]
    0::numeric AS "LTF",                              -- [14] [15]
    0::numeric AS "VF",                               -- [10] [11]
    0::numeric AS "Ratio de cambio",                  -- [12]
    0::numeric AS "ADU SIN PICOS",                    -- [12]
    0::numeric AS "ZONA ROJA BASE",                   -- [16]
    0::numeric AS "ZONA ROJA SEGURIDAD",              -- [17]
    0::numeric AS "ZONA ROJA (TOR)",                  -- [18]
    0::numeric AS "ZONA AMARILLA",                    -- [19]
    0::numeric AS "LIMITE ZONA AMARILLA (TOY)",       -- [20]
    0::numeric AS "ZONA VERDE",                       -- [21]
    0::numeric AS "TAMAÑO BUFFER (TOG)",              -- [22]
    0::numeric AS "FLUJO NETO (NFP)",                 -- [23]
    0::numeric AS "PEDIDO ESTANDAR DDMRP",            -- [24]
    0::numeric AS "FLUJO NETO (NFP) AJUSTADO",        -- [25]
    0::numeric AS "PEDIDO AJUSTADO DDMRP",            -- [26]
    0::numeric AS "PEDIDO SUGERIDO AJUSTADO A PISO",  -- [M5]
    0::numeric AS "# DE MESES DEL PEDIDO",            -- [M5]
    0::numeric(20,2) AS "ULTIMO FOB",                 -- [27]
    NULL::date AS "ULTIMA COMPRA",                    -- [31]
    0::numeric(20,2) AS "COSTO PROM",                 -- [27]
    0::numeric(20,2) AS "ULT. COSTO",                 -- [27]
    0::numeric(20,2) AS "P. LISTA",                   -- [27]
    NULL::numeric(20,2) AS "P. LISTA VS ULT.COSTO",   -- [28]
    NULL::date AS "ULTIMA VENTA",                     -- [30]
    NULL::varchar AS "OBSERVACIONES"                  -- [32]
FROM core.dim_item b
LEFT JOIN core.vw_ddmrp_ventas a ON a.hev_empresa = b.dit_empresa AND a.hev_codigoitem = b.dit_codigo
LEFT JOIN core.ddmrp_inventario c ON b.dit_empresa = c.ddmpr_empresa AND b.dit_identificador = c.ddmrp_item
LEFT JOIN core.ddmrp_bodegas d ON b.dit_empresa = d.empresa AND b.dit_codigo = d.codigo
LEFT JOIN core.vw_ddmrp_trans_ped e ON b.dit_empresa = e.dit_empresa AND b.dit_codigo = e.dit_codigo
-- ddmrp_abc tiene una fila por empresa + línea + ítem: se agrupa para no duplicar filas
-- si un ítem vende en dos líneas (queda la mejor clase: A < B < C < D)
LEFT JOIN (
	SELECT empresa, codigo_item, MIN(segmento_final) AS segmento_final
	FROM core.ddmrp_abc
	GROUP BY empresa, codigo_item
) f ON b.dit_empresa = f.empresa AND b.dit_codigo = f.codigo_item
WHERE b.dit_activo = 'SI' AND b.dit_compra = 'Y' AND b.dit_grupo IN ('LLANTAS', 'LLANTAS MOTO')
"""

# Columnas que no están en SQL_DDMRP: ninguna. Todas van en SQL_DDMRP para que la tabla
# quede en el mismo orden que el Excel (una columna nueva que se agregue aquí queda al final).
COLUMNAS_CALCULADAS = []

# Columnas de versiones anteriores que ya no se usan: se borran si existen
COLUMNAS_VIEJAS = ["ADU CON PICOS", "ADU_90", "ADU60D", "COD_PROVEEDOR_IMP", "NOMBRE_PROVEEDOR"]


# =============================================================================
# FÓRMULAS: un bloque por columna, en el orden en que se ejecutan (ver PASOS)
# =============================================================================

# =============================================================================
# HOMOLOGACIÓN IMPORTADOR / COMERCIALIZADOR  (aquí se cambia todo lo del master)
# =============================================================================
# Cada línea es un caso. Los ítems de las dos empresas se unen por el mismo nombre (DESCRIPCION).
#   importador / comercializador: empresas de cada rol
#   condicion:  qué ítems entran (columnas de core.ddmrp_llantas_mes; se evalúa en la empresa de la que se copia)
#   planifica:  "importador" o "comercializador": la fila que se planifica y que RECIBE los datos
#   dias:       True = la fila que planifica toma también DIAS INV 1 AÑO y DIAS INV 90D de la otra
#
# Para agregar un caso o cambiar el comercializador, solo se cambia esta lista. Ojo: las ventas,
# el ADU y el stock se pasan en otros scripts (vw_ddmrp_ventas, HOMOLOGACIONES de
# ddmrp_ventas_picos.py y ddmrp_bodega.py); si cambia un caso hay que cambiarlo allá también.
HOMOLOGACIONES = [
    {"nombre": "ROADWING PESADO", "importador": ROADWING_DESTINO, "comercializador": ROADWING_ORIGEN,
     "condicion": f"\"PROPIEDAD\" = '{ROADWING_PROPIEDAD}'",
     "planifica": "importador", "dias": True},
    {"nombre": "CST MOTO", "importador": "STOX", "comercializador": "MAXXIMUNDO",
     "condicion": "\"MARCA\" = 'CST' AND \"GRUPO\" = 'LLANTAS MOTO'",          # misma regla que la vista
     "planifica": "importador", "dias": True},
    {"nombre": "IKONIX", "importador": "MAXXIMUNDO", "comercializador": "IKONIX",  # al revés
     "condicion": '"MARCA" IN (' + ", ".join(f"'{m}'" for m in MARCA_PROVEEDOR_IKONIX) + ")",
     "planifica": "comercializador", "dias": False},
]

# De qué rol sale cada columna de costo y precio (lo usa [H2])
COLUMNAS_DEL_IMPORTADOR      = ["ULTIMO FOB"]
COLUMNAS_DEL_COMERCIALIZADOR = ["COSTO PROM", "ULT. COSTO", "P. LISTA"]
COLUMNAS_DIAS                = ["DIAS INV 1 AÑO", "DIAS INV 90D"]


def sql_pasar(columnas, origen, destino, condicion, solo_si_tiene=False):
    """UPDATE que copia columnas del ítem de la empresa origen al de la empresa destino con el mismo nombre.
    solo_si_tiene=True: si el origen está en 0 o vacío, el destino se queda con su valor."""
    select = ", ".join(f'MAX("{c}") AS "{c}"' for c in columnas)
    if solo_si_tiene:
        sets = ", ".join(f'"{c}" = COALESCE(NULLIF(st."{c}", 0), au."{c}")' for c in columnas)
    else:
        sets = ", ".join(f'"{c}" = st."{c}"' for c in columnas)
    return f"""
UPDATE {TABLA} au
SET {sets}
FROM (
    SELECT UPPER(TRIM("DESCRIPCION")) AS nombre, {select}
    FROM {TABLA}
    WHERE "EMPRESA" = '{origen}' AND {condicion}
    GROUP BY UPPER(TRIM("DESCRIPCION"))
) st
WHERE au."EMPRESA" = '{destino}' AND UPPER(TRIM(au."DESCRIPCION")) = st.nombre
"""


def origen_destino(h):
    """(origen, destino): el destino es la empresa que planifica; el origen, la otra."""
    if h["planifica"] == "importador":
        return h["comercializador"], h["importador"]
    return h["importador"], h["comercializador"]


# -----------------------------------------------------------------------------
# [H1] DIAS INV 1 AÑO y DIAS INV 90D: la empresa que planifica toma los de la otra
#      (el stock estuvo allá; va antes de [3]-[6], que usan estos días). Solo casos con dias=True.
#        ROADWING PESADO: AUTOLLANTA toma los días de STOX
#        CST MOTO:        STOX toma los días de MAXXIMUNDO
# -----------------------------------------------------------------------------
PASOS_H1_DIAS = [
    (f"[H1] DIAS INV de {o} a {d} ({h['nombre']})", sql_pasar(COLUMNAS_DIAS, o, d, h["condicion"]))
    for h in HOMOLOGACIONES if h["dias"]
    for o, d in [origen_destino(h)]
]

# -----------------------------------------------------------------------------
# [H3] Si EN STOCK > 4, cada columna de días que esté en 0 (o vacía) pasa a 1, por separado:
#        DIAS INV 1 AÑO = 0  ->  DIAS INV 1 AÑO + 1
#        DIAS INV 90D   = 0  ->  DIAS INV 90D + 1
#      La que no está en 0 queda igual.
#      Va después de [H1] y antes de [3]-[6], que usan estos días.
# -----------------------------------------------------------------------------
SQL_DIAS_INV_MAS_1 = f"""
UPDATE {TABLA}
SET "DIAS INV 1 AÑO" = CASE WHEN COALESCE("DIAS INV 1 AÑO", 0) = 0
                            THEN COALESCE("DIAS INV 1 AÑO", 0) + 1 ELSE "DIAS INV 1 AÑO" END,
    "DIAS INV 90D"   = CASE WHEN COALESCE("DIAS INV 90D", 0) = 0
                            THEN COALESCE("DIAS INV 90D", 0) + 1   ELSE "DIAS INV 90D" END
WHERE "EN STOCK" > 4
  AND (COALESCE("DIAS INV 1 AÑO", 0) = 0 OR COALESCE("DIAS INV 90D", 0) = 0)
"""

# -----------------------------------------------------------------------------
# [1] TOP = 'SI' si la descripción tiene una medida top (ddmrp_medidas_top), si no 'NO'
# -----------------------------------------------------------------------------
SQL_TOP = f"""
UPDATE {TABLA} d
SET "TOP" = x.top
FROM (
    SELECT dit_empresa, dit_codigo, top
    FROM core.ddmrp_medidas_top
) x
WHERE d."EMPRESA" = x.dit_empresa AND d."CODIGO_ITEM" = x.dit_codigo
"""

# -----------------------------------------------------------------------------
# [2] STOCK TOTAL = EN STOCK + TRANSITOS TOTAL + PEDIDOS + BACKORDERS
#     (vacíos cuentan como 0)
# -----------------------------------------------------------------------------
SQL_STOCK_TOTAL = f"""
UPDATE {TABLA}
SET "STOCK TOTAL" = ROUND(COALESCE("EN STOCK", 0) + COALESCE("TRANSITOS TOTAL", 0) + COALESCE("PEDIDOS", 0) + COALESCE("BACKORDERS", 0), 2)
"""

# -----------------------------------------------------------------------------
# [3] DEMANDA MES - AÑO = UN (#) - AÑO / DIAS INV 1 AÑO * 30      (0 si no hay días con stock)
#     (se multiplica antes de dividir para no perder decimales)
# -----------------------------------------------------------------------------
SQL_DEMANDA_MES_1ANIO = f"""
UPDATE {TABLA}
SET "DEMANDA MES - AÑO" = ROUND(COALESCE("UN (#) - AÑO" * 30 / NULLIF("DIAS INV 1 AÑO", 0), 0), 2)
"""

# -----------------------------------------------------------------------------
# [4] DEMANDA MES 90D = UN (#) - 90D / DIAS INV 90D * 30      (0 si no hay días con stock)
# -----------------------------------------------------------------------------
SQL_DEMANDA_MES_90D = f"""
UPDATE {TABLA}
SET "DEMANDA MES 90D" = ROUND(COALESCE("UN (#) - 90D" * 30 / NULLIF("DIAS INV 90D", 0), 0), 2)
"""

# -----------------------------------------------------------------------------
# [5] % VARIACIÓN DEMANDA = (demanda diaria 90D / demanda diaria 1 año - 1) * 100
#       demanda diaria 90D   = UN (#) - 90D / DIAS INV 90D
#       demanda diaria 1 año = UN (#) - AÑO / DIAS INV 1 AÑO
#     (0 si no se puede calcular)
# -----------------------------------------------------------------------------
SQL_VAR_DEMANDA = f"""
UPDATE {TABLA}
SET "% VARIACIÓN DEMANDA" = ROUND(COALESCE(
	("UN (#) - 90D" * NULLIF("DIAS INV 1 AÑO", 0) / NULLIF("DIAS INV 90D" * "UN (#) - AÑO", 0) - 1) * 100
, 0), 2)
"""

# -----------------------------------------------------------------------------
# DLT por proveedor (lo usan [7] y [8]): core.ddmrp_proveedores_dlt
#   dlt_max = todos los tiempos (incluye el tiempo de backorder)
#   dlt_min = dlt_max sin el tiempo de backorder
# Solo proveedores con DLT > 0: los que están en 0 o vacíos no cuentan y el ítem
# cae al promedio por marca [9].
# -----------------------------------------------------------------------------
SQL_DLT_PROVEEDOR = """
SELECT
	ddmrp_empresa          AS empresa,
	ddmrp_codigo_proveedor AS cod_proveedor,
	ROUND(AVG(ddmrp_dlt_max)::numeric, 2) AS dlt_max,
	ROUND(AVG(ddmrp_dlt_min)::numeric, 2) AS dlt_min
FROM core.ddmrp_proveedores_dlt
WHERE ddmrp_dlt_max > 0
GROUP BY ddmrp_empresa, ddmrp_codigo_proveedor
"""

# DLT que le toca al ítem: con BACKORDERS -> dlt_max | sin BACKORDERS -> dlt_min
DLT_SEGUN_BACKORDER = 'CASE WHEN COALESCE(d."BACKORDERS", 0) > 0 THEN {0}.dlt_max ELSE {0}.dlt_min END'

# -----------------------------------------------------------------------------
# [7] DLT = DLT del proveedor del ítem (max si tiene BACKORDERS, si no min)
#     El proveedor sale de vw_ddmrp_item_proveedor; si tiene varios se promedian.
#     Ítems sin proveedor (o con proveedor sin DLT) quedan en 0.
# -----------------------------------------------------------------------------
SQL_DLT = f"""
UPDATE {TABLA} d
SET "DLT" = {DLT_SEGUN_BACKORDER.format("x")}
FROM (
    SELECT
    	v.empresa,
    	v.codigoitem,
    	ROUND(AVG(p.dlt_max), 2) AS dlt_max,
    	ROUND(AVG(p.dlt_min), 2) AS dlt_min
    FROM core.vw_ddmrp_item_proveedor v
    JOIN ({SQL_DLT_PROVEEDOR}) p ON p.empresa = v.empresa AND p.cod_proveedor = v.heim_codigoproveedor
    GROUP BY v.empresa, v.codigoitem
) x
WHERE d."EMPRESA" = x.empresa AND d."CODIGO_ITEM" = x.codigoitem
"""

# -----------------------------------------------------------------------------
# [8] DLT (IKONIX) = DLT del proveedor que le toca según su MARCA (MARCA_PROVEEDOR_IKONIX)
#     (max si tiene BACKORDERS, si no min). Marcas fuera de la lista quedan como estaban.
#     parámetros: empresa, lista de marcas, lista de proveedores (mismo orden)
# -----------------------------------------------------------------------------
SQL_DLT_IKONIX = f"""
UPDATE {TABLA} d
SET "DLT" = {DLT_SEGUN_BACKORDER.format("p")}
FROM unnest(%(marcas)s::text[], %(proveedores)s::text[]) AS m(marca, cod_proveedor)
JOIN ({SQL_DLT_PROVEEDOR}) p ON p.empresa = %(empresa)s AND p.cod_proveedor = m.cod_proveedor
WHERE d."EMPRESA" = %(empresa)s AND UPPER(TRIM(d."MARCA")) = m.marca
"""

PARAMS_DLT_IKONIX = {
    "empresa":     EMPRESA_DLT_POR_MARCA,
    "marcas":      list(MARCA_PROVEEDOR_IKONIX),
    "proveedores": list(MARCA_PROVEEDOR_IKONIX.values()),
}

# -----------------------------------------------------------------------------
# [9] DLT (si quedó en 0) = promedio del DLT de los ítems de la misma MARCA (de cualquier
#     empresa) que sí tienen DLT. Si la marca no tiene ninguno, queda 0.
# -----------------------------------------------------------------------------
SQL_DLT_MARCA = f"""
UPDATE {TABLA} d
SET "DLT" = m.dlt
FROM (
	SELECT "MARCA", ROUND(AVG("DLT"), 2) AS dlt
	FROM {TABLA}
	WHERE "DLT" > 0
	GROUP BY "MARCA"
) m
WHERE d."DLT" = 0 AND d."MARCA" = m."MARCA"
"""

# -----------------------------------------------------------------------------
# [10] VF = porcentaje según el CV (desviacion_estandar de ddmrp_ventas_picos)
#        CV = 0          -> 0  (luego queda en 0.20 con [11])
#        CV <= 0.5       -> VF bajo  (param 7, 0.2)
#        0.5 < CV <= 1   -> VF medio (param 8, 0.4)
#        CV > 1          -> VF alto  (param 9, 0.6)
# -----------------------------------------------------------------------------
SQL_VF = f"""
UPDATE {TABLA} d
SET "VF" = x.vf
FROM (
    SELECT
    	hev_empresa,
    	hev_codigoitem,
    	CASE
    		WHEN cv = 0   THEN 0
    		WHEN cv <= 0.5 THEN {parametro(ID_VF_BAJO)}
    		WHEN cv <= 1   THEN {parametro(ID_VF_MEDIO)}
    		ELSE                {parametro(ID_VF_ALTO)}
    	END AS vf
    FROM (
    	SELECT DISTINCT hev_empresa, hev_codigoitem, desviacion_estandar AS cv
    	FROM core.ddmrp_ventas_picos
    ) x
) x
WHERE d."EMPRESA" = x.hev_empresa AND d."CODIGO_ITEM" = x.hev_codigoitem
"""

# -----------------------------------------------------------------------------
# [11] VF (si quedó en 0: ítem sin ventas o CV = 0) = 0.20
# -----------------------------------------------------------------------------
SQL_VF_DEFAULT = f"""
UPDATE {TABLA}
SET "VF" = 0.20
WHERE "VF" = 0
"""

# -----------------------------------------------------------------------------
# MENSUALIZADO: fórmulas del Excel DDMRP_GRUPOVI_LLANTAS_V16 (hoja Sheet1)
#   ADU que usan todas las fórmulas = el mayor entre ADU BASE y ADU 90 DÍAS
#   (en el Excel: MAX(BJ, BK))
# -----------------------------------------------------------------------------
ADU_MAX = 'GREATEST("ADU BASE", "ADU 90 DÍAS")'


def meses_de(columna):
    """Meses que cubre la columna con el ADU mayor: columna / ADU / 30 (0 si no hay ADU).
    Excel: =IFERROR((col / MAX(BJ, BK)) / 30, 0)"""
    return f'COALESCE(COALESCE("{columna}", 0) / NULLIF({ADU_MAX}, 0) / {DIAS_MES}, 0)'


def redondea_par(x):
    """Igual que REDONDEA.PAR (EVEN) de Excel: al par siguiente, alejándose de 0 (7.3 -> 8, -7.3 -> -8, 0 -> 0)."""
    return f"(SIGN({x}) * CEIL(ABS({x}) / 2) * 2)"


# -----------------------------------------------------------------------------
# [12] ADU BASE    = UN (#) - AÑO / DIAS INV 1 AÑO       (0 si no hay días)   Excel: =IFERROR(V/Y, 0)
#      ADU 90 DÍAS = DEMANDA MES 90D / 30                                     Excel: =AC/30
# -----------------------------------------------------------------------------
SQL_ADU = f"""
UPDATE {TABLA}
SET "ADU BASE"    = COALESCE("UN (#) - AÑO" / NULLIF("DIAS INV 1 AÑO", 0), 0),
    "ADU 90 DÍAS" = "DEMANDA MES 90D" / {DIAS_MES}
"""

# -----------------------------------------------------------------------------
# [12] Ratio de cambio = ADU 90 DÍAS / ADU BASE - 1     (0 si no hay ADU BASE)   Excel: =IFERROR((BK/BJ)-1, 0)
# -----------------------------------------------------------------------------
SQL_RATIO_CAMBIO = f"""
UPDATE {TABLA}
SET "Ratio de cambio" = COALESCE("ADU 90 DÍAS" / NULLIF("ADU BASE", 0) - 1, 0)
"""

# -----------------------------------------------------------------------------
# [12] ADU SIN PICOS = ADU_SIN_PICOS de ddmrp_ventas_picos (solo se muestra)
#      (últimos 365 días: (ventas - ventas pico alto) / días con inventario)
# -----------------------------------------------------------------------------
SQL_ADU_SIN_PICOS = f"""
UPDATE {TABLA} d
SET "ADU SIN PICOS" = a.adu_sin_picos
FROM (
    SELECT DISTINCT hev_empresa, hev_codigoitem, "ADU_SIN_PICOS" AS adu_sin_picos
    FROM core.ddmrp_ventas_picos
) a
WHERE d."EMPRESA" = a.hev_empresa AND d."CODIGO_ITEM" = a.hev_codigoitem
"""

# -----------------------------------------------------------------------------
# [13] STOCK PROYECTADO DLT = STOCK TOTAL - ADU mayor * DLT     Excel: =AY-(MAX(BJ,BK)*BG)
# -----------------------------------------------------------------------------
SQL_STOCK_PROYECTADO_DLT = f"""
UPDATE {TABLA}
SET "STOCK PROYECTADO DLT" = "STOCK TOTAL" - {ADU_MAX} * "DLT"
"""

# -----------------------------------------------------------------------------
# [14] LTF = factor según el DLT
#        DLT = 0          -> 0  (luego queda en 0.20 con [15])
#        DLT <= 60        -> LTF alto  (param 6, 0.6)
#        60 < DLT <= 100  -> LTF medio (param 5, 0.4)
#        DLT > 100        -> LTF bajo  (param 4, 0.2)
# -----------------------------------------------------------------------------
SQL_LTF = f"""
UPDATE {TABLA}
SET "LTF" = CASE
	WHEN "DLT" = 0   THEN 0
	WHEN "DLT" <= 60  THEN {parametro(ID_LTF_ALTO)}
	WHEN "DLT" <= 100 THEN {parametro(ID_LTF_MEDIO)}
	ELSE                   {parametro(ID_LTF_BAJO)}
END
"""

# -----------------------------------------------------------------------------
# [15] LTF (si quedó en 0: ítem sin DLT) = 0.20
# -----------------------------------------------------------------------------
SQL_LTF_DEFAULT = f"""
UPDATE {TABLA}
SET "LTF" = 0.20
WHERE "LTF" = 0
"""

# -----------------------------------------------------------------------------
# [16] ZONA ROJA BASE = ADU mayor * DLT * LTF                   Excel: =MAX(BJ,BK)*BG*BH
# -----------------------------------------------------------------------------
SQL_ZONA_ROJA_BASE = f"""
UPDATE {TABLA}
SET "ZONA ROJA BASE" = {ADU_MAX} * "DLT" * "LTF"
"""

# -----------------------------------------------------------------------------
# [17] ZONA ROJA SEGURIDAD = ZONA ROJA BASE * VF                Excel: =BN*BI
# -----------------------------------------------------------------------------
SQL_ZONA_ROJA_SEGURIDAD = f"""
UPDATE {TABLA}
SET "ZONA ROJA SEGURIDAD" = "ZONA ROJA BASE" * "VF"
"""

# -----------------------------------------------------------------------------
# [18] ZONA ROJA (TOR) = ZONA ROJA BASE + ZONA ROJA SEGURIDAD   Excel: =BN+BO
# -----------------------------------------------------------------------------
SQL_ZONA_ROJA = f"""
UPDATE {TABLA}
SET "ZONA ROJA (TOR)" = "ZONA ROJA BASE" + "ZONA ROJA SEGURIDAD"
"""

# -----------------------------------------------------------------------------
# [19] ZONA AMARILLA = ADU mayor * DLT                           Excel: =MAX(BJ,BK)*BG
# -----------------------------------------------------------------------------
SQL_ZONA_AMARILLA = f"""
UPDATE {TABLA}
SET "ZONA AMARILLA" = {ADU_MAX} * "DLT"
"""

# -----------------------------------------------------------------------------
# [20] LIMITE ZONA AMARILLA (TOY) = ZONA ROJA (TOR) + ZONA AMARILLA   Excel: =BP+BQ
# -----------------------------------------------------------------------------
SQL_LIMITE_ZONA_AMARILLA = f"""
UPDATE {TABLA}
SET "LIMITE ZONA AMARILLA (TOY)" = "ZONA ROJA (TOR)" + "ZONA AMARILLA"
"""

# -----------------------------------------------------------------------------
# [21] ZONA VERDE = ADU mayor * 30                               Excel: =MAX(BJ,BK)*30
# -----------------------------------------------------------------------------
SQL_ZONA_VERDE = f"""
UPDATE {TABLA}
SET "ZONA VERDE" = {ADU_MAX} * {DIAS_MES}
"""

# -----------------------------------------------------------------------------
# [22] TAMAÑO BUFFER (TOG) = LIMITE ZONA AMARILLA (TOY) + ZONA VERDE   Excel: =BR+BS
# -----------------------------------------------------------------------------
SQL_TAMANO_BUFFER = f"""
UPDATE {TABLA}
SET "TAMAÑO BUFFER (TOG)" = "LIMITE ZONA AMARILLA (TOY)" + "ZONA VERDE"
"""

# -----------------------------------------------------------------------------
# [23] FLUJO NETO (NFP) = STOCK TOTAL                            Excel: =AY
# -----------------------------------------------------------------------------
SQL_FLUJO_NETO = f"""
UPDATE {TABLA}
SET "FLUJO NETO (NFP)" = "STOCK TOTAL"
"""

# -----------------------------------------------------------------------------
# [M1] Meses que cubre cada cantidad con el ADU mayor (0 si no hay ADU):
#        # MESES EN STOCK         = EN STOCK        / ADU mayor / 30   Excel: =IFERROR((AF/MAX(BJ,BK))/30,0)
#        # MESES EN TRANSITO      = TRANSITOS TOTAL / ADU mayor / 30   Excel: =IFERROR((AH/MAX(BJ,BK))/30,0)
#        # MESES EN PEDIDOS       = PEDIDOS         / ADU mayor / 30   Excel: =IFERROR((AN/MAX(BJ,BK))/30,0)
#        # MESES EN BACK ORDERS   = BACKORDERS      / ADU mayor / 30   Excel: =IFERROR((AT/MAX(BJ,BK))/30,0)
#        MESES EN STOCK TOTAL     = STOCK TOTAL     / ADU mayor / 30   Excel: =IFERROR((AY/MAX(BJ,BK)/30),0)
# -----------------------------------------------------------------------------
SQL_MESES = f"""
UPDATE {TABLA}
SET "# MESES EN STOCK"       = {meses_de("EN STOCK")},
    "# MESES EN TRANSITO"    = {meses_de("TRANSITOS TOTAL")},
    "# MESES EN PEDIDOS"     = {meses_de("PEDIDOS")},
    "# MESES EN BACK ORDERS" = {meses_de("BACKORDERS")},
    "MESES EN STOCK TOTAL"   = {meses_de("STOCK TOTAL")}
"""

# -----------------------------------------------------------------------------
# [M2] MESES EN PISO X CATEGORIA       = 3 si CLASIF. PARETO es A o B, si no 2   Excel: =IF(OR(S="A",S="B"),3,2)
#      MESES EN PISO + DLT X CATEGORIA = DLT / 30 + MESES EN PISO X CATEGORIA   Excel: =(BG/30)+BD
# -----------------------------------------------------------------------------
SQL_MESES_PISO = f"""
UPDATE {TABLA}
SET "MESES EN PISO X CATEGORIA" = CASE WHEN "CLASIF. PARETO" IN ('A', 'B') THEN {MESES_PISO_AB}
                                       ELSE {MESES_PISO_OTROS} END
"""
SQL_MESES_PISO_DLT = f"""
UPDATE {TABLA}
SET "MESES EN PISO + DLT X CATEGORIA" = "DLT" / {DIAS_MES} + "MESES EN PISO X CATEGORIA"
"""

# -----------------------------------------------------------------------------
# [M3] VALIDADOR (texto o número):
#        STOCK TOTAL = 0 y ADU mayor = 0  -> 'REVISAR PARA INACTIVAR'
#        STOCK TOTAL = 0 y ADU mayor > 0  -> 'PEDIR MESES X CATEGORIA'
#        STOCK TOTAL > 0 y ADU mayor = 0  -> 'INFINITO REVISAR FALTA DE VENTAS'
#        STOCK TOTAL > 0 y ADU mayor > 0  -> STOCK PROYECTADO DLT / ADU mayor   (días)
#        otro caso (negativos)           -> 'FALSO' (lo que muestra el Excel)
#      MES DE STOCK PROYECT MAX ADU DLT:
#        'REVISAR PARA INACTIVAR'           -> 0
#        'PEDIR MESES X CATEGORIA'          -> MESES EN PISO X CATEGORIA
#        'INFINITO REVISAR FALTA DE VENTAS' -> 'INFINITO'
#        número                             -> VALIDADOR / 30   (meses)
#      Las dos columnas son texto porque mezclan palabras y números; los números se
#      guardan con 2 decimales. Los cálculos que siguen usan el número sin redondear.
# -----------------------------------------------------------------------------
CASO_STOCK_ADU = f"""CASE
        WHEN "STOCK TOTAL" = 0 AND {ADU_MAX} = 0 THEN 'REVISAR PARA INACTIVAR'
        WHEN "STOCK TOTAL" = 0 AND {ADU_MAX} > 0 THEN 'PEDIR MESES X CATEGORIA'
        WHEN "STOCK TOTAL" > 0 AND {ADU_MAX} = 0 THEN 'INFINITO REVISAR FALTA DE VENTAS'
        WHEN "STOCK TOTAL" > 0 AND {ADU_MAX} > 0 THEN 'NUMERO'
        ELSE 'FALSO'
    END"""
# MES DE STOCK PROYECT MAX ADU DLT como número (NULL = INFINITO); Excel: FALSO / 30 = 0
MES_STOCK_NUM = f"""CASE {CASO_STOCK_ADU}
        WHEN 'REVISAR PARA INACTIVAR'  THEN 0
        WHEN 'PEDIR MESES X CATEGORIA' THEN "MESES EN PISO X CATEGORIA"
        WHEN 'NUMERO'                  THEN "STOCK PROYECTADO DLT" / {ADU_MAX} / {DIAS_MES}
        WHEN 'FALSO'                   THEN 0
    END"""
SQL_VALIDADOR = f"""
UPDATE {TABLA}
SET "VALIDADOR" = CASE {CASO_STOCK_ADU}
        WHEN 'NUMERO' THEN ROUND("STOCK PROYECTADO DLT" / {ADU_MAX}, 2)::text
        ELSE {CASO_STOCK_ADU}
    END,
    "MES DE STOCK PROYECT MAX ADU DLT" = CASE {CASO_STOCK_ADU}
        WHEN 'INFINITO REVISAR FALTA DE VENTAS' THEN 'INFINITO'
        ELSE ROUND({MES_STOCK_NUM}, 2)::text
    END
"""

# -----------------------------------------------------------------------------
# [M4] MESES X PEDIR TOTAL = MESES EN PISO + DLT X CATEGORIA - MES DE STOCK PROYECT MAX ADU DLT
#                            (0 si queda negativo o si el mes de stock es INFINITO)
#      Excel: =IF(BE>=BC, BE-BC, IF(BE<BC, 0))   (en Excel un texto es mayor que cualquier número)
# -----------------------------------------------------------------------------
SQL_MESES_X_PEDIR = f"""
UPDATE {TABLA}
SET "MESES X PEDIR TOTAL" = CASE {CASO_STOCK_ADU}
        WHEN 'INFINITO REVISAR FALTA DE VENTAS' THEN 0
        ELSE GREATEST("MESES EN PISO + DLT X CATEGORIA" - ({MES_STOCK_NUM}), 0)
    END
"""

# -----------------------------------------------------------------------------
# [24] PEDIDO ESTANDAR DDMRP = TOG - NFP (0 si queda en 0 o negativo)   Excel: =IF((BT-BU)<=0,0,BT-BU)
# -----------------------------------------------------------------------------
SQL_PEDIDO_ESTANDAR = f"""
UPDATE {TABLA}
SET "PEDIDO ESTANDAR DDMRP" = GREATEST("TAMAÑO BUFFER (TOG)" - "FLUJO NETO (NFP)", 0)
"""

# -----------------------------------------------------------------------------
# [25] FLUJO NETO (NFP) AJUSTADO = STOCK TOTAL - ADU mayor * DLT (0 si queda en 0 o negativo)
#      Excel: =IF((AY-(MAX(BJ,BK)*BG))<=0,0,AY-(MAX(BJ,BK)*BG))
# -----------------------------------------------------------------------------
SQL_FLUJO_NETO_AJUSTADO = f"""
UPDATE {TABLA}
SET "FLUJO NETO (NFP) AJUSTADO" = GREATEST("STOCK TOTAL" - {ADU_MAX} * "DLT", 0)
"""

# -----------------------------------------------------------------------------
# [26] PEDIDO AJUSTADO DDMRP = TOG - NFP AJUSTADO; si queda negativo: TOR + ZONA VERDE / 2
#      Excel: =IF((BT-BW)<0, BP+BS/2, BT-BW)
# -----------------------------------------------------------------------------
SQL_PEDIDO_AJUSTADO = f"""
UPDATE {TABLA}
SET "PEDIDO AJUSTADO DDMRP" = CASE
    WHEN "TAMAÑO BUFFER (TOG)" - "FLUJO NETO (NFP) AJUSTADO" < 0 THEN "ZONA ROJA (TOR)" + "ZONA VERDE" / 2
    ELSE "TAMAÑO BUFFER (TOG)" - "FLUJO NETO (NFP) AJUSTADO"
END
"""

# -----------------------------------------------------------------------------
# [M5] PEDIDO SUGERIDO AJUSTADO A PISO = REDONDEA.PAR( meses * 30 * ADU mayor )
#        meses = MESES X PEDIR TOTAL, pero a lo más MESES EN PISO X CATEGORIA (3 o 2)
#        Excel: =EVEN(IF(AND(BD=3,BF>=3), 3*30*MAX(BJ,BK), IF(AND(BD=3,BF<3), BF*30*MAX(BJ,BK),
#                     IF(AND(BD=2,BF>=2), 2*30*MAX(BJ,BK), IF(AND(BD=2,BF<2), BF*30*MAX(BJ,BK), "ERROR")))))
#      # DE MESES DEL PEDIDO = PEDIDO SUGERIDO AJUSTADO A PISO / ADU mayor / 30   (0 si no hay ADU)
#        Excel: =IFERROR((BY/MAX(BJ,BK))/30,0)
#      Antes de REDONDEA.PAR se redondea a 10 decimales: la división de PostgreSQL deja restos
#      como 240.0000000000000003 (Excel da 240 exacto) y eso subiría el pedido a 242.
# -----------------------------------------------------------------------------
PEDIDO_PISO = f'ROUND(LEAST("MESES X PEDIR TOTAL", "MESES EN PISO X CATEGORIA") * {DIAS_MES} * {ADU_MAX}, 10)'
SQL_PEDIDO_SUGERIDO_PISO = f"""
UPDATE {TABLA}
SET "PEDIDO SUGERIDO AJUSTADO A PISO" = {redondea_par(PEDIDO_PISO)}
"""
SQL_MESES_DEL_PEDIDO = f"""
UPDATE {TABLA}
SET "# DE MESES DEL PEDIDO" = {meses_de("PEDIDO SUGERIDO AJUSTADO A PISO")}
"""

# -----------------------------------------------------------------------------
# [27] ULTIMO FOB = dit_ultimofob | COSTO PROM = dit_costopromedio |
#      ULT. COSTO = dit_ultimocosto | P. LISTA = dit_listaprecios_a     (dim_item, 2 decimales)
# -----------------------------------------------------------------------------
SQL_COSTOS = f"""
UPDATE {TABLA} d
SET "ULTIMO FOB"  = x.ultimo_fob,
    "COSTO PROM"  = x.costo_promedio,
    "ULT. COSTO"  = x.ultimo_costo,
    "P. LISTA"    = x.lista_precios_a
FROM (
    SELECT
    	dit_empresa,
    	dit_codigo,
    	ROUND(COALESCE(dit_ultimofob, 0), 2)      AS ultimo_fob,
    	ROUND(COALESCE(dit_costopromedio, 0), 2)  AS costo_promedio,
    	ROUND(COALESCE(dit_ultimocosto, 0), 2)    AS ultimo_costo,
    	ROUND(COALESCE(dit_listaprecios_a, 0), 2) AS lista_precios_a
    FROM core.dim_item
) x
WHERE d."EMPRESA" = x.dit_empresa AND d."CODIGO_ITEM" = x.dit_codigo
"""

# -----------------------------------------------------------------------------
# [H2] Costos y precio según el rol (COLUMNAS_DEL_IMPORTADOR / COLUMNAS_DEL_COMERCIALIZADOR):
#        ULTIMO FOB                          -> del IMPORTADOR
#        COSTO PROM, ULT. COSTO, P. LISTA    -> del COMERCIALIZADOR
#      La empresa que planifica solo toma de la otra las columnas que le tocan a la otra:
#        ROADWING PESADO: AUTOLLANTA (importador) toma COSTO PROM, ULT. COSTO y P. LISTA de STOX
#        CST MOTO:        STOX (importador) toma COSTO PROM, ULT. COSTO y P. LISTA de MAXXIMUNDO
#        IKONIX (al revés): IKONIX (comercializador) toma el ULTIMO FOB de MAXXIMUNDO
#      Si la otra empresa lo tiene en 0 o vacío, se queda el valor propio.
#      Va antes de [28] para que el margen se calcule con estos valores.
# -----------------------------------------------------------------------------
PASOS_H2_COSTOS = [
    (f"[H2] {', '.join(cols)} de {o} a {d} ({h['nombre']})",
     sql_pasar(cols, o, d, h["condicion"], solo_si_tiene=True))
    for h in HOMOLOGACIONES
    for o, d in [origen_destino(h)]
    for cols in [COLUMNAS_DEL_COMERCIALIZADOR if h["planifica"] == "importador" else COLUMNAS_DEL_IMPORTADOR]
]

# -----------------------------------------------------------------------------
# [28] P. LISTA VS ULT.COSTO = (P. LISTA - ULT. COSTO) / P. LISTA * 100
#        - sin último costo se toma 0 (da 100 %)
#        - P. LISTA 0 o vacío: queda vacío (no se puede dividir)
# -----------------------------------------------------------------------------
SQL_PLISTA_VS_ULTCOSTO = f"""
UPDATE {TABLA}
SET "P. LISTA VS ULT.COSTO" = COALESCE(ROUND(
	("P. LISTA" - COALESCE("ULT. COSTO", 0)) * 100 / NULLIF("P. LISTA", 0)
, 2), 0)
"""

# -----------------------------------------------------------------------------
# [29] COD. PROV1, PROV1, COD. PROV2, PROV2 = core.ddmrp_proveedor_item (solo informativo)
#      (dim_item.dit_proveedorprincipal / dit_proveedorsecundario con nombre de dim_socios;
#       si dim_item no tiene proveedor, los 2 de importación más recientes)
# -----------------------------------------------------------------------------
SQL_PROVEEDORES = f"""
UPDATE {TABLA} d
SET "COD. PROV1" = x.cod_prov1,
    "PROV1"      = x.nom_prov1,
    "COD. PROV2" = x.cod_prov2,
    "PROV2"      = x.nom_prov2
FROM (
    SELECT empresa, codigo_item AS codigoitem, cod_prov1, nom_prov1, cod_prov2, nom_prov2
    FROM core.ddmrp_proveedor_item
) x
WHERE d."EMPRESA" = x.empresa AND d."CODIGO_ITEM" = x.codigoitem
"""

# -----------------------------------------------------------------------------
# [30] ULTIMA VENTA = ultima_venta de vw_ddmrp_ventas
#      (fecha de la última venta con los filtros de la vista: últimos 365 días, sin PPTO,
#       mayoreo / B2B, sin clientes relacionados y con la homologación; vacía si no vendió en el año)
# -----------------------------------------------------------------------------
SQL_ULT_VENTA = f"""
UPDATE {TABLA} d
SET "ULTIMA VENTA" = v.ultima_venta
FROM (
    SELECT hev_empresa, hev_codigoitem, ultima_venta
    FROM core.vw_ddmrp_ventas
) v
WHERE d."EMPRESA" = v.hev_empresa AND d."CODIGO_ITEM" = v.hev_codigoitem
"""

# -----------------------------------------------------------------------------
# [31] ULTIMA COMPRA = dit_ultingreso de dim_item (fecha del último ingreso del ítem)
# -----------------------------------------------------------------------------
SQL_ULT_COMPRA = f"""
UPDATE {TABLA} d
SET "ULTIMA COMPRA" = x.dit_ultingreso
FROM (
    SELECT dit_empresa, dit_codigo, dit_ultingreso
    FROM core.dim_item
) x
WHERE d."EMPRESA" = x.dit_empresa AND d."CODIGO_ITEM" = x.dit_codigo
"""

# -----------------------------------------------------------------------------
# [32] OBSERVACIONES: la misma lógica con la que se generaron los valores del Excel V16
#      (la del ddmrp anterior). Usa el TAMAÑO PEDIDO de antes, que se calcula aquí por
#      dentro con el ADU con picos de ddmrp_ventas_picos (no se guarda como columna):
#        ADU          = ADU_CON_PICOS (0 si el ítem no vendió)
#        TOG          = ZONA ROJA BASE + ZONA ROJA SEGURIDAD + ZONA AMARILLA + ZONA VERDE
#                       ROJA BASE = ROUND(ADU * DLT * LTF, 2), SEGURIDAD = ROUND(ROJA BASE * VF, 2),
#                       AMARILLA = ROUND(ADU * DLT, 2), VERDE = MAX(ROUND(ADU * ciclo (param 3), 2), ROJA BASE)
#        NFP          = STOCK TOTAL - ADU * DLT
#        TAMAÑO PEDIDO = TOG - NFP si NFP <= TOG (mínimo 0), si no 0
#        STOCK PROY.  = ROUND(STOCK TOTAL - DLT * ADU, 2)
#      'INACTIVAR' si TAMAÑO PEDIDO = 0 y STOCK TOTAL = 0
#      'LIQUIDAR'  si TAMAÑO PEDIDO = 0 y STOCK PROY. <> 0
#      '-'         en los demás casos
# -----------------------------------------------------------------------------
SQL_OBSERVACIONES = f"""
UPDATE {TABLA} d
SET "OBSERVACIONES" = CASE
    WHEN x.tamano_pedido = 0 AND d."STOCK TOTAL" = 0      THEN 'INACTIVAR'
    WHEN x.tamano_pedido = 0 AND x.stock_proyectado <> 0  THEN 'LIQUIDAR'
    ELSE '-'
END
FROM (
    SELECT "EMPRESA", "CODIGO_ITEM",
           CASE WHEN nfp <= tog THEN GREATEST(tog - nfp, 0) ELSE 0 END AS tamano_pedido,
           ROUND("STOCK TOTAL" - "DLT" * adu, 2)                     AS stock_proyectado
    FROM (
        SELECT *,
               roja_base + ROUND(roja_base * "VF", 2) + ROUND(adu * "DLT", 2)
                 + GREATEST(ROUND(adu * {parametro(ID_CICLO_PEDIDO)}::numeric, 2), roja_base) AS tog,
               "STOCK TOTAL" - adu * "DLT"                                                 AS nfp
        FROM (
            SELECT t."EMPRESA", t."CODIGO_ITEM", t."STOCK TOTAL", t."DLT", t."VF", COALESCE(v.adu, 0) AS adu,
                   ROUND(COALESCE(v.adu, 0) * t."DLT" * t."LTF", 2) AS roja_base
            FROM {TABLA} t
            LEFT JOIN (
                SELECT DISTINCT hev_empresa, hev_codigoitem, "ADU_CON_PICOS" AS adu
                FROM core.ddmrp_ventas_picos
            ) v ON v.hev_empresa = t."EMPRESA" AND v.hev_codigoitem = t."CODIGO_ITEM"
        ) a
    ) b
) x
WHERE d."EMPRESA" = x."EMPRESA" AND d."CODIGO_ITEM" = x."CODIGO_ITEM"
"""

# -----------------------------------------------------------------------------
# [33] Redondeo a 2 decimales de las columnas calculadas. Va al final: las fórmulas se
#      calculan sin redondear (igual que el Excel) y solo se guarda el resultado con 2 decimales.
# -----------------------------------------------------------------------------
COLUMNAS_2_DECIMALES = [
    "# MESES EN STOCK", "# MESES EN TRANSITO", "# MESES EN PEDIDOS", "# MESES EN BACK ORDERS",
    "MESES EN STOCK TOTAL", "STOCK PROYECTADO DLT", "MESES EN PISO + DLT X CATEGORIA", "MESES X PEDIR TOTAL",
    "DLT", "LTF", "VF", "ADU BASE", "ADU 90 DÍAS", "Ratio de cambio", "ADU SIN PICOS",
    "ZONA ROJA BASE", "ZONA ROJA SEGURIDAD", "ZONA ROJA (TOR)", "ZONA AMARILLA", "LIMITE ZONA AMARILLA (TOY)",
    "ZONA VERDE", "TAMAÑO BUFFER (TOG)", "FLUJO NETO (NFP)", "PEDIDO ESTANDAR DDMRP", "FLUJO NETO (NFP) AJUSTADO",
    "PEDIDO AJUSTADO DDMRP", "PEDIDO SUGERIDO AJUSTADO A PISO", "# DE MESES DEL PEDIDO",
]
SQL_REDONDEO = f"""
UPDATE {TABLA}
SET {", ".join(f'"{c}" = ROUND("{c}", 2)' for c in COLUMNAS_2_DECIMALES)}
"""

# =============================================================================
# PASOS: orden en que se ejecutan las fórmulas (cada una usa columnas de pasos anteriores)
# =============================================================================
PASOS = [
    # n    columna que se calcula                 SQL                         parámetros
    *PASOS_H1_DIAS,                               # uno por caso de HOMOLOGACIONES con dias=True
    ("[H3] DIAS INV + 1 si EN STOCK > 4",         SQL_DIAS_INV_MAS_1),
    ("[1]  TOP",                                  SQL_TOP),
    ("[2]  STOCK TOTAL",                          SQL_STOCK_TOTAL),
    ("[3]  DEMANDA MES - AÑO",                    SQL_DEMANDA_MES_1ANIO),
    ("[4]  DEMANDA MES 90D",                      SQL_DEMANDA_MES_90D),
    ("[5]  % VARIACIÓN DEMANDA",                  SQL_VAR_DEMANDA),
    ("[7]  DLT por proveedor",                    SQL_DLT),
    ("[8]  DLT de IKONIX por marca",              SQL_DLT_IKONIX,             PARAMS_DLT_IKONIX),
    ("[9]  DLT por promedio de marca",            SQL_DLT_MARCA),
    ("[10] VF",                                   SQL_VF),
    ("[11] VF por defecto (0.20)",                SQL_VF_DEFAULT),
    ("[12] ADU BASE y ADU 90 DÍAS",               SQL_ADU),
    ("[12] Ratio de cambio",                      SQL_RATIO_CAMBIO),
    ("[12] ADU SIN PICOS",                        SQL_ADU_SIN_PICOS),
    ("[13] STOCK PROYECTADO DLT",                 SQL_STOCK_PROYECTADO_DLT),
    ("[14] LTF",                                  SQL_LTF),
    ("[15] LTF por defecto (0.20)",               SQL_LTF_DEFAULT),
    ("[16] ZONA ROJA BASE",                       SQL_ZONA_ROJA_BASE),
    ("[17] ZONA ROJA SEGURIDAD",                  SQL_ZONA_ROJA_SEGURIDAD),
    ("[18] ZONA ROJA (TOR)",                      SQL_ZONA_ROJA),
    ("[19] ZONA AMARILLA",                        SQL_ZONA_AMARILLA),
    ("[20] LIMITE ZONA AMARILLA (TOY)",           SQL_LIMITE_ZONA_AMARILLA),
    ("[21] ZONA VERDE",                           SQL_ZONA_VERDE),
    ("[22] TAMAÑO BUFFER (TOG)",                  SQL_TAMANO_BUFFER),
    ("[23] FLUJO NETO (NFP)",                     SQL_FLUJO_NETO),
    ("[M1] # MESES (stock, tránsito, pedidos, backorders, stock total)", SQL_MESES),
    ("[M2] MESES EN PISO X CATEGORIA",            SQL_MESES_PISO),
    ("[M2] MESES EN PISO + DLT X CATEGORIA",      SQL_MESES_PISO_DLT),
    ("[M3] VALIDADOR y MES DE STOCK PROYECT MAX ADU DLT", SQL_VALIDADOR),
    ("[M4] MESES X PEDIR TOTAL",                  SQL_MESES_X_PEDIR),
    ("[24] PEDIDO ESTANDAR DDMRP",                SQL_PEDIDO_ESTANDAR),
    ("[25] FLUJO NETO (NFP) AJUSTADO",            SQL_FLUJO_NETO_AJUSTADO),
    ("[26] PEDIDO AJUSTADO DDMRP",                SQL_PEDIDO_AJUSTADO),
    ("[M5] PEDIDO SUGERIDO AJUSTADO A PISO",      SQL_PEDIDO_SUGERIDO_PISO),
    ("[M5] # DE MESES DEL PEDIDO",                SQL_MESES_DEL_PEDIDO),
    ("[27] Costos y precio",                      SQL_COSTOS),
    *PASOS_H2_COSTOS,                             # uno por caso de HOMOLOGACIONES
    ("[28] P. LISTA VS ULT.COSTO",                SQL_PLISTA_VS_ULTCOSTO),
    ("[29] Proveedor 1 y 2",                      SQL_PROVEEDORES),
    ("[30] ULTIMA VENTA",                         SQL_ULT_VENTA),
    ("[31] ULTIMA COMPRA",                        SQL_ULT_COMPRA),
    ("[32] OBSERVACIONES",                        SQL_OBSERVACIONES),
    ("[33] Redondeo a 2 decimales",               SQL_REDONDEO),               # siempre al final
]


# =============================================================================
# CARGA de core.ddmrp_llantas_mes (una sola transacción: si algo falla, la tabla queda como estaba)
# =============================================================================
def preparar_tabla(cur):
    """Crea core.ddmrp_llantas_mes si no existe y le agrega las columnas que falten. Devuelve las columnas de SQL_DDMRP."""
    cur.execute(f"CREATE TABLE IF NOT EXISTS {TABLA} AS {SQL_DDMRP} WITH NO DATA")
    # columnas y tipos del SELECT (tabla temporal vacía)
    cur.execute(f"CREATE TEMP TABLE tmp_ddmrp AS {SQL_DDMRP} WITH NO DATA")
    cur.execute("""
        SELECT attname, format_type(atttypid, atttypmod)
        FROM pg_attribute
        WHERE attrelid = 'tmp_ddmrp'::regclass AND attnum > 0 AND NOT attisdropped
        ORDER BY attnum
    """)
    columnas_base = cur.fetchall()
    # si la tabla ya existía, agrega las columnas nuevas (no borra la tabla)
    for nombre, tipo in columnas_base + COLUMNAS_CALCULADAS:
        cur.execute(f'ALTER TABLE {TABLA} ADD COLUMN IF NOT EXISTS "{nombre}" {tipo}')
    for nombre in COLUMNAS_VIEJAS:
        cur.execute(f'ALTER TABLE {TABLA} DROP COLUMN IF EXISTS "{nombre}"')
    return [nombre for nombre, _ in columnas_base]


def cargar_ddmrp():
    """Borra los registros de core.ddmrp_llantas_mes, inserta la tabla base y ejecuta las fórmulas en orden."""
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:
            with conn.cursor() as cur:
                columnas_base = preparar_tabla(cur)
                cur.execute(f"TRUNCATE TABLE {TABLA};")
                # nombres entre comillas (tienen mayúsculas, espacios y Ñ)
                nombres = ", ".join('"' + nombre + '"' for nombre in columnas_base)
                cur.execute(f"INSERT INTO {TABLA} ({nombres}) {SQL_DDMRP}")
                filas = cur.rowcount
                for nombre, sql, *params in PASOS:
                    cur.execute(sql, *params)
                    log.info("%-40s %s ítems", nombre, cur.rowcount)
        log.info("Cargadas %s filas en %s", filas, TABLA)
    finally:
        conn.close()


def main():
    fallidos = []
    for nombre, ejecutar in PROCESOS:
        log.info("=== Inicio %s ===", nombre)
        inicio = time.time()
        try:
            ejecutar()
            log.info("=== Fin %s (%.1f s) ===", nombre, time.time() - inicio)
        except Exception:
            log.exception("=== Error en %s ===", nombre)
            fallidos.append(nombre)

    if fallidos:
        log.error("Terminó con errores en: %s", ", ".join(fallidos))
        log.error("No se actualiza %s porque fallaron procesos previos", TABLA)
        sys.exit(1)

    log.info("=== Inicio %s ===", PG_TABLA)
    inicio = time.time()
    try:
        cargar_ddmrp()
        log.info("=== Fin %s (%.1f s) ===", PG_TABLA, time.time() - inicio)
    except Exception:
        log.exception("=== Error en %s ===", PG_TABLA)
        sys.exit(1)

    log.info("Todos los procesos terminaron correctamente")


if __name__ == "__main__":
    main()
