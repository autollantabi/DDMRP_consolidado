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
PG_TABLA  = "ddmrp_proveedores_dlt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("proveedores_dlt")


# ---------------------------------------------------------------------------
# DLT por empresa + proveedor (días), con los tiempos cargados en la tabla:
#   DLT MAX = confirmación del pedido + producción + backorder + coordinación del booking
#           + tránsito internacional + aduana        (suma todo)
#   DLT MIN = DLT MAX sin el tiempo de backorder
# El master usa el MAX si el ítem tiene backorders y el MIN si no tiene.
# Un tiempo vacío (NULL) se cuenta como 0.
# ---------------------------------------------------------------------------
SQL_DLT = f"""
UPDATE {PG_SCHEMA}.{PG_TABLA}
SET ddmrp_dlt_max = COALESCE(ddmrp_tiempo_confi_pedido, 0)
                  + COALESCE(ddmrp_tiempo_producccion, 0)
                  + COALESCE(ddmrp_tiempo_backorder, 0)
                  + COALESCE(ddmrp_tiempo_coord_booking, 0)
                  + COALESCE(ddmrp_tiempo_transito, 0)
                  + COALESCE(ddmrp_tiempo_aduana, 0),
    ddmrp_dlt_min = COALESCE(ddmrp_tiempo_confi_pedido, 0)
                  + COALESCE(ddmrp_tiempo_producccion, 0)
                  + COALESCE(ddmrp_tiempo_coord_booking, 0)
                  + COALESCE(ddmrp_tiempo_transito, 0)
                  + COALESCE(ddmrp_tiempo_aduana, 0)
"""

# Proveedores con producción, tránsito o aduana en 0 o vacíos: el DLT queda incompleto (solo aviso)
SQL_INCOMPLETOS = f"""
SELECT ddmrp_empresa, ddmrp_codigo_proveedor, ddmrp_dlt_max, ddmrp_dlt_min
FROM {PG_SCHEMA}.{PG_TABLA}
WHERE COALESCE(ddmrp_tiempo_producccion, 0) = 0
   OR COALESCE(ddmrp_tiempo_transito, 0)    = 0
   OR COALESCE(ddmrp_tiempo_aduana, 0)      = 0
ORDER BY ddmrp_empresa, ddmrp_codigo_proveedor
"""


def ejecutar():
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:                      # una sola transacción
            with conn.cursor() as cur:
                cur.execute(SQL_DLT)
                log.info("DLT max y min actualizados en %s proveedores de %s.%s",
                         cur.rowcount, PG_SCHEMA, PG_TABLA)
                cur.execute(SQL_INCOMPLETOS)
                incompletos = cur.fetchall()
        if incompletos:
            log.warning("%s proveedores tienen producción, tránsito o aduana en 0 (DLT incompleto):",
                        len(incompletos))
            for empresa, proveedor, dlt_max, dlt_min in incompletos:
                log.warning("   %s | %s | DLT max = %s | DLT min = %s", empresa, proveedor, dlt_max, dlt_min)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al actualizar el DLT de proveedores")
        raise
