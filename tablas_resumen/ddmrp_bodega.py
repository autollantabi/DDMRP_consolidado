import logging
import sys
from pathlib import Path

import psycopg2
from hdbcli import dbapi
from psycopg2.extras import execute_values

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import HANA, POSTGRES

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_bodegas"

# Empresas: esquema SAP, prefijo del código (ST_2000191) y bodegas (OITW.WhsCode)
EMPRESAS_CONFIG = [
    {"codigo": "STOX",       "abreviatura": "ST",  "bodegas": ["02", "03", "07", "08", "09", "10"]},
    {"codigo": "AUTOLLANTA", "abreviatura": "AU",  "bodegas": ["01", "02", "03", "07", "08", "09", "10"]},
    {"codigo": "MAXXIMUNDO", "abreviatura": "MA",  "bodegas": ["02", "03", "07", "08", "09", "10"]},
    {"codigo": "IKONIX",     "abreviatura": "IK",  "bodegas": ["01", "02", "03", "07", "08", "09", "10"]},
    {"codigo": "AUTOMAX",    "abreviatura": "ATX", "bodegas": ["01", "02", "03", "04", "05"]},
]

SEPARADOR = "_"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("bodega")


# ---------------------------------------------------------------------------
# EXTRACCIÓN (SAP HANA): stock (OnHand) por ítem en las bodegas de cada empresa
# ---------------------------------------------------------------------------
SQL_TEMPLATE = """
SELECT
    T0."ItemCode" AS "codigo",
    T0."ItemName" AS "nombre_item",
    COALESCE(
        MAX(T2."ItmsGrpNam"),
        'NO EXISTE PROPIEDAD ACTIVA'
    ) AS "PROPIEDAD",
    SUM(T1."OnHand") AS "sum"
FROM "{schema}"."OITM" T0
INNER JOIN "{schema}"."OITW" T1
    ON T0."ItemCode" = T1."ItemCode"
LEFT JOIN "{schema}"."OITG" T2
    ON T2."ItmsTypCod" =
        CASE
            WHEN T0."QryGroup1" = 'Y' THEN 1
            WHEN T0."QryGroup2" = 'Y' THEN 2
            WHEN T0."QryGroup3" = 'Y' THEN 3
            WHEN T0."QryGroup4" = 'Y' THEN 4
            WHEN T0."QryGroup5" = 'Y' THEN 5
            WHEN T0."QryGroup6" = 'Y' THEN 6
            WHEN T0."QryGroup7" = 'Y' THEN 7
            WHEN T0."QryGroup8" = 'Y' THEN 8
            WHEN T0."QryGroup9" = 'Y' THEN 9
            WHEN T0."QryGroup10" = 'Y' THEN 10
            WHEN T0."QryGroup11" = 'Y' THEN 11
            WHEN T0."QryGroup12" = 'Y' THEN 12
            WHEN T0."QryGroup13" = 'Y' THEN 13
            WHEN T0."QryGroup14" = 'Y' THEN 14
            WHEN T0."QryGroup15" = 'Y' THEN 15
            WHEN T0."QryGroup16" = 'Y' THEN 16
            WHEN T0."QryGroup17" = 'Y' THEN 17
            WHEN T0."QryGroup18" = 'Y' THEN 18
            WHEN T0."QryGroup19" = 'Y' THEN 19
            WHEN T0."QryGroup20" = 'Y' THEN 20
            WHEN T0."QryGroup21" = 'Y' THEN 21
            WHEN T0."QryGroup22" = 'Y' THEN 22
            WHEN T0."QryGroup23" = 'Y' THEN 23
            WHEN T0."QryGroup24" = 'Y' THEN 24
            WHEN T0."QryGroup25" = 'Y' THEN 25
            WHEN T0."QryGroup26" = 'Y' THEN 26
            WHEN T0."QryGroup27" = 'Y' THEN 27
            WHEN T0."QryGroup28" = 'Y' THEN 28
            WHEN T0."QryGroup29" = 'Y' THEN 29
            WHEN T0."QryGroup30" = 'Y' THEN 30
            WHEN T0."QryGroup31" = 'Y' THEN 31
            WHEN T0."QryGroup32" = 'Y' THEN 32
            WHEN T0."QryGroup33" = 'Y' THEN 33
            WHEN T0."QryGroup34" = 'Y' THEN 34
            WHEN T0."QryGroup35" = 'Y' THEN 35
            WHEN T0."QryGroup36" = 'Y' THEN 36
            WHEN T0."QryGroup37" = 'Y' THEN 37
            WHEN T0."QryGroup38" = 'Y' THEN 38
            WHEN T0."QryGroup39" = 'Y' THEN 39
            WHEN T0."QryGroup40" = 'Y' THEN 40
            WHEN T0."QryGroup41" = 'Y' THEN 41
            WHEN T0."QryGroup42" = 'Y' THEN 42
            WHEN T0."QryGroup43" = 'Y' THEN 43
            WHEN T0."QryGroup44" = 'Y' THEN 44
            WHEN T0."QryGroup45" = 'Y' THEN 45
            WHEN T0."QryGroup46" = 'Y' THEN 46
            WHEN T0."QryGroup47" = 'Y' THEN 47
            WHEN T0."QryGroup48" = 'Y' THEN 48
            WHEN T0."QryGroup49" = 'Y' THEN 49
            WHEN T0."QryGroup50" = 'Y' THEN 50
            WHEN T0."QryGroup51" = 'Y' THEN 51
            WHEN T0."QryGroup52" = 'Y' THEN 52
            WHEN T0."QryGroup53" = 'Y' THEN 53
            WHEN T0."QryGroup54" = 'Y' THEN 54
            WHEN T0."QryGroup55" = 'Y' THEN 55
            WHEN T0."QryGroup56" = 'Y' THEN 56
            WHEN T0."QryGroup57" = 'Y' THEN 57
            WHEN T0."QryGroup58" = 'Y' THEN 58
            WHEN T0."QryGroup59" = 'Y' THEN 59
            WHEN T0."QryGroup60" = 'Y' THEN 60
            WHEN T0."QryGroup61" = 'Y' THEN 61
            WHEN T0."QryGroup62" = 'Y' THEN 62
            WHEN T0."QryGroup63" = 'Y' THEN 63
            WHEN T0."QryGroup64" = 'Y' THEN 64
        END
WHERE T1."WhsCode" IN ({bodegas_in})
GROUP BY
    T0."ItemCode",
    T0."ItemName";
"""


