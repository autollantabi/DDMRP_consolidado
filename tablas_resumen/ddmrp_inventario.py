import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import POSTGRES

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"            # cambia si ddmrp_inventario está en otro esquema
PG_TABLA  = "ddmrp_inventario"

# Bodegas de venta por empresa: códigos de bodega (core.hec_inventario.inv_codigo_bodega,
# los mismos de SAP). Solo se extraen las empresas que estén aquí.
BODEGAS_POR_EMPRESA = {
    "MAXXIMUNDO": ["02", "03", "07", "08", "09", "10"],
    "AUTOLLANTA": ["01", "02", "03", "07", "08", "09", "10"],
    "STOX":       ["02", "03", "07", "08", "09", "10"],
    "IKONIX":     ["01", "02", "03", "07", "08", "09", "10"],
    "AUTOMAX":    ["01", "02", "03", "04", "05"],
}

# Filtros opcionales: pon None para traer todas las empresas / todos los ítems
FILTRO_EMPRESA = None
FILTRO_ITEM    = None

# Fecha de corte opcional: pon una fecha, ej. date(2026, 6, 30), para calcular
# las ventanas hacia atrás desde esa fecha. Con None se usa hoy.
FECHA_CORTE = None #date(2026, 9, 23)

HOY   = FECHA_CORTE or date.today()
HASTA = HOY + timedelta(days=1)     # límite superior exclusivo (incluye todo el día de corte)

# Días de cada ventana en core.ddmrp_parametros (ddmrp_valor_num, solo ddmrp_estado = 1)
ID_DIAS_1ANIO = 1    # Ventas 1 anio -> 365
ID_DIAS_90D   = 2    # Venta 90 dias -> 90

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("etl_dias_stock")


# ---------------------------------------------------------------------------
# PARÁMETROS (PostgreSQL)
# ---------------------------------------------------------------------------
def leer_parametros():
    ids = (ID_DIAS_1ANIO, ID_DIAS_90D)
    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ddmrp_id, ddmrp_valor_num
            FROM core.ddmrp_parametros
            WHERE ddmrp_id IN %s AND ddmrp_estado = 1
        """, (ids,))
        valores = dict(cur.fetchall())

    faltan = [i for i in ids if valores.get(i) is None]
    if faltan:
        raise ValueError(f"Faltan parámetros activos en core.ddmrp_parametros: ddmrp_id {faltan}")

    log.info("Parámetros: días 1 año = %s, días 90d = %s",
             valores[ID_DIAS_1ANIO], valores[ID_DIAS_90D])
    return int(valores[ID_DIAS_1ANIO]), int(valores[ID_DIAS_90D])


# ---------------------------------------------------------------------------
# EXTRACCIÓN (PostgreSQL, core.hec_inventario: una foto diaria de stock por ítem y bodega)
#   Un día cuenta si el ítem tuvo stock > 0 en al menos una bodega de venta de su empresa.
#   La bodega se cruza por CÓDIGO (no por nombre: los nombres cambian, el código no).
# ---------------------------------------------------------------------------
def extraer(dias_1anio, dias_90d):
    # Fechas dinámicas: ventanas de dias_1anio y dias_90d días que terminan en el día de corte
    desde_1a  = HOY - timedelta(days=dias_1anio - 1)   # 365: 2026-10-07 -> 2025-10-08
    desde_90d = HOY - timedelta(days=dias_90d - 1)     # 90:  2026-10-07 -> 2026-07-10

    # pares (empresa, código de bodega de venta)
    bodegas = tuple((empresa, codigo) for empresa, codigos in BODEGAS_POR_EMPRESA.items()
                    for codigo in codigos)

    sql = """
        SELECT
            inv_empresa,
            inv_cod_item,
            COUNT(DISTINCT inv_fecha_subida::date)                                    AS dias_stock_1anio,
            COUNT(DISTINCT inv_fecha_subida::date) FILTER (WHERE inv_fecha_subida >= %(desde_90d)s)
                                                                                      AS dias_stock_90d
        FROM core.hec_inventario
        WHERE inv_fecha_subida >= %(desde_1a)s
          AND inv_fecha_subida <  %(hasta)s
          AND inv_stock > 0
          AND (inv_empresa, inv_codigo_bodega) IN %(bodegas)s
    """
    params = {"desde_90d": desde_90d, "desde_1a": desde_1a, "hasta": HASTA, "bodegas": bodegas}

    if FILTRO_EMPRESA:
        sql += " AND inv_empresa = %(empresa)s"
        params["empresa"] = FILTRO_EMPRESA
    if FILTRO_ITEM:
        sql += " AND inv_cod_item = %(item)s"
        params["item"] = FILTRO_ITEM

    sql += " GROUP BY inv_empresa, inv_cod_item;"

    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        filas = [(r[0], r[1], float(r[2]), float(r[3])) for r in cur.fetchall()]

    log.info("Extraídas %s filas de core.hec_inventario (corte %s: 1 año desde %s, 90d desde %s)",
             len(filas), HOY, desde_1a, desde_90d)
    return filas


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL)
# ---------------------------------------------------------------------------
# "ddmrp_stock_inv_90D" va entre comillas porque tiene mayúscula.
CREATE = f"""
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} (
    ddmpr_empresa           varchar,
    ddmrp_item              varchar,
    ddmrp_stock_inv_1anio   double precision,
    "ddmrp_stock_inv_90D"   double precision
)
"""

INSERT = f"""
INSERT INTO {PG_SCHEMA}.{PG_TABLA}
    (ddmpr_empresa, ddmrp_item, ddmrp_stock_inv_1anio, "ddmrp_stock_inv_90D")
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


# ---------------------------------------------------------------------------
def ejecutar():
    cargar(extraer(*leer_parametros()))


if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error en el ETL")
        raise