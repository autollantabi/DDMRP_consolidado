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
PG_TABLA  = "ddmrp"
TABLA     = f"{PG_SCHEMA}.{PG_TABLA}"

# Parámetros en core.ddmrp_parametros (ddmrp_valor_num) que usa este script
ID_CICLO_PEDIDO = 3    # Ciclo de pedido (días)            -> ZONA VERDE
ID_LTF_BAJO     = 4    # LTF bajo  (0.2): DLT > 100         -> LTF
ID_LTF_MEDIO    = 5    # LTF medio (0.4): 60 < DLT <= 100   -> LTF
ID_LTF_ALTO     = 6    # LTF alto  (0.6): DLT <= 60         -> LTF
ID_VF_BAJO      = 7    # VF bajo   (0.2): CV <= 0.5         -> VF
ID_VF_MEDIO     = 8    # VF medio  (0.4): 0.5 < CV <= 1     -> VF
ID_VF_ALTO      = 9    # VF alto   (0.6): CV > 1            -> VF

DIAS_3_MESES = 90      # TAMAÑO 3 MESES INVENTARIO = ADU * 90

# IKONIX no importa: MAXXIMUNDO le importa y los códigos de ítem son distintos entre
# empresas, así que el DLT de IKONIX se asigna por MARCA -> proveedor
# (el DLT de esos proveedores está en ddmrp_proveedores_dlt con empresa = 'IKONIX').
# EMPRESA_DLT_POR_MARCA y MARCA_PROVEEDOR_IKONIX se importan de ddmrp_proveedor_item.py

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("master")


def parametro(id_parametro):
    """Subconsulta que trae el valor de un parámetro de core.ddmrp_parametros."""
    return f"(SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {id_parametro})"