def extraer():
    filas = []
    conn = dbapi.connect(**HANA)
    try:
        cur = conn.cursor()
        for emp in EMPRESAS_CONFIG:
            schema = (f"SBO_{emp['codigo']}_PROD1" if emp["codigo"] == "AUTOMAX"
                      else f"SBO_{emp['codigo']}_PROD")
            marcas = ", ".join("?" for _ in emp["bodegas"])
            cur.execute(SQL_TEMPLATE.format(schema=schema, bodegas_in=marcas), emp["bodegas"])
            datos = cur.fetchall()
            if not datos:
                log.warning("No se encontraron datos para el esquema %s", schema)
            # columnas en el orden de la tabla: codigo, nombre_item, propiedad, empresa, sum
            filas += [(f"{emp['abreviatura']}{SEPARADOR}{codigo}", nombre_item, propiedad, emp["codigo"], stock)
                      for codigo, nombre_item, propiedad, stock in datos]
            log.info("Extraídas %s filas de %s (bodegas %s)", len(datos), schema, emp["bodegas"])
    finally:
        conn.close()
    return filas


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL): crea la tabla si no existe, borra sus registros e inserta
# ---------------------------------------------------------------------------
CREATE = f"""
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} (
    codigo   varchar,
    nombre_item varchar,
    propiedad varchar,
    empresa  varchar,
    sum      bigint
)
"""

