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
import ddmrp_proveedores
import ddmrp_ventas_picos
from config import POSTGRES

PROCESOS = [
    ("ddmrp_bodega", ddmrp_bodega.ejecutar),
    ("ddmrp_inventario", ddmrp_inventario.ejecutar),
    ("ddmrp_ventas_picos", ddmrp_ventas_picos.ejecutar),
    ("ddmrp_proveedores", ddmrp_proveedores.ejecutar),
    ("ddmrp_medidas_top", ddmrp_medidas_top.ejecutar),
    ("ddmrp_abc", ddmrp_abc.ejecutar),
]

PG_SCHEMA = "core"
PG_TABLA  = "ddmrp"

# Parámetros en core.ddmrp_parametros (ddmrp_valor_num) que usa este script
ID_CICLO_PEDIDO = 3    # Ciclo de pedido (días)            -> ZONA VERDE
ID_LTF_BAJO     = 4    # LTF bajo  (0.2): DLT > 100         -> LTF
ID_LTF_MEDIO    = 5    # LTF medio (0.4): 60 < DLT <= 100   -> LTF
ID_LTF_ALTO     = 6    # LTF alto  (0.6): DLT <= 60         -> LTF
ID_VF_BAJO      = 7    # VF bajo   (0.2): CV <= 0.5         -> VF
ID_VF_MEDIO     = 8    # VF medio  (0.4): 0.5 < CV <= 1     -> VF
ID_VF_ALTO      = 9    # VF alto   (0.6): CV > 1            -> VF

