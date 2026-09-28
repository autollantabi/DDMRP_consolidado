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
    SUM(T1."OnHand") AS "sum"
FROM "{schema}"."OITM" T0
INNER JOIN "{schema}"."OITW" T1
    ON T0."ItemCode" = T1."ItemCode"
WHERE T1."WhsCode" IN ({bodegas_in})
GROUP BY
    T0."ItemCode"
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
            # columnas en el orden de la tabla: codigo, empresa, sum
            filas += [(f"{emp['abreviatura']}{SEPARADOR}{codigo}", emp["codigo"], stock)
                      for codigo, stock in datos]
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
    empresa  varchar,
    sum      bigint
)
"""

INSERT = f"INSERT INTO {PG_SCHEMA}.{PG_TABLA} (codigo, empresa, sum) VALUES %s"


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
        log.exception("Error al cargar stock por bodega")
        raise