# Si la tabla ya existía sin nombre_item ni propiedad, CREATE TABLE IF NOT EXISTS no las agrega
ALTER = (f"ALTER TABLE {PG_SCHEMA}.{PG_TABLA} "
         f"ADD COLUMN IF NOT EXISTS nombre_item varchar, ADD COLUMN IF NOT EXISTS propiedad varchar")

INSERT = f"INSERT INTO {PG_SCHEMA}.{PG_TABLA} (codigo, nombre_item, propiedad, empresa, sum) VALUES %s"

# ---------------------------------------------------------------------------
# HOMOLOGACIÓN: el stock de STOX con propiedad ROADWING PESADO se SUMA al ítem de
# AUTOLLANTA que tiene el mismo nombre (igual que vw_ddmrp_ventas hace con las ventas)
#   AUTOLLANTA.sum = AUTOLLANTA.sum + STOX.sum      (STOX conserva su stock)
# El nombre se compara sin importar mayúsculas ni espacios al inicio/final.
# ---------------------------------------------------------------------------
SQL_SUMAR_STOCK_ROADWING = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA} au
SET sum = au.sum + st.sum
FROM (
    SELECT UPPER(TRIM(nombre_item)) AS nombre, SUM(sum) AS sum
    FROM {PG_SCHEMA}.{PG_TABLA}
    WHERE empresa = 'STOX' AND propiedad = 'ROADWING PESADO'
    GROUP BY UPPER(TRIM(nombre_item))
) st
WHERE au.empresa = 'AUTOLLANTA' AND UPPER(TRIM(au.nombre_item)) = st.nombre
"""

# ---------------------------------------------------------------------------
# HOMOLOGACIÓN: el stock de MAXXIMUNDO con propiedad CST MOTO (llantas moto CST) se SUMA
# al ítem de STOX que tiene el mismo nombre (igual que vw_ddmrp_ventas hace con las ventas)
#   STOX.sum = STOX.sum + MAXXIMUNDO.sum            (MAXXIMUNDO conserva su stock)
# El nombre se compara sin importar mayúsculas ni espacios al inicio/final.
# ---------------------------------------------------------------------------
SQL_SUMAR_STOCK_CST = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA} st
SET sum = st.sum + ma.sum
FROM (
    SELECT UPPER(TRIM(nombre_item)) AS nombre, SUM(sum) AS sum
    FROM {PG_SCHEMA}.{PG_TABLA}
    WHERE empresa = 'MAXXIMUNDO' AND propiedad = 'CST MOTO'
    GROUP BY UPPER(TRIM(nombre_item))
) ma
WHERE st.empresa = 'STOX' AND UPPER(TRIM(st.nombre_item)) = ma.nombre
"""


def cargar(filas):
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:                      # una sola transacción: si falla, no deja la tabla vacía
            with conn.cursor() as cur:
                cur.execute(CREATE)
                cur.execute(ALTER)
                cur.execute(f"TRUNCATE TABLE {PG_SCHEMA}.{PG_TABLA};")
                if filas:
                    execute_values(cur, INSERT, filas, page_size=5000)
                # stock de ROADWING PESADO de STOX -> se suma en AUTOLLANTA (mismo nombre de ítem)
                cur.execute(SQL_SUMAR_STOCK_ROADWING)
                log.info("Stock ROADWING PESADO de STOX sumado a AUTOLLANTA en %s ítems", cur.rowcount)
                # stock de CST MOTO de MAXXIMUNDO -> se suma en STOX (mismo nombre de ítem)
                cur.execute(SQL_SUMAR_STOCK_CST)
                log.info("Stock CST MOTO de MAXXIMUNDO sumado a STOX en %s ítems", cur.rowcount)
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
        log.exception("Error al cargar stock por bodega")
        raise
