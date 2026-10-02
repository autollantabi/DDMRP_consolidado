import logging
import sys
from pathlib import Path

import psycopg2

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import POSTGRES

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_medidas_top"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("medidas_top")


# ---------------------------------------------------------------------------
# CONSULTA: marca TOP = 'SI' si la descripción del ítem (dim_item) contiene una
# medida de core.ddmrp_medidastop; si no, 'NO'.
#   Para comparar se quita el guion de "R-" (ej. "175/70 R-13" coincide con "175/70 R13");
#   la descripción se guarda tal cual.
# ---------------------------------------------------------------------------
SQL_MEDIDAS_TOP = """
SELECT
    a.dit_empresa,
    a.dit_codigo,
    a.dit_nombre,
    b.medida,
    CASE
        WHEN b.medida IS NOT NULL THEN 'SI'
        ELSE 'NO'
    END AS top
FROM core.dim_item a
LEFT JOIN core.ddmrp_medidastop b
    ON REPLACE(a.dit_nombre, 'R-', 'R') ILIKE '%' || b.medida || '%'
"""


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL): crea la tabla si no existe, borra sus registros e inserta
# ---------------------------------------------------------------------------
def cargar():
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:                      # una sola transacción: si falla, no deja la tabla vacía
            with conn.cursor() as cur:
                cur.execute(f"CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} AS {SQL_MEDIDAS_TOP} WITH NO DATA")
                cur.execute(f"TRUNCATE TABLE {PG_SCHEMA}.{PG_TABLA};")
                cur.execute(f"INSERT INTO {PG_SCHEMA}.{PG_TABLA} {SQL_MEDIDAS_TOP}")
                filas = cur.rowcount
        log.info("Cargadas %s filas en %s.%s", filas, PG_SCHEMA, PG_TABLA)
    finally:
        conn.close()


def ejecutar():
    cargar()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al cargar medidas top")
        raise
