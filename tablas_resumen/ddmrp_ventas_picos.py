import logging
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median, stdev

import psycopg2
from psycopg2.extras import execute_values

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import POSTGRES

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_ventas_picos"

FECHA_DESDE = date(2025, 5, 1)

# Filtros opcionales: pon None para traer todas las empresas / todos los ítems
FILTRO_EMPRESA = None #"STOX"
FILTRO_ITEM    = None  #"ST_2001143"

# Parámetros en core.ddmrp_parametros (ddmrp_valor_num, solo ddmrp_estado = 1)
ID_UMBRAL_PICO = 13    # Umbral: es_pico = "SI" cuando |Z modificado| > umbral
ID_CONSTANTE_Z = 14    # Z modificado = constante * (cantidad - mediana) / MADX
ID_VF_BAJO  = 7        # VF bajo  (0.2): CV <= LIMITE_VF_BAJO
ID_VF_MEDIO = 8        # VF medio (0.4): LIMITE_VF_BAJO < CV <= LIMITE_VF_MEDIO, y SKUs no medibles
ID_VF_ALTO  = 9        # VF alto  (0.6): CV > LIMITE_VF_MEDIO

LIMITE_VF_BAJO  = 0.5
LIMITE_VF_MEDIO = 1

MESES_VENTANA     = 12  # ADU y CV: últimos 12 meses completos (sin el mes en curso)
MIN_MESES_LIMPIOS = 3   # con menos meses limpios el CV no se puede medir -> VF medio

DECIMALES_Z = 2        # decimales con los que se redondea el Z modificado
DECIMALES_DESV = 2     # decimales con los que se redondea desviacion_estandar

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("vts_mensual_sku")


# ---------------------------------------------------------------------------
# PARÁMETROS (PostgreSQL)
# ---------------------------------------------------------------------------
def leer_parametros():
    ids = (ID_UMBRAL_PICO, ID_CONSTANTE_Z, ID_VF_BAJO, ID_VF_MEDIO, ID_VF_ALTO)
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

    log.info("Parámetros: umbral = %s, constante Z = %s, VF bajo = %s, VF medio = %s, VF alto = %s",
             valores[ID_UMBRAL_PICO], valores[ID_CONSTANTE_Z],
             valores[ID_VF_BAJO], valores[ID_VF_MEDIO], valores[ID_VF_ALTO])
    factores_vf = (valores[ID_VF_BAJO], valores[ID_VF_MEDIO], valores[ID_VF_ALTO])
    return valores[ID_UMBRAL_PICO], valores[ID_CONSTANTE_Z], factores_vf


# ---------------------------------------------------------------------------
# EXTRACCIÓN (PostgreSQL)
# ---------------------------------------------------------------------------
def extraer():
    sql = """
        SELECT
            hev_empresa,
            hev_codigoitem,
            date_trunc('month', hev_fechadocumento)::date AS mes,
            ROUND(SUM(hev_cantidad))::integer             AS cantidad,
            current_date                                  AS fecha_subida
        FROM core.hec_ventas
        WHERE hev_fechadocumento::date >= %s
          AND hev_tipodocumento <> 'PPTO'
    """
    params = [FECHA_DESDE]

    if FILTRO_EMPRESA:
        sql += " AND hev_empresa = %s"
        params.append(FILTRO_EMPRESA)
    if FILTRO_ITEM:
        sql += " AND hev_codigoitem = %s"
        params.append(FILTRO_ITEM)

    sql += """
        GROUP BY hev_empresa, hev_codigoitem, date_trunc('month', hev_fechadocumento)::date
        ORDER BY hev_empresa, hev_codigoitem, mes;
    """

    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        columnas = [d[0] for d in cur.description]
        filas = cur.fetchall()

    log.info("Extraídas %s filas de core.hec_ventas (desde %s)", len(filas), FECHA_DESDE)
    return columnas, filas


# ---------------------------------------------------------------------------
# CÁLCULO por empresa + ítem:
#   desv_mediana = |cantidad - mediana|              (=ABS(C36-MEDX))
#   z_modificado = constante_z * (cantidad - mediana) / MADX  (=0,6745*(C36-MEDX)/MADX)
#   es_pico      = "SI" si |z_modificado| > umbral_pico   (=SI(ABS(E36)>ZTHR;"SI";"NO"))
#   demanda_adu  = cantidad si no es pico, si no 0        (=SI(F36="NO";C36;"0"))
# ---------------------------------------------------------------------------
def agregar_desv_mediana(columnas, filas, umbral_pico, constante_z):
    i_cant = columnas.index("cantidad")

    cantidades = defaultdict(list)
    for f in filas:
        cantidades[(f[0], f[1])].append(f[i_cant])
    medianas = {sku: median(v) for sku, v in cantidades.items()}
    # MADX: mediana de |cantidad - mediana| de cada empresa + ítem
    mads = {sku: median(abs(c - medianas[sku]) for c in v) for sku, v in cantidades.items()}

    columnas = (columnas[:i_cant + 1] + ["desv_mediana", "z_modificado", "es_pico", "demanda_adu"]
                + columnas[i_cant + 1:])
    nuevas = []
    for f in filas:
        sku = (f[0], f[1])
        dif = f[i_cant] - medianas[sku]
        # Z modificado = constante_z * (cantidad - mediana) / MADX; 0 si MADX = 0 (no se puede dividir)
        z = constante_z * dif / mads[sku] if mads[sku] else 0
        # se compara con el Z sin redondear, como en Excel
        es_pico = "SI" if abs(z) > umbral_pico else "NO"
        z_red = round(z, DECIMALES_Z)
        # demanda para ADU: excluye los picos (se ponen en 0)
        demanda_adu = f[i_cant] if es_pico == "NO" else 0
        nuevas.append(f[:i_cant + 1] + (abs(dif), z_red, es_pico, demanda_adu) + f[i_cant + 1:])
    return columnas, nuevas


