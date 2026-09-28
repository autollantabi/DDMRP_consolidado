import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pyodbc
import psycopg2
from psycopg2.extras import execute_values

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import POSTGRES, sqlserver_conn_str

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"            # cambia si ddmrp_inventario está en otro esquema
PG_TABLA  = "ddmrp_inventario"

# Bodegas por empresa: códigos de dim_bodegas.dib_codigobodega, se comparan tal
# cual (sin rellenar con 0). Solo se extraen las empresas que estén aquí.
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
# EXTRACCIÓN (SQL Server)
# ---------------------------------------------------------------------------
def extraer(dias_1anio, dias_90d):
    # Fechas dinámicas (corte - dias_1anio y corte - dias_90d)
    desde_1a  = HOY - timedelta(days=dias_1anio - 1)   # 365: 2026-09-22 -> 2025-09-21
    desde_90d = HOY - timedelta(days=dias_90d - 1)     # 90:  2026-09-22 -> 2026-06-24

    # (b.dib_nombreempresa = ? AND b.dib_codigobodega IN (?, ...)) OR (...) por cada empresa
    bloques, params_bodegas = [], []
    for empresa, codigos in BODEGAS_POR_EMPRESA.items():
        marcas = ", ".join("?" for _ in codigos)
        bloques.append(f"(b.dib_nombreempresa = ? AND b.dib_codigobodega IN ({marcas}))")
        params_bodegas += [empresa, *codigos]
    filtro_bodegas = " OR ".join(bloques)

    sql = f"""
        SELECT
            hex_empresa,
            hex_identificadoritem,
            COUNT(DISTINCT CAST(hex_fechasubida AS DATE)) AS dias_stock_1anio,
            COUNT(DISTINCT CASE
                               WHEN hex_fechasubida >= ?
                               THEN CAST(hex_fechasubida AS DATE)
                           END) AS dias_stock_90d
        FROM DWH.dbo.hec_existencias
        --FROM DWH.dbo.existencias_stox
        WHERE hex_fechasubida >= ?
          AND hex_fechasubida < ?
          AND hex_stock > 0
          AND EXISTS (
              SELECT 1
              FROM DWH.dbo.dim_bodegas b
              WHERE b.dib_nombreempresa = hex_empresa
                AND b.dib_nombrebodega  = hex_nombrealmacen
                AND ({filtro_bodegas})
          )
    """
    # Fechas como texto YYYYMMDD: el driver "SQL Server" no acepta parámetros tipo date
    params = [desde_90d.strftime("%Y%m%d"), desde_1a.strftime("%Y%m%d"),
              HASTA.strftime("%Y%m%d"), *params_bodegas]

    if FILTRO_EMPRESA:
        sql += " AND hex_empresa = ?"
        params.append(FILTRO_EMPRESA)
    if FILTRO_ITEM:
        sql += " AND hex_identificadoritem = ?"
        params.append(FILTRO_ITEM)

    sql += " GROUP BY hex_empresa, hex_identificadoritem;"

    with pyodbc.connect(sqlserver_conn_str()) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        filas = [(r[0], r[1], float(r[2]), float(r[3])) for r in cur.fetchall()]

    log.info("Extraídas %s filas de SQL Server (corte %s: 1 año desde %s, 90d desde %s)",
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