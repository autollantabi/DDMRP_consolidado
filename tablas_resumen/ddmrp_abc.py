import logging
import sys
from collections import defaultdict
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import POSTGRES

# ---------------------------------------------------------------------------
# CONFIGURACIÓN (misma lógica que pareto/cluster.py, versión v3-abc)
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_abc"

ID_DIAS_VENTANA = 1    # Ventas 1 anio (365): días hacia atrás (sin hoy) en core.ddmrp_parametros

# Entran todas las empresas, líneas e ítems con venta en la ventana (sin filtros).
# Cada empresa + línea de venta se clasifica por separado, así los montos de una
# empresa (o moneda, como AUTOMAX) nunca se comparan con los de otra.

# Score = suma de (participación del ítem en el segmento * peso); los pesos suman 1
PESOS = {"unidades": 0.20, "venta_neta": 0.30, "utilidad": 0.50}
CORTE_A = 0.80         # A: hasta el 80 % del score acumulado
CORTE_B = 0.95         # B: hasta el 95 %; C: el resto
MIN_DIAS_HISTORIA = 30 # primera venta hace menos de 30 días -> SIN_HISTORIA (se clasifica C)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("abc")


# ---------------------------------------------------------------------------
# PARÁMETROS (PostgreSQL)
# ---------------------------------------------------------------------------
def leer_dias_ventana():
    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ddmrp_valor_num
            FROM core.ddmrp_parametros
            WHERE ddmrp_id = %s AND ddmrp_estado = 1
        """, (ID_DIAS_VENTANA,))
        fila = cur.fetchone()
    if not fila or fila[0] is None:
        raise ValueError(f"Falta el parámetro activo ddmrp_id {ID_DIAS_VENTANA} en core.ddmrp_parametros")
    log.info("Parámetros: días ventana = %s", fila[0])
    return int(fila[0])


# ---------------------------------------------------------------------------
# EXTRACCIÓN (PostgreSQL): una fila por empresa + línea + ítem, últimos 'dias' días sin hoy
#   - solo FACTURA y NOTA DE CRÉDITO (las NC vienen en negativo y SUM las netea)
#   - utilidad = venta neta - costo neto (hev_utilidad viene en 0 en las NC)
# ---------------------------------------------------------------------------
SQL_EXTRACCION = """
SELECT
    hev_empresa                        AS empresa,
    hev_lineaventa                     AS linea,
    hev_codigoitem                     AS codigo_item,
    SUM(hev_cantidad)                  AS unidades,
    SUM(hev_ventaneta)                 AS venta_neta,
    SUM(hev_ventaneta - hev_costoneto) AS utilidad,
    current_date - MIN(hev_fechadocumento) AS dias_historia,
    current_date                       AS fecha_subida
FROM core.hec_ventas
WHERE hev_tipodocumento IN ('FACTURA', 'NOTA DE CRÉDITO')
  AND hev_fechadocumento >= current_date - %(dias)s
  AND hev_fechadocumento <  current_date