# =============================================================================
# TABLA BASE: una fila por ítem de dim_item con los datos que vienen de las tablas resumen.
# Las columnas en 0 se llenan después con las fórmulas [n].
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
	ROUND(a."365D"::numeric, 2) AS "UN (#) - AÑO",
	ROUND(a.max_cantidad_anio::numeric, 2) AS "PICO ULT. AÑO X FACTURA",
	a.supera_umbral AS "DIF. MAX AÑO vs TOT. AÑO",
    ROUND(c.ddmrp_stock_inv_1anio::numeric, 2) AS "DIAS INV 1 AÑO",
	                --CASE
	                --	WHEN ROUND(d.sum::numeric, 2) < 4 THEN 0
	                --	ELSE ROUND(c.ddmrp_stock_inv_1anio::numeric, 2)
	                --END AS "DIAS INV 1 AÑO",
	0::numeric AS "DEMANDA MES - AÑO",   -- [3]
	ROUND(a."90D"::numeric, 2) AS "UN (#) - 90D",
    ROUND(c."ddmrp_stock_inv_90D"::numeric, 2) AS "DIAS INV 90D",
	                    --CASE
	                    --	WHEN ROUND(d.sum::numeric, 2) < 4 THEN 0
	                    --	ELSE ROUND(c."ddmrp_stock_inv_90D"::numeric, 2)
	                    --END AS "DIAS INV 90D",
	0::numeric AS "DEMANDA MES 90D",     -- [4]
	0::numeric AS "% VARIACIÓN DEMANDA",       -- [5]
	ROUND(a."MES"::numeric, 2) AS "UNIDADES MES ACTUAL",
	ROUND(d.sum::numeric, 2) AS "EN STOCK",
    ROUND((COALESCE(e."Transito15D", 0) + COALESCE(e."Transito30D", 0)
     + COALESCE(e."Transito45D", 0) + COALESCE(e."Transito>45D", 0))::numeric, 2) AS "TRANSITOS TOTAL",
    ROUND(e."Transito15D"::numeric, 2) AS "TRANSITO 15D",
	ROUND(e."Transito30D"::numeric, 2) AS "TRANSITO 30D",
	ROUND(e."Transito45D"::numeric, 2) AS "TRANSITO 45D",
	ROUND(e."Transito>45D"::numeric, 2) AS "TRANSITO >45D",
	ROUND(e.pedido::numeric, 2) AS "PEDIDOS",
    ROUND(e."Pedidos15D"::numeric, 2) AS "Pedidos15D",
	ROUND(e."Pedidos30D"::numeric, 2) AS "Pedidos30D",
	ROUND(e."Pedidos45D"::numeric, 2) AS "Pedidos45D",
	ROUND(e."Pedidos>45D"::numeric, 2) AS "Pedidos>45D",
	ROUND(e."Backorder"::numeric, 2) AS "BACKORDERS",
    ROUND(e."Backorder15D"::numeric, 2) AS "Backorders_15D",
    ROUND(e."Backorder30D"::numeric, 2) AS "Backorders_30D",
    ROUND(e."Backorder>30D"::numeric, 2) AS "Backorders>30D",
	0::numeric AS "MES INV TOTAL SEGUN DEMANDA 90D",       -- [6]
	0::numeric AS "STOCK TOTAL",         -- [2]
    0::numeric AS "STOCK PROYECTADO DLT",         -- [13]
	0::numeric AS "DLT",                 -- [7] [8] [9]
	0::numeric AS "LTF",                 -- [14] [15]
	0::numeric AS "VF"                   -- [10] [11]
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
"""

# Columnas que no están en SQL_DDMRP: se agregan a la tabla (en este orden) y se llenan con las fórmulas
COLUMNAS_CALCULADAS = [
    ('ADU',                           'numeric DEFAULT 0'),        # [12]
    ('ADU SIN PICOS',                 'numeric DEFAULT 0'),        # [12]
    ('ZONA ROJA BASE',                'numeric DEFAULT 0'),        # [16]
    ('ZONA ROJA SEGURIDAD',           'numeric DEFAULT 0'),        # [17]
    ('ZONA ROJA (TOR)',               'numeric DEFAULT 0'),        # [18]
    ('ZONA AMARILLA',                 'numeric DEFAULT 0'),        # [19]
    ('LIMITE ZONA AMARILLA (TOY)',    'numeric DEFAULT 0'),        # [20]
    ('ZONA VERDE',                    'numeric DEFAULT 0'),        # [21]
    ('TAMAÑO BUFFER (TOG)',           'numeric DEFAULT 0'),        # [22]
    ('FLUJO NETO (NFP)',              'numeric DEFAULT 0'),        # [23]
    ('TAMAÑO PEDIDO',                 'numeric DEFAULT 0'),        # [24]
    ('NUEVO TAMAÑO PEDIDO',           'numeric DEFAULT 0'),        # [25]
    ('TAMAÑO 3 MESES INVENTARIO',     'numeric DEFAULT 0'),        # [26]
    ('ULTIMO FOB',                    'numeric(20,2) DEFAULT 0'),  # [27]
    ('COSTO PROM',                    'numeric(20,2) DEFAULT 0'),  # [27]
    ('ULT. COSTO',                    'numeric(20,2) DEFAULT 0'),  # [27]
    ('P. LISTA',                      'numeric(20,2) DEFAULT 0'),  # [27]
    ('P. LISTA VS ULT.COSTO',         'numeric(20,2)'),            # [28]
]

# Columnas de versiones anteriores que ya no se usan: se borran si existen
COLUMNAS_VIEJAS = ["ADU CON PICOS", "ADU_90", "ADU60D", "COD_PROVEEDOR_IMP", "NOMBRE_PROVEEDOR"]


# =============================================================================
# FÓRMULAS: un bloque por columna, en el orden en que se ejecutan (ver PASOS)
# =============================================================================

# -----------------------------------------------------------------------------
# HOMOLOGACIÓN comercializador -> importador: los ítems del comercializador que cumplen la
# condición y su ítem del importador con el mismo nombre (DESCRIPCION). Las ventas ya se
# pasan en vw_ddmrp_ventas, el ADU en ddmrp_ventas_picos.py y el stock en ddmrp_bodega.py;
# aquí se pasan los días con inventario y el P. LISTA.
#   ROADWING PESADO: comercializador STOX       -> importador AUTOLLANTA
#   CST MOTO:        comercializador MAXXIMUNDO -> importador STOX
# -----------------------------------------------------------------------------
ROADWING_CONDICION = f'"PROPIEDAD" = \'{ROADWING_PROPIEDAD}\''
CST_MOTO_ORIGEN    = "MAXXIMUNDO"
CST_MOTO_DESTINO   = "STOX"
CST_MOTO_CONDICION = '"MARCA" = \'CST\' AND "GRUPO" = \'LLANTAS MOTO\''   # misma regla que la vista


def sql_pasar(columnas, origen=ROADWING_ORIGEN, destino=ROADWING_DESTINO, condicion=ROADWING_CONDICION):
    """UPDATE que copia columnas del ítem del comercializador (origen) al del importador (destino) con el mismo nombre."""
    select = ", ".join(f'MAX("{c}") AS "{c}"' for c in columnas)
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


# -----------------------------------------------------------------------------
# [H1] DIAS INV 1 AÑO y DIAS INV 90D del importador = los del comercializador
#      (el stock estuvo en el comercializador; va antes de [3]-[6], que usan estos días)
#        ROADWING PESADO: AUTOLLANTA toma los días de STOX
#        CST MOTO:        STOX toma los días de MAXXIMUNDO
# -----------------------------------------------------------------------------
SQL_DIAS_INV_DE_STOX = sql_pasar(["DIAS INV 1 AÑO", "DIAS INV 90D"])
SQL_DIAS_INV_CST_MOTO = sql_pasar(["DIAS INV 1 AÑO", "DIAS INV 90D"],
                                  CST_MOTO_ORIGEN, CST_MOTO_DESTINO, CST_MOTO_CONDICION)

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
# [6] MES INV TOTAL SEGUN DEMANDA 90D = STOCK TOTAL / DEMANDA MES 90D
#       demanda sin redondear: UN (#) - 90D / DIAS INV 90D * 30
#       - sin venta en 1 año NI en 90 días, y con stock -> 9999 (cobertura infinita)
#       - en los demás casos sin demanda                -> 0
# -----------------------------------------------------------------------------
SQL_MES_INV_TOTAL = f"""
UPDATE {TABLA}
SET "MES INV TOTAL SEGUN DEMANDA 90D" = CASE
	WHEN COALESCE("UN (#) - AÑO", 0) = 0 AND COALESCE("UN (#) - 90D", 0) = 0 AND "STOCK TOTAL" > 0 THEN 9999
	ELSE ROUND(COALESCE(
		"STOCK TOTAL" * NULLIF("DIAS INV 90D", 0) / NULLIF("UN (#) - 90D" * 30, 0)
	, 0), 2)