# IKONIX no importa: MAXXIMUNDO le importa y los códigos de ítem son distintos entre
# empresas, así que el DLT de IKONIX se asigna por MARCA -> proveedor de MAXXIMUNDO
# (ddmrp_proveedores.py ya deja esas filas con empresa = 'IKONIX')
EMPRESA_DLT_POR_MARCA = "IKONIX"
MARCA_PROVEEDOR_IKONIX = {
    "UYUSTOOLS": "P2222222222002",   # HANGZHOU HANTOO ENTERPRISES CO., LTD
    "DONGCHENG": "P9999999999994",   # JIANGSU DONGCHENG IMPORT AND EXPORT TRADE CO.,LTD.
    "SATA":      "P9999999999993",   # SHANGHAI DATECH IMP.&EXP. ENTERPRISES CO., LTD.
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("master")


# ---------------------------------------------------------------------------
# TABLA FINAL core.ddmrp: se arma con las tablas resumen, al final de todo
# ---------------------------------------------------------------------------
SQL_DDMRP = """
SELECT
	b.dit_empresa AS "EMPRESA",
	b.dit_codigo AS "CODIGO_ITEM",
    b.dit_codigoproveedor as "CODIGO_PROVEEDOR",
	b.dit_nombre AS "DESCRIPCION",
	b.dit_grupo AS "GRUPO",
    b.dit_propiedad AS "PROPIEDAD",
	b.dit_rin as "RIN",
	b.dit_serie as "SERIE",
	b.dit_ancho AS "ANCHO",
	b.dit_nombrefabricante AS "MARCA",
	b.dit_codigobarras AS "BARRAS",
	b.dit_disenio AS "DISEÑO",
    b.dit_antiguedad AS "ANTIGUEDAD",
	'NO'::text AS "TOP",                 -- se llena con SQL_TOP
	f.segmento_final AS "CLUSTER",       -- clasificación ABC (ddmrp_abc): A, B, C o D; vacío si no entra
	b.dit_activo AS "ACTIVO",
	b.dit_compra AS "ARTICULO_COMPRA",
	ROUND(a."365D"::numeric, 2) AS "VTAS_1_AÑO",
	ROUND(a.max_cantidad_anio::numeric, 2) AS "VENTAS MES PICO",
	a.supera_umbral AS "DIF PICO VTAS ULT AÑO VS # VTAS ULT AÑO",
	ROUND(c.ddmrp_stock_inv_1anio::numeric, 2) AS "DIAS INV 1 AÑO",
	0::numeric AS "DEMANDA MES 1 AÑO",   -- se llena con SQL_DEMANDA_MES_1ANIO
	ROUND(a."90D"::numeric, 2) AS "VENTA 90D",
	ROUND(c."ddmrp_stock_inv_90D"::numeric, 2) AS "DIAS INV 90D",
	0::numeric AS "DEMANDA MES 90D",     -- se llena con SQL_DEMANDA_MES_90D
	0::numeric AS "% VAR DEMANDA",       -- se llena con SQL_VAR_DEMANDA
	ROUND(a."MES"::numeric, 2) AS "VENTAS MES ACTUAL",
	--ROUND(d.sum::numeric, 2) AS "EN STOCK",
    CASE
        WHEN ROUND(d.sum::numeric, 2) < 4   THEN 0
        ELSE ROUND(d.sum::numeric, 2)
    END AS "EN STOCK",
    ROUND(e."Transito15D"::numeric, 2) AS "TRANSITO 15D",
	ROUND(e."Transito30D"::numeric, 2) AS "TRANSITO 30D",
	ROUND(e."Transito60D"::numeric, 2) AS "TRANSITO 60D",
	ROUND(e.pedido::numeric, 2) AS "PEDIDOS",
    ROUND(e."Pedidos15D"::numeric, 2) AS "Pedidos15D",
	ROUND(e."Pedidos30D"::numeric, 2) AS "Pedidos30D",
	ROUND(e."Pedidos60D"::numeric, 2) AS "Pedidos60D",
	ROUND(e."Pedidos90D"::numeric, 2) AS "Pedidos90D",
	ROUND(e."Pedidos>90D"::numeric, 2) AS "Pedidos>90D",
	ROUND(e."Backorder"::numeric, 2) AS "BACKORDERS",
    ROUND(e."Backorder15D"::numeric, 2) AS "Backorders_15D",
    ROUND(e."Backorder30D"::numeric, 2) AS "Backorders_30D",
    ROUND(e."Backorder>30D"::numeric, 2) AS "Backorders>30D",
	0::numeric AS "MES INV TOTAL",       -- se llena con SQL_MES_INV_TOTAL
	0::numeric AS "STOCK TOTAL",         -- se llena con SQL_STOCK_TOTAL
    0::numeric AS "STOCK PROYECTADO DLT",         -- se llena con SQL_STOCK_TOTAL
	0::numeric AS "DLT",                 -- se llena con SQL_DLT
	0::numeric AS "LTF",                 -- se llena con SQL_LTF
	0::numeric AS "VF"                   -- se llena con SQL_VF
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


# ---------------------------------------------------------------------------
# TOP por ítem: 'SI' si la descripción tiene una medida top (ddmrp_medidas_top), si no 'NO'
# ---------------------------------------------------------------------------
SQL_TOP = """
SELECT dit_empresa, dit_codigo, top
FROM core.ddmrp_medidas_top
"""

# ---------------------------------------------------------------------------
# STOCK TOTAL = EN STOCK + TRANSITO 15D + TRANSITO 30D + TRANSITO 60D + PEDIDOS + BACKORDERS
# ---------------------------------------------------------------------------
SQL_STOCK_TOTAL = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "STOCK TOTAL" = ROUND(COALESCE("EN STOCK", 0) + COALESCE("TRANSITO 15D", 0) + COALESCE("TRANSITO 30D", 0) + COALESCE("TRANSITO 60D", 0)
                          + COALESCE("PEDIDOS", 0) + COALESCE("BACKORDERS", 0), 2)
"""

# ---------------------------------------------------------------------------
# STOCK PROYECTADO DLT = ("STOCK TOTAL" - (DLT * ADU))
# ---------------------------------------------------------------------------
SQL_STOCK_PROYECTADO_DLT = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "STOCK PROYECTADO DLT" = ROUND(COALESCE("STOCK TOTAL", 0) - ("DLT" * "ADU"), 2)
"""

# ---------------------------------------------------------------------------
# DEMANDA MES 1 AÑO = VTAS_1_AÑO / DIAS INV 1 AÑO * 30   (0 si no hay días con stock)
# DEMANDA MES 90D   = VENTA 90D  / DIAS INV 90D  * 30   (0 si no hay días con stock)
#   (se multiplica antes de dividir para no perder decimales)
# ---------------------------------------------------------------------------
SQL_DEMANDA_MES_1ANIO = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "DEMANDA MES 1 AÑO" = ROUND(COALESCE("VTAS_1_AÑO" * 30 / NULLIF("DIAS INV 1 AÑO", 0), 0), 2)
"""

SQL_DEMANDA_MES_90D = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "DEMANDA MES 90D" = ROUND(COALESCE("VENTA 90D" * 30 / NULLIF("DIAS INV 90D", 0), 0), 2)
"""

# ---------------------------------------------------------------------------
# % VAR DEMANDA = (demanda diaria 90D / demanda diaria 1 año - 1) * 100   (0 si no se puede calcular)
#   demanda diaria 90D   = VENTA 90D  / DIAS INV 90D
#   demanda diaria 1 año = VTAS_1_AÑO / DIAS INV 1 AÑO
# ---------------------------------------------------------------------------
SQL_VAR_DEMANDA = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "% VAR DEMANDA" = ROUND(COALESCE(
	("VENTA 90D" * NULLIF("DIAS INV 1 AÑO", 0) / NULLIF("DIAS INV 90D" * "VTAS_1_AÑO", 0) - 1) * 100
, 0), 2)
"""

# ---------------------------------------------------------------------------
# MES INV TOTAL = STOCK TOTAL / DEMANDA MES 90D
#   (usa la demanda 90D sin redondear: VENTA 90D / DIAS INV 90D * 30)
#   - sin venta en 1 año NI en 90 días, y con stock -> 9999 (cobertura infinita: no hay con qué comparar)
#   - en los demás casos sin demanda                -> 0
# ---------------------------------------------------------------------------
SQL_MES_INV_TOTAL = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "MES INV TOTAL" = CASE
	WHEN COALESCE("VTAS_1_AÑO", 0) = 0 AND COALESCE("VENTA 90D", 0) = 0 AND "STOCK TOTAL" > 0 THEN 9999
	ELSE ROUND(COALESCE(
		"STOCK TOTAL" * NULLIF("DIAS INV 90D", 0) / NULLIF("VENTA 90D" * 30, 0)
	, 0), 2)
END
"""

# ---------------------------------------------------------------------------
# DLT por ítem: promedio por proveedor (ddmrp_proveedores) llevado al ítem con
# vw_ddmrp_item_proveedor; si el ítem tiene varios proveedores se promedian.
# Ítems sin proveedor quedan en 0.
# ---------------------------------------------------------------------------
SQL_DLT = """
SELECT
	v.empresa,
	v.codigoitem,
	ROUND(AVG(p.dlt), 2) AS dlt
FROM core.vw_ddmrp_item_proveedor v
JOIN (
	SELECT
		empresa,
		cod_proveedor,
		ROUND(AVG(dlt), 2) AS dlt
	FROM core.ddmrp_proveedores
	GROUP BY empresa, cod_proveedor
) p ON p.empresa = v.empresa AND p.cod_proveedor = v.heim_codigoproveedor
GROUP BY v.empresa, v.codigoitem
"""

# ---------------------------------------------------------------------------
# DLT de IKONIX por marca: la MARCA del ítem da el proveedor (MARCA_PROVEEDOR_IKONIX)
# y se pone el DLT promedio de ese proveedor en ddmrp_proveedores (empresa IKONIX).
# Marcas que no están en la lista o proveedores sin filas quedan como estaban.
#   parámetros: empresa, lista de marcas, lista de proveedores (mismo orden)
# ---------------------------------------------------------------------------
SQL_DLT_IKONIX = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA} d
SET "DLT" = p.dlt
FROM unnest(%(marcas)s::text[], %(proveedores)s::text[]) AS m(marca, cod_proveedor)
JOIN (
	SELECT cod_proveedor, ROUND(AVG(dlt), 2) AS dlt
	FROM core.ddmrp_proveedores
	WHERE empresa = %(empresa)s
	GROUP BY cod_proveedor
) p ON p.cod_proveedor = m.cod_proveedor
WHERE d."EMPRESA" = %(empresa)s AND UPPER(TRIM(d."MARCA")) = m.marca
"""

# ---------------------------------------------------------------------------
# DLT faltante (ítems sin proveedor, DLT = 0): promedio del DLT de los ítems de la
# misma MARCA (de cualquier empresa) que sí tienen DLT. Si la marca no tiene ninguno, queda 0.
# ---------------------------------------------------------------------------
SQL_DLT_MARCA = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA} d
SET "DLT" = m.dlt
FROM (
	SELECT "MARCA", ROUND(AVG("DLT"), 2) AS dlt
	FROM {PG_SCHEMA}.{PG_TABLA}
	WHERE "DLT" > 0
	GROUP BY "MARCA"
) m
WHERE d."DLT" = 0 AND d."MARCA" = m."MARCA"
"""

# ---------------------------------------------------------------------------
# VF por ítem: porcentaje según el tramo del CV (igual que el LTF con el DLT).
#   El CV es la columna desviacion_estandar de ddmrp_ventas_picos (un solo CV por empresa + ítem).
#   CV = 0            -> 0 (luego queda en 0.20 con SQL_VF_DEFAULT)
#   CV <= 0.5         -> VF bajo  (param 7, 0.2)
#   0.5 < CV <= 1     -> VF medio (param 8, 0.4)
#   CV > 1            -> VF alto  (param 9, 0.6)
#   En ddmrp_ventas_picos el VF se guarda calculado (CV * porcentaje); aquí solo el porcentaje.
# ---------------------------------------------------------------------------
SQL_VF = f"""
SELECT
	hev_empresa,
	hev_codigoitem,
	CASE
		WHEN cv = 0   THEN 0
		WHEN cv <= 0.5 THEN (SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {ID_VF_BAJO})
		WHEN cv <= 1   THEN (SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {ID_VF_MEDIO})
		ELSE                (SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {ID_VF_ALTO})
	END AS vf