GROUP BY 1, 2, 3
"""


def extraer(dias):
    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute(SQL_EXTRACCION, {"dias": dias})
        columnas = [d[0] for d in cur.description]
        filas = [dict(zip(columnas, f)) for f in cur.fetchall()]
    for f in filas:                     # numeric llega como Decimal
        for c in PESOS:
            f[c] = float(f[c] or 0)
    log.info("Extraídas %s filas (últimos %s días sin hoy, %s segmentos empresa + línea)",
             len(filas), dias, len({(f["empresa"], f["linea"]) for f in filas}))
    return filas


# ---------------------------------------------------------------------------
# CLASIFICACIÓN ABC por segmento (empresa + línea)
#   1. flag: SIN_HISTORIA si la primera venta tiene < 30 días; D si venta neta <= 0; si no OK
#   2. score (solo ítems OK) = Σ peso * valor del ítem / total del segmento
#      (negativos se toman como 0: no le restan participación a los demás)
#   3. se ordena por score de mayor a menor y se acumula:
#      A hasta el 80 %, B hasta el 95 %, C el resto; el primero siempre A; score 0 -> C
#   4. segmento_final = clase ABC; SIN_HISTORIA -> C; D -> D
# ---------------------------------------------------------------------------
def clasificar(filas):
    for f in filas:
        if f["dias_historia"] < MIN_DIAS_HISTORIA:
            f["flag"] = "SIN_HISTORIA"
        elif f["venta_neta"] <= 0:
            f["flag"] = "D"
        else:
            f["flag"] = "OK"
        f["score"] = f["score_acum_pct"] = f["rank_segmento"] = f["clase_abc"] = None

    segmentos = defaultdict(list)
    for f in filas:
        if f["flag"] == "OK":
            segmentos[(f["empresa"], f["linea"])].append(f)

    for (empresa, linea), items in segmentos.items():
        totales = {c: sum(max(f[c], 0) for f in items) for c in PESOS}
        for f in items:
            f["score"] = sum(peso * max(f[c], 0) / totales[c]
                             for c, peso in PESOS.items() if totales[c] > 0)

        items.sort(key=lambda f: f["score"], reverse=True)
        total_score = sum(f["score"] for f in items)
        acumulado = 0
        for rank, f in enumerate(items, start=1):
            acumulado += f["score"]
            f["rank_segmento"] = rank
            f["score_acum_pct"] = acumulado / total_score if total_score > 0 else 0
            if f["score"] <= 0:
                f["clase_abc"] = "C"
            elif rank == 1 or f["score_acum_pct"] <= CORTE_A:
                f["clase_abc"] = "A"
            elif f["score_acum_pct"] <= CORTE_B:
                f["clase_abc"] = "B"
            else:
                f["clase_abc"] = "C"
        conteo = defaultdict(int)
        for f in items:
            conteo[f["clase_abc"]] += 1
        log.info("%s - %s: %s", empresa, linea, dict(sorted(conteo.items())))

    for f in filas:
        f["segmento_final"] = {"OK": f["clase_abc"], "SIN_HISTORIA": "C"}.get(f["flag"], f["flag"])
    return filas


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL): crea la tabla si no existe, borra sus registros e inserta
# ---------------------------------------------------------------------------
COLUMNAS = ["empresa", "linea", "codigo_item", "unidades", "venta_neta", "utilidad",
            "dias_historia", "flag", "score", "score_acum_pct", "rank_segmento",
            "clase_abc", "segmento_final", "fecha_subida"]

CREATE = f"""
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} (
    empresa         varchar,
    linea           varchar,
    codigo_item     varchar,
    unidades        numeric,
    venta_neta      numeric,
    utilidad        numeric,
    dias_historia   integer,
    flag            varchar(12),
    score           numeric,
    score_acum_pct  numeric,
    rank_segmento   integer,
    clase_abc       varchar(1),
    segmento_final  varchar(12),
    fecha_subida    date
)
"""

INSERT = f"INSERT INTO {PG_SCHEMA}.{PG_TABLA} ({', '.join(COLUMNAS)}) VALUES %s"


def cargar(filas):
    datos = [tuple(f[c] for c in COLUMNAS) for f in filas]
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:                      # una sola transacción: si falla, no deja la tabla vacía
            with conn.cursor() as cur:
                cur.execute(CREATE)
                cur.execute(f"TRUNCATE TABLE {PG_SCHEMA}.{PG_TABLA};")
                if datos:
                    execute_values(cur, INSERT, datos, page_size=5000)
        log.info("Cargadas %s filas en %s.%s", len(datos), PG_SCHEMA, PG_TABLA)
    finally:
        conn.close()


def ejecutar():
    cargar(clasificar(extraer(leer_dias_ventana())))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al cargar la clasificación ABC")
        raise