END
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
# [12] ADU           = ADU_CON_PICOS de ddmrp_ventas_picos  (lo usan todos los cálculos)
#      ADU SIN PICOS = ADU_SIN_PICOS de ddmrp_ventas_picos  (solo se muestra)
#      En ddmrp_ventas_picos (últimos 365 días):
#        ADU_CON_PICOS = ventas                     / días con inventario
#        ADU_SIN_PICOS = (ventas - ventas pico alto) / días con inventario
#      Para calcular con el ADU sin picos: cambiar "ADU_CON_PICOS" AS adu por "ADU_SIN_PICOS" AS adu
# -----------------------------------------------------------------------------
SQL_ADU = f"""
UPDATE {TABLA} d
SET "ADU" = a.adu,
    "ADU SIN PICOS" = a.adu_sin_picos
FROM (
    SELECT DISTINCT hev_empresa, hev_codigoitem,
           "ADU_CON_PICOS" AS adu,
           "ADU_SIN_PICOS" AS adu_sin_picos
    FROM core.ddmrp_ventas_picos
) a
WHERE d."EMPRESA" = a.hev_empresa AND d."CODIGO_ITEM" = a.hev_codigoitem
"""

# -----------------------------------------------------------------------------
# [13] STOCK PROYECTADO DLT = STOCK TOTAL - DLT * ADU
# -----------------------------------------------------------------------------
SQL_STOCK_PROYECTADO_DLT = f"""
UPDATE {TABLA}
SET "STOCK PROYECTADO DLT" = ROUND(COALESCE("STOCK TOTAL", 0) - ("DLT" * "ADU"), 2)
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
# [16] ZONA ROJA BASE = ADU * DLT * LTF
# -----------------------------------------------------------------------------
SQL_ZONA_ROJA_BASE = f"""
UPDATE {TABLA}
SET "ZONA ROJA BASE" = ROUND("ADU" * "DLT" * "LTF", 2)
"""

# -----------------------------------------------------------------------------
# [17] ZONA ROJA SEGURIDAD = ZONA ROJA BASE * VF
# -----------------------------------------------------------------------------
SQL_ZONA_ROJA_SEGURIDAD = f"""
UPDATE {TABLA}
SET "ZONA ROJA SEGURIDAD" = ROUND("ZONA ROJA BASE" * "VF", 2)
"""

# -----------------------------------------------------------------------------
# [18] ZONA ROJA (TOR) = ZONA ROJA BASE + ZONA ROJA SEGURIDAD
# -----------------------------------------------------------------------------
SQL_ZONA_ROJA = f"""
UPDATE {TABLA}
SET "ZONA ROJA (TOR)" = "ZONA ROJA BASE" + "ZONA ROJA SEGURIDAD"
"""

# -----------------------------------------------------------------------------
# [19] ZONA AMARILLA = ADU * DLT
# -----------------------------------------------------------------------------
SQL_ZONA_AMARILLA = f"""
UPDATE {TABLA}
SET "ZONA AMARILLA" = ROUND("ADU" * "DLT", 2)
"""

# -----------------------------------------------------------------------------
# [20] LIMITE ZONA AMARILLA (TOY) = ZONA ROJA + ZONA AMARILLA
# -----------------------------------------------------------------------------
SQL_LIMITE_ZONA_AMARILLA = f"""
UPDATE {TABLA}
SET "LIMITE ZONA AMARILLA (TOY)" = "ZONA ROJA (TOR)" + "ZONA AMARILLA"
"""

# -----------------------------------------------------------------------------
# [21] ZONA VERDE = MAX( ADU * CICLO DE PEDIDO (param 3) ; ZONA ROJA BASE )
#      (ZONA ROJA BASE = ADU * DLT * LTF. Sin MOQ por ahora)
# -----------------------------------------------------------------------------
SQL_ZONA_VERDE = f"""
UPDATE {TABLA}
SET "ZONA VERDE" = GREATEST(
	ROUND("ADU" * {parametro(ID_CICLO_PEDIDO)}::numeric, 2),
	"ZONA ROJA BASE"
)
"""

# -----------------------------------------------------------------------------
# [22] TAMAÑO BUFFER (TOG) = LIMITE  ZONA AMARILLA + ZONA VERDE
# -----------------------------------------------------------------------------
SQL_TAMANO_BUFFER = f"""
UPDATE {TABLA}
SET "TAMAÑO BUFFER (TOG)" = "LIMITE ZONA AMARILLA (TOY)" + "ZONA VERDE"
"""

# -----------------------------------------------------------------------------
# [23] FLUJO NETO (NFP) = STOCK TOTAL - ADU * DLT
# -----------------------------------------------------------------------------
SQL_FLUJO_NETO = f"""
UPDATE {TABLA}
SET "FLUJO NETO (NFP)" = "STOCK TOTAL" - ("ADU" * "DLT")
"""

# -----------------------------------------------------------------------------
# [24] TAMAÑO PEDIDO = TAMAÑO BUFFER (TOG) - FLUJO NETO   si FLUJO NETO <= TAMAÑO BUFFER (TOG)
#                    = 0                           si FLUJO NETO >  TAMAÑO BUFFER (TOG)
# -----------------------------------------------------------------------------
SQL_TAMANO_PEDIDO = f"""
UPDATE {TABLA}
SET "TAMAÑO PEDIDO" = CASE
	WHEN "FLUJO NETO (NFP)" <= "TAMAÑO BUFFER (TOG)" THEN GREATEST("TAMAÑO BUFFER (TOG)" - "FLUJO NETO (NFP)", 0)
	ELSE 0