FROM (
	SELECT DISTINCT hev_empresa, hev_codigoitem, desviacion_estandar AS cv
	FROM core.ddmrp_ventas_picos
) x
"""

# ---------------------------------------------------------------------------
# VF por defecto: si el VF quedó en 0 (ítem sin ventas o CV = 0) se pone 0.20
# ---------------------------------------------------------------------------
SQL_VF_DEFAULT = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "VF" = 0.20
WHERE "VF" = 0
"""

# ---------------------------------------------------------------------------
# ADU (u/día) por ítem: ya viene calculado en ddmrp_ventas_picos
#   (últimos 365 días, param 1, sin los tramos con pico alto ni sus días)
# ---------------------------------------------------------------------------
SQL_ADU = """
SELECT DISTINCT hev_empresa, hev_codigoitem, "ADU" AS adu
FROM core.ddmrp_ventas_picos
"""

# ---------------------------------------------------------------------------
# LTF por ítem: factor según el tramo del DLT del ítem (parámetros 4, 5 y 6)
#   DLT = 0          -> 0 (sin lead time)
#   DLT <= 60        -> LTF alto  (param 6, 0.6)
#   60 < DLT <= 100  -> LTF medio (param 5, 0.4)
#   DLT > 100        -> LTF bajo  (param 4, 0.2)
# ---------------------------------------------------------------------------
SQL_LTF = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "LTF" = CASE
	WHEN "DLT" = 0   THEN 0
	WHEN "DLT" <= 60  THEN (SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {ID_LTF_ALTO})
	WHEN "DLT" <= 100 THEN (SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {ID_LTF_MEDIO})
	ELSE                   (SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {ID_LTF_BAJO})
