import logging
import sys
from collections import Counter
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import POSTGRES

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_proveedor_item"

# IKONIX no importa: MAXXIMUNDO le importa y los códigos de ítem son distintos entre
# empresas, así que su proveedor (y su DLT en master.py) se asigna por MARCA -> proveedor
EMPRESA_DLT_POR_MARCA = "IKONIX"
MARCA_PROVEEDOR_IKONIX = {
    "UYUSTOOLS": "P2222222222002",   # HANGZHOU HANTOO ENTERPRISES CO., LTD
    "DONGCHENG": "P9999999999994",   # JIANGSU DONGCHENG IMPORT AND EXPORT TRADE CO.,LTD.
    "SATA":      "P9999999999993",   # SHANGHAI DATECH IMP.&EXP. ENTERPRISES CO., LTD.
}
# Empresa que importa para IKONIX: sus socios (proveedores) están registrados en esta empresa
EMPRESA_IMPORTADORA = "MAXXIMUNDO"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("proveedor_item")


# ---------------------------------------------------------------------------
# PROVEEDOR 1 y 2 por empresa + ítem
#   1º dim_item: dit_proveedorprincipal (PROV1) y dit_proveedorsecundario (PROV2);
#      'UF' o vacío = sin dato.
#   2º Si dim_item no tiene proveedor: los 2 proveedores de importación más recientes
#      (facturas de reserva unidas a importaciones por número de PI, ordenados por la
#      última fecha de factura de reserva). IKONIX por marca (MARCA_PROVEEDOR_IKONIX).
# NOMBRE del proveedor:
#   - origen DIM_ITEM:      dim_socios de la misma empresa -> dim_socios de la empresa
#                           importadora -> nombre en hec_importaciones -> el código
#   - origen IMPORTACIONES: nombre en hec_importaciones -> dim_socios de la misma empresa
#                           -> dim_socios de la empresa importadora -> el código
#   (en dim_socios un mismo código puede tener distinto nombre según la empresa)
#   parámetros: empresa IKONIX, marcas y proveedores (mismo orden), empresa importadora
# ---------------------------------------------------------------------------
SQL = """
WITH dim AS (
	SELECT dit_empresa AS empresa, dit_codigo AS codigoitem,
	       NULLIF(NULLIF(TRIM(dit_proveedorprincipal), ''), 'UF')  AS p1,
	       NULLIF(NULLIF(TRIM(dit_proveedorsecundario), ''), 'UF') AS p2
	FROM core.dim_item
),
relacion AS (
	SELECT hfr.hfr_empresa AS empresa, hfr.hfr_codigoitem AS codigoitem,
	       imp.heim_codigoproveedor AS cod_proveedor, MAX(hfr.hfr_fechadocumento) AS ultima_fecha
	FROM core.hec_facturas_reserva hfr
	JOIN core.hec_importaciones imp ON hfr.hfr_numeropi = imp.heim_num_pi
	GROUP BY 1, 2, 3
	UNION ALL
	SELECT d.dit_empresa, d.dit_codigo, m.cod_proveedor, NULL
	FROM core.dim_item d
	JOIN unnest(%(marcas)s::text[], %(proveedores)s::text[]) AS m(marca, cod_proveedor)
	  ON d.dit_empresa = %(empresa_marca)s AND UPPER(TRIM(d.dit_nombrefabricante)) = m.marca
),
imp AS (
	SELECT empresa, codigoitem,
	       MAX(cod_proveedor) FILTER (WHERE rn = 1) AS cod1,
	       MAX(cod_proveedor) FILTER (WHERE rn = 2) AS cod2
	FROM (SELECT r.*, ROW_NUMBER() OVER (PARTITION BY empresa, codigoitem
	                                     ORDER BY ultima_fecha DESC NULLS LAST, cod_proveedor) AS rn
	      FROM relacion r) x
	GROUP BY empresa, codigoitem
),
base AS (
	SELECT d.empresa, d.codigoitem,
	       CASE WHEN COALESCE(d.p1, d.p2) IS NOT NULL THEN 'DIM_ITEM' ELSE 'IMPORTACIONES' END AS origen,
	       CASE WHEN COALESCE(d.p1, d.p2) IS NOT NULL THEN COALESCE(d.p1, d.p2) ELSE i.cod1 END AS cod1,
	       CASE WHEN COALESCE(d.p1, d.p2) IS NOT NULL THEN CASE WHEN d.p1 IS NOT NULL THEN d.p2 END
	            ELSE i.cod2 END AS cod2
	FROM dim d
	LEFT JOIN imp i ON i.empresa = d.empresa AND i.codigoitem = d.codigoitem
	WHERE COALESCE(d.p1, d.p2, i.cod1) IS NOT NULL
),
socios AS (
	SELECT ds_nombreempresa AS empresa, ds_codigosocio AS codigo, MAX(ds_nombre) AS nombre
	FROM core.dim_socios
	GROUP BY 1, 2
),
nombres_imp AS (
	SELECT heim_codigoproveedor AS codigo, MAX(heim_proveedor) AS nombre
	FROM core.hec_importaciones
	GROUP BY 1
)
SELECT
	b.empresa, b.codigoitem,
	b.cod1,
	CASE WHEN b.origen = 'DIM_ITEM'
	     THEN COALESCE(s1.nombre, s1m.nombre, n1.nombre, b.cod1)
	     ELSE COALESCE(n1.nombre, s1.nombre, s1m.nombre, b.cod1) END AS nom1,
	b.cod2,
	CASE WHEN b.cod2 IS NULL THEN NULL
	     WHEN b.origen = 'DIM_ITEM'
	     THEN COALESCE(s2.nombre, s2m.nombre, n2.nombre, b.cod2)
	     ELSE COALESCE(n2.nombre, s2.nombre, s2m.nombre, b.cod2) END AS nom2,
	b.origen
FROM base b
LEFT JOIN socios s1  ON s1.empresa  = b.empresa              AND s1.codigo  = b.cod1
LEFT JOIN socios s1m ON s1m.empresa = %(empresa_importadora)s AND s1m.codigo = b.cod1
LEFT JOIN nombres_imp n1 ON n1.codigo = b.cod1
LEFT JOIN socios s2  ON s2.empresa  = b.empresa              AND s2.codigo  = b.cod2
LEFT JOIN socios s2m ON s2m.empresa = %(empresa_importadora)s AND s2m.codigo = b.cod2
LEFT JOIN nombres_imp n2 ON n2.codigo = b.cod2
"""