END
"""

# -----------------------------------------------------------------------------
# [25] NUEVO TAMAÑO PEDIDO = 0                                   si MES INV TOTAL SEGUN DEMANDA 90D > 4
#                          = TAMAÑO PEDIDO redondeado al par de arriba   en caso contrario
#                            (CEIL(x / 2) * 2: 7 -> 8, 7.3 -> 8, 8 -> 8)
# -----------------------------------------------------------------------------
SQL_NUEVO_TAMANO_PEDIDO = f"""
UPDATE {TABLA}
SET "NUEVO TAMAÑO PEDIDO" = CASE
	WHEN "MES INV TOTAL SEGUN DEMANDA 90D" > 4 THEN 0
	ELSE CEIL("TAMAÑO PEDIDO" / 2) * 2
END
"""

# -----------------------------------------------------------------------------
# [26] TAMAÑO 3 MESES INVENTARIO = ADU * 90
# -----------------------------------------------------------------------------
SQL_TAMANO_3_MESES = f"""
UPDATE {TABLA}
SET "TAMAÑO 3 MESES INVENTARIO" = ROUND("ADU" * {DIAS_3_MESES}, 2)
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
    	ROUND(dit_ultimofob, 2)      AS ultimo_fob,
    	ROUND(dit_costopromedio, 2)  AS costo_promedio,
    	ROUND(dit_ultimocosto, 2)    AS ultimo_costo,
    	ROUND(dit_listaprecios_a, 2) AS lista_precios_a
    FROM core.dim_item
) x
WHERE d."EMPRESA" = x.dit_empresa AND d."CODIGO_ITEM" = x.dit_codigo
"""

# -----------------------------------------------------------------------------
# [H2] P. LISTA de AUTOLLANTA = el de STOX   (COSTO PROM y ULT. COSTO se quedan los de
#      AUTOLLANTA; va antes de [28] para que el margen se calcule con este precio)
# -----------------------------------------------------------------------------
SQL_PLISTA_DE_STOX = sql_pasar(["P. LISTA"])

# -----------------------------------------------------------------------------
# [28] P. LISTA VS ULT.COSTO = (P. LISTA - ULT. COSTO) / P. LISTA * 100
#        - sin último costo se toma 0 (da 100 %)
#        - P. LISTA 0 o vacío: queda vacío (no se puede dividir)
# -----------------------------------------------------------------------------
SQL_PLISTA_VS_ULTCOSTO = f"""
UPDATE {TABLA}
SET "P. LISTA VS ULT.COSTO" = ROUND(
	("P. LISTA" - COALESCE("ULT. COSTO", 0)) * 100 / NULLIF("P. LISTA", 0)
, 2)
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