END
"""

# ---------------------------------------------------------------------------
# LTF por defecto: si el LTF quedó en 0 (ítem sin DLT) se pone 0.20
# ---------------------------------------------------------------------------
SQL_LTF_DEFAULT = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "LTF" = 0.20
WHERE "LTF" = 0
"""

# ---------------------------------------------------------------------------
# ZONA ROJA por ítem:
#   ZONA ROJA BASE      = ADU * DLT * LTF
#   ZONA ROJA SEGURIDAD = ZONA ROJA BASE * VF
# ---------------------------------------------------------------------------
SQL_ZONA_ROJA_BASE = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "ZONA ROJA BASE" = ROUND("ADU" * "DLT" * "LTF", 2)
"""

SQL_ZONA_ROJA_SEGURIDAD = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "ZONA ROJA SEGURIDAD" = ROUND("ZONA ROJA BASE" * "VF", 2)
"""

# ---------------------------------------------------------------------------
# TOR (Top of Red = zona roja total): TOR = ZONA ROJA BASE + ZONA ROJA SEGURIDAD
# ---------------------------------------------------------------------------
SQL_TOR = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "TOR" = "ZONA ROJA BASE" + "ZONA ROJA SEGURIDAD"
"""

# ---------------------------------------------------------------------------
# ZONA AMARILLA = ADU * DLT
# TOY (Top of Yellow) = TOR + ZONA AMARILLA
# ---------------------------------------------------------------------------
SQL_ZONA_AMARILLA = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "ZONA AMARILLA" = ROUND("ADU" * "DLT", 2)
"""