PARAMS = {
    "empresa_marca":       EMPRESA_DLT_POR_MARCA,
    "marcas":              list(MARCA_PROVEEDOR_IKONIX),
    "proveedores":         list(MARCA_PROVEEDOR_IKONIX.values()),
    "empresa_importadora": EMPRESA_IMPORTADORA,
}


def extraer():
    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute(SQL, PARAMS)
        filas = cur.fetchall()
    origen = Counter(f[-1] for f in filas)
    log.info("Proveedor por ítem: %s ítems (desde dim_item %s, desde importaciones %s)",
             len(filas), origen.get("DIM_ITEM", 0), origen.get("IMPORTACIONES", 0))
    return filas


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL): crea la tabla si no existe, borra sus registros e inserta
# ---------------------------------------------------------------------------
CREATE = f"""
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} (
    empresa      varchar,
    codigo_item  varchar,
    cod_prov1    varchar,
    nom_prov1    varchar,
    cod_prov2    varchar,
    nom_prov2    varchar,
    origen       varchar(15)
)
"""

INSERT = f"""
INSERT INTO {PG_SCHEMA}.{PG_TABLA}
    (empresa, codigo_item, cod_prov1, nom_prov1, cod_prov2, nom_prov2, origen)
VALUES %s
"""


def cargar(filas):
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:                      # una sola transacción: si falla, no deja la tabla vacía
            with conn.cursor() as cur:
                cur.execute(CREATE)
                cur.execute(f"TRUNCATE TABLE {PG_SCHEMA}.{PG_TABLA};")
                if filas:
                    execute_values(cur, INSERT, filas, page_size=5000)
        log.info("Cargadas %s filas en %s.%s", len(filas), PG_SCHEMA, PG_TABLA)
    finally:
        conn.close()


def ejecutar():
    cargar(extraer())


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al cargar el proveedor por ítem")
        raise