# =============================================================================
# PASOS: orden en que se ejecutan las fórmulas (cada una usa columnas de pasos anteriores)
# =============================================================================
PASOS = [
    # n    columna que se calcula                 SQL                         parámetros
    ("[H1] DIAS INV de STOX a AUTOLLANTA",       SQL_DIAS_INV_DE_STOX),
    ("[H1] DIAS INV de MAXXIMUNDO a STOX (CST)", SQL_DIAS_INV_CST_MOTO),
    ("[H3] DIAS INV + 1 si EN STOCK > 4",         SQL_DIAS_INV_MAS_1),
    ("[1]  TOP",                                  SQL_TOP),
    ("[2]  STOCK TOTAL",                          SQL_STOCK_TOTAL),
    ("[3]  DEMANDA MES - AÑO",                    SQL_DEMANDA_MES_1ANIO),
    ("[4]  DEMANDA MES 90D",                      SQL_DEMANDA_MES_90D),
    ("[5]  % VARIACIÓN DEMANDA",                  SQL_VAR_DEMANDA),
    ("[6]  MES INV TOTAL SEGUN DEMANDA 90D",      SQL_MES_INV_TOTAL),
    ("[7]  DLT por proveedor",                    SQL_DLT),
    ("[8]  DLT de IKONIX por marca",              SQL_DLT_IKONIX,             PARAMS_DLT_IKONIX),
    ("[9]  DLT por promedio de marca",            SQL_DLT_MARCA),
    ("[10] VF",                                   SQL_VF),
    ("[11] VF por defecto (0.20)",                SQL_VF_DEFAULT),
    ("[12] ADU y ADU SIN PICOS",                  SQL_ADU),
    ("[13] STOCK PROYECTADO DLT",                 SQL_STOCK_PROYECTADO_DLT),
    ("[14] LTF",                                  SQL_LTF),
    ("[15] LTF por defecto (0.20)",               SQL_LTF_DEFAULT),
    ("[16] ZONA ROJA BASE",                       SQL_ZONA_ROJA_BASE),
    ("[17] ZONA ROJA SEGURIDAD",                  SQL_ZONA_ROJA_SEGURIDAD),
    ("[18] ZONA ROJA (TOR)",                            SQL_ZONA_ROJA),
    ("[19] ZONA AMARILLA",                        SQL_ZONA_AMARILLA),
    ("[20] LIMITE ZONA AMARILLA (TOY)",        SQL_LIMITE_ZONA_AMARILLA),
    ("[21] ZONA VERDE",                           SQL_ZONA_VERDE),
    ("[22] TAMAÑO BUFFER (TOG)",                        SQL_TAMANO_BUFFER),
    ("[23] FLUJO NETO (NFP)",                           SQL_FLUJO_NETO),
    ("[24] TAMAÑO PEDIDO",                        SQL_TAMANO_PEDIDO),
    ("[25] NUEVO TAMAÑO PEDIDO",                  SQL_NUEVO_TAMANO_PEDIDO),
    ("[26] TAMAÑO 3 MESES INVENTARIO",            SQL_TAMANO_3_MESES),
    ("[27] Costos y precio",                      SQL_COSTOS),
    ("[H2] P. LISTA de STOX a AUTOLLANTA",       SQL_PLISTA_DE_STOX),
    ("[28] P. LISTA VS ULT.COSTO",                SQL_PLISTA_VS_ULTCOSTO),
    ("[29] Proveedor 1 y 2",                      SQL_PROVEEDORES),
]


# =============================================================================
# CARGA de core.ddmrp (una sola transacción: si algo falla, la tabla queda como estaba)
# =============================================================================
def preparar_tabla(cur):
    """Crea core.ddmrp si no existe y le agrega las columnas que falten. Devuelve las columnas de SQL_DDMRP."""
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
    """Borra los registros de core.ddmrp, inserta la tabla base y ejecuta las fórmulas en orden."""
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