SQL_TOY = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "TOY" = "TOR" + "ZONA AMARILLA"
"""

# ---------------------------------------------------------------------------
# ZONA VERDE = MAX( ADU * Ciclo de Pedido (param 3) ; ADU * DLT * LTF )
#   ADU * DLT * LTF es la ZONA ROJA BASE. Sin MOQ por ahora.
# ---------------------------------------------------------------------------
SQL_ZONA_VERDE = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "ZONA VERDE" = GREATEST(
	ROUND("ADU" * (SELECT ddmrp_valor_num FROM core.ddmrp_parametros WHERE ddmrp_id = {ID_CICLO_PEDIDO})::numeric, 2),
	"ZONA ROJA BASE"
)
"""

# ---------------------------------------------------------------------------
# TOG (Top of Green) = TOY + ZONA VERDE
# ---------------------------------------------------------------------------
SQL_TOG = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "TOG" = "TOY" + "ZONA VERDE"
"""

# ---------------------------------------------------------------------------
# NFP (Net Flow Position) = Inventario disponible + Suministro abierto - Demanda calificada
#   STOCK TOTAL ya es EN STOCK + tránsitos + pedidos + backorders (inventario + suministro abierto).
#   Demanda calificada = 0 por ahora (pedidos abiertos de clientes: pendiente traerlos de SAP).
#   Para cambiarla, reemplazar el "- 0" por la columna o consulta que corresponda.
# ---------------------------------------------------------------------------
SQL_NFP = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "NFP" = "STOCK TOTAL" - 0
"""

# ---------------------------------------------------------------------------
# PEDIDO SUGERIDO: solo se pide si NFP <= TOY (regla de disparo)
#   PEDIDO SUGERIDO = TOG - NFP   si NFP <= TOG
#   PEDIDO SUGERIDO = 0           si NFP >  TOG
# ---------------------------------------------------------------------------
SQL_PEDIDO_SUGERIDO = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "PEDIDO SUGERIDO" = CASE
	WHEN "NFP" <= "TOG" THEN GREATEST("TOG" - "NFP", 0)
	ELSE 0
END
"""

# ---------------------------------------------------------------------------
# NUEVO TAMAÑO PEDIDO:
#   0                 si MES INV TOTAL > 4
#   PEDIDO SUGERIDO   en caso contrario
# ---------------------------------------------------------------------------
SQL_NUEVO_TAMANO_PEDIDO = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "NUEVO TAMAÑO PEDIDO" = CASE
	WHEN "MES INV TOTAL" > 4 THEN 0
	ELSE "PEDIDO SUGERIDO"
END
"""

# ---------------------------------------------------------------------------
# COSTOS Y PRECIO del ítem (dim_item), redondeados a 2 decimales
# ---------------------------------------------------------------------------
SQL_COSTOS = """
SELECT
	dit_empresa,
	dit_codigo,
	ROUND(dit_ultimofob, 2)      AS ultimo_fob,
	ROUND(dit_costopromedio, 2)  AS costo_promedio,
	ROUND(dit_ultimocosto, 2)    AS ultimo_costo,
	ROUND(dit_listaprecios_a, 2) AS lista_precios_a
FROM core.dim_item
"""