def sumar_meses(d, n):
    """Primer día del mes que está n meses después (o antes, si n < 0) de d."""
    total = d.year * 12 + d.month - 1 + n
    return date(total // 12, total % 12 + 1, 1)


# ---------------------------------------------------------------------------
# ADU, CV y VF por empresa + ítem (se repiten en todas las filas mensuales del SKU).
# Serie mensual del SKU:
#   - últimos 12 meses completos (sin el mes en curso); si el ítem es nuevo, desde su primer mes
#   - los meses sin venta cuentan como 0
#   - se quitan los picos ALTOS (es_pico = "SI" y cantidad sobre la mediana, z_modificado > 0)
# ADU                 = promedio de la serie / 30  (u/día; 0 si sale negativo)
# desviacion_estandar = CV = stdev(serie) / promedio(serie)  (= desviación estándar / ADU)
# VF = CV * factor del tramo:
#   CV <= 0.5        -> CV * 0.2 (VF bajo)
#   0.5 < CV <= 1    -> CV * 0.4 (VF medio)
#   CV > 1           -> CV * 0.6 (VF alto)
#   no medible (menos de 3 meses limpios o promedio <= 0) -> VF = 0.40, CV = 0
# ---------------------------------------------------------------------------
def agregar_adu_vf(columnas, filas, factores_vf):
    bajo, medio, alto = factores_vf
    i_mes  = columnas.index("mes")
    i_cant = columnas.index("cantidad")
    i_pico = columnas.index("es_pico")
    i_z    = columnas.index("z_modificado")

    mes_actual  = date.today().replace(day=1)          # mes en curso: no entra (incompleto)
    ini_ventana = sumar_meses(mes_actual, -MESES_VENTANA)

    primer_mes = {}
    ventas = defaultdict(dict)                         # sku -> {mes: cantidad, o None si es pico alto}
    for f in filas:
        sku = (f[0], f[1])
        primer_mes[sku] = min(primer_mes.get(sku, f[i_mes]), f[i_mes])
        pico_alto = f[i_pico] == "SI" and f[i_z] > 0
        ventas[sku][f[i_mes]] = None if pico_alto else f[i_cant]

    calculos = {}
    for sku, por_mes in ventas.items():
        serie = []
        mes = max(primer_mes[sku], ini_ventana)
        while mes < mes_actual:
            cantidad = por_mes.get(mes, 0)             # mes sin venta = 0
            if cantidad is not None:                   # None = pico alto, se quita
                serie.append(cantidad)
            mes = sumar_meses(mes, 1)

        promedio = mean(serie) if serie else 0
        adu = max(promedio / 30, 0)
        if len(serie) >= MIN_MESES_LIMPIOS and promedio > 0:
            # CV = desviación estándar / ADU (misma serie; la unidad se cancela)
            cv = stdev(serie) / promedio
            if cv <= LIMITE_VF_BAJO:
                factor = bajo
            elif cv <= LIMITE_VF_MEDIO:
                factor = medio
            else:
                factor = alto
            vf = round(cv * factor, DECIMALES_DESV)    # VF = CV * factor del tramo
        else:
            cv, vf = 0, medio                          # CV no medible -> VF = 0.40
        calculos[sku] = (round(cv, DECIMALES_DESV), vf, round(adu, 2))

    return (columnas + ["desviacion_estandar", "VF", "ADU"],
            [f + calculos[(f[0], f[1])] for f in filas])


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL): crea la tabla si no existe, borra sus registros e inserta
# ---------------------------------------------------------------------------
CREATE = f"""
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} (
    hev_empresa          varchar,
    hev_codigoitem       varchar,
    mes                  date,
    cantidad             integer,
    desv_mediana         numeric,
    z_modificado         numeric,
    es_pico              varchar(2),
    demanda_adu          integer,
    fecha_subida         date,
    desviacion_estandar  numeric,
    "VF"                 numeric,
    "ADU"                numeric
)
"""

# Si la tabla ya existía sin las columnas: CREATE TABLE IF NOT EXISTS no agrega columnas
ALTER = (f"ALTER TABLE {PG_SCHEMA}.{PG_TABLA} "
         f'ADD COLUMN IF NOT EXISTS desviacion_estandar numeric, ADD COLUMN IF NOT EXISTS "VF" numeric, '
         f'ADD COLUMN IF NOT EXISTS "ADU" numeric')


def cargar(columnas, filas):
    # nombres entre comillas: "VF" va en mayúsculas
    nombres = ", ".join('"' + c + '"' for c in columnas)
    insert = f"INSERT INTO {PG_SCHEMA}.{PG_TABLA} ({nombres}) VALUES %s"
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:                      # una sola transacción: si falla, no deja la tabla vacía
            with conn.cursor() as cur:
                cur.execute(CREATE)
                cur.execute(ALTER)
                cur.execute(f"TRUNCATE TABLE {PG_SCHEMA}.{PG_TABLA};")
                if filas:
                    execute_values(cur, insert, filas, page_size=5000)
        log.info("Cargadas %s filas en %s.%s", len(filas), PG_SCHEMA, PG_TABLA)
    finally:
        conn.close()


def ejecutar():
    umbral_pico, constante_z, factores_vf = leer_parametros()
    columnas, filas = agregar_desv_mediana(*extraer(), umbral_pico, constante_z)
    cargar(*agregar_adu_vf(columnas, filas, factores_vf))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al cargar ventas mensuales")
        raise