# ---------------------------------------------------------------------------
# P. LISTA VS ULT. COSTO (margen sobre el precio de lista, en %):
#   (LISTA PRECIOS A - ULTIMO COSTO) / LISTA PRECIOS A * 100
#   - sin último costo se toma 0 (da 100 %)
#   - precio de lista 0 o vacío: queda vacío (no se puede dividir)
# ---------------------------------------------------------------------------
SQL_PLISTA_VS_ULTCOSTO = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET "P. LISTA VS ULT. COSTO" = ROUND(
	("LISTA PRECIOS A" - COALESCE("ULTIMO COSTO", 0)) * 100 / NULLIF("LISTA PRECIOS A", 0)
, 2)
"""

def cargar_ddmrp():
    """Crea core.ddmrp si no existe (con las columnas del SELECT), borra sus registros e inserta."""
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:                      # una sola transacción: si falla, no deja la tabla vacía
            with conn.cursor() as cur:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} AS {SQL_DDMRP} WITH NO DATA")
                # columnas y tipos del SELECT (tabla temporal vacía)
                cur.execute(f"CREATE TEMP TABLE tmp_ddmrp AS {SQL_DDMRP} WITH NO DATA")
                cur.execute("""
                    SELECT attname, format_type(atttypid, atttypmod)
                    FROM pg_attribute
                    WHERE attrelid = 'tmp_ddmrp'::regclass AND attnum > 0 AND NOT attisdropped
                    ORDER BY attnum
                """)
                columnas = cur.fetchall()
                # si la tabla ya existía, agrega las columnas nuevas del SELECT (no borra la tabla)
                for nombre, tipo in columnas:
                    cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} '
                                f'ADD COLUMN IF NOT EXISTS "{nombre}" {tipo}')
                # nombres entre comillas (tienen mayúsculas, espacios y Ñ)
                nombres = ", ".join('"' + nombre + '"' for nombre, _ in columnas)
                # ADU se llena aparte (SQL_ADU); ítems sin venta quedan en 0
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "ADU" numeric DEFAULT 0')
                # ADU_90 ya no se usa (las zonas van con el ADU): se borra la columna si existe
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} DROP COLUMN IF EXISTS "ADU_90"')
                # zona roja y TOR se llenan aparte (SQL_ZONA_ROJA_BASE, SQL_ZONA_ROJA_SEGURIDAD, SQL_TOR)
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "ZONA ROJA BASE" numeric DEFAULT 0')
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "ZONA ROJA SEGURIDAD" numeric DEFAULT 0')
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "TOR" numeric DEFAULT 0')
                # zona amarilla y TOY se llenan aparte (SQL_ZONA_AMARILLA, SQL_TOY)
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "ZONA AMARILLA" numeric DEFAULT 0')
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "TOY" numeric DEFAULT 0')
                # zona verde se llena aparte (SQL_ZONA_VERDE)
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "ZONA VERDE" numeric DEFAULT 0')
                # TOG se llena aparte (SQL_TOG)
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "TOG" numeric DEFAULT 0')
                # NFP y pedido sugerido se llenan aparte (SQL_NFP, SQL_PEDIDO_SUGERIDO)
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "NFP" numeric DEFAULT 0')
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "PEDIDO SUGERIDO" numeric DEFAULT 0')
                # nuevo tamaño de pedido se llena aparte (SQL_NUEVO_TAMANO_PEDIDO)
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "NUEVO TAMAÑO PEDIDO" numeric DEFAULT 0')
                # costos y precio se llenan aparte (SQL_COSTOS), con 2 decimales
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "ULTIMO FOB" numeric(20,2) DEFAULT 0')
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "COSTO PROMEDIO" numeric(20,2) DEFAULT 0')
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "ULTIMO COSTO" numeric(20,2) DEFAULT 0')
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "LISTA PRECIOS A" numeric(20,2) DEFAULT 0')
                # margen lista vs último costo se llena aparte (SQL_PLISTA_VS_ULTCOSTO)
                cur.execute(f'ALTER TABLE {PG_SCHEMA}.{PG_TABLA} ADD COLUMN IF NOT EXISTS "P. LISTA VS ULT. COSTO" numeric(20,2)')
                cur.execute(f"TRUNCATE TABLE {PG_SCHEMA}.{PG_TABLA};")
                cur.execute(f"INSERT INTO {PG_SCHEMA}.{PG_TABLA} ({nombres}) {SQL_DDMRP}")
                filas = cur.rowcount
                # pega el TOP por empresa + código de ítem
                cur.execute(f"""
                    UPDATE {PG_SCHEMA}.{PG_TABLA} d
                    SET "TOP" = x.top
                    FROM ({SQL_TOP}) x
                    WHERE d."EMPRESA" = x.dit_empresa AND d."CODIGO_ITEM" = x.dit_codigo
                """)
                log.info("TOP actualizado en %s ítems", cur.rowcount)
                # stock total, demandas, variación y meses de inventario (usan columnas ya cargadas)
                cur.execute(SQL_STOCK_TOTAL)
                cur.execute(SQL_STOCK_PROYECTADO_DLT)
                cur.execute(SQL_DEMANDA_MES_1ANIO)
                cur.execute(SQL_DEMANDA_MES_90D)
                cur.execute(SQL_VAR_DEMANDA)
                cur.execute(SQL_MES_INV_TOTAL)
                # pega el DLT por empresa + código de ítem
                cur.execute(f"""
                    UPDATE {PG_SCHEMA}.{PG_TABLA} d
                    SET "DLT" = x.dlt
                    FROM ({SQL_DLT}) x
                    WHERE d."EMPRESA" = x.empresa AND d."CODIGO_ITEM" = x.codigoitem
                """)
                log.info("DLT actualizado en %s ítems", cur.rowcount)
                # DLT de IKONIX por marca -> proveedor de MAXXIMUNDO
                cur.execute(SQL_DLT_IKONIX, {
                    "empresa":     EMPRESA_DLT_POR_MARCA,
                    "marcas":      list(MARCA_PROVEEDOR_IKONIX),
                    "proveedores": list(MARCA_PROVEEDOR_IKONIX.values()),
                })
                log.info("DLT de %s por marca en %s ítems", EMPRESA_DLT_POR_MARCA, cur.rowcount)
                # DLT faltante: promedio por marca (solo ítems que quedaron en 0)
                cur.execute(SQL_DLT_MARCA)
                log.info("DLT por promedio de marca en %s ítems", cur.rowcount)
                # pega el VF por empresa + código de ítem
                cur.execute(f"""
                    UPDATE {PG_SCHEMA}.{PG_TABLA} d
                    SET "VF" = x.vf
                    FROM ({SQL_VF}) x
                    WHERE d."EMPRESA" = x.hev_empresa AND d."CODIGO_ITEM" = x.hev_codigoitem
                """)
                log.info("VF actualizado en %s ítems", cur.rowcount)
                # VF por defecto (0.20) donde quedó en 0
                cur.execute(SQL_VF_DEFAULT)
                log.info("VF por defecto (0.20) en %s ítems", cur.rowcount)
                # pega el ADU por empresa + código de ítem
                cur.execute(f"""
                    UPDATE {PG_SCHEMA}.{PG_TABLA} d
                    SET "ADU" = a.adu
                    FROM ({SQL_ADU}) a
                    WHERE d."EMPRESA" = a.hev_empresa AND d."CODIGO_ITEM" = a.hev_codigoitem
                """)
                log.info("ADU actualizado en %s ítems", cur.rowcount)
                # LTF según el tramo del DLT de cada ítem
                cur.execute(SQL_LTF)
                # LTF por defecto (0.20) donde quedó en 0
                cur.execute(SQL_LTF_DEFAULT)
                log.info("LTF por defecto (0.20) en %s ítems", cur.rowcount)
                # zona roja (con ADU, DLT, LTF y VF ya cargados) y luego el TOR
                cur.execute(SQL_ZONA_ROJA_BASE)
                cur.execute(SQL_ZONA_ROJA_SEGURIDAD)
                cur.execute(SQL_TOR)
                # zona amarilla y luego el TOY (usa el TOR)
                cur.execute(SQL_ZONA_AMARILLA)
                cur.execute(SQL_TOY)
                # zona verde (usa ADU y ZONA ROJA BASE)
                cur.execute(SQL_ZONA_VERDE)
                # TOG (usa TOY y ZONA VERDE)
                cur.execute(SQL_TOG)
                # NFP y luego el pedido sugerido (usa NFP, TOY y TOG)
                cur.execute(SQL_NFP)
                cur.execute(SQL_PEDIDO_SUGERIDO)
                # nuevo tamaño de pedido (usa MES INV TOTAL y PEDIDO SUGERIDO)
                cur.execute(SQL_NUEVO_TAMANO_PEDIDO)
                # pega costos y precio por empresa + código de ítem
                cur.execute(f"""
                    UPDATE {PG_SCHEMA}.{PG_TABLA} d
                    SET "ULTIMO FOB"      = x.ultimo_fob,
                        "COSTO PROMEDIO"  = x.costo_promedio,
                        "ULTIMO COSTO"    = x.ultimo_costo,
                        "LISTA PRECIOS A" = x.lista_precios_a
                    FROM ({SQL_COSTOS}) x
                    WHERE d."EMPRESA" = x.dit_empresa AND d."CODIGO_ITEM" = x.dit_codigo
                """)
                log.info("Costos y precio actualizados en %s ítems", cur.rowcount)
                # margen lista vs último costo (usa LISTA PRECIOS A y ULTIMO COSTO)
                cur.execute(SQL_PLISTA_VS_ULTCOSTO)
        log.info("Cargadas %s filas en %s.%s", filas, PG_SCHEMA, PG_TABLA)
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
        log.error("No se actualiza %s.%s porque fallaron procesos previos", PG_SCHEMA, PG_TABLA)
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
