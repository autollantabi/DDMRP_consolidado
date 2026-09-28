import logging
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

import psycopg2
from psycopg2.extras import execute_values

# config.py está en DDMRP/conection
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "conection"))
from config import POSTGRES

# ---------------------------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------------------------
PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_proveedores"

# Filtros opcionales: pon None para traer todas las empresas / todos los proveedores
FILTRO_EMPRESA   = None #"AUTOLLANTA"
FILTRO_PROVEEDOR = None #"P5555555555001"

# Parámetros en core.ddmrp_parametros (ddmrp_valor_num, solo ddmrp_estado = 1)
ID_UMBRAL_PICO = 13    # Umbral: es_pico = "SI" cuando |Z modificado| > umbral
ID_CONSTANTE_Z = 14    # Z modificado = constante * (leadtime - mediana) / MADX
ID_DIAS_DATOS  = 15    # Días toma datos: hfr_fechadocumento < current_date - días
ID_DIAS_CONFIRMACION = 10   # Dias Confirmacion Pedido                     (DLT)
ID_DIAS_DESADUANIZ   = 11   # Dias Desaduanizacion y Recepcion Bodega      (DLT)
ID_DIAS_BOOKING      = 12   # Dias Cordinacion Booking                     (DLT)
ID_LTF_BAJO  = 4       # LTF bajo  (0.2): DLT <= LIMITE_LTF_BAJO
ID_LTF_MEDIO = 5       # LTF medio (0.4): LIMITE_LTF_BAJO < DLT <= LIMITE_LTF_MEDIO
ID_LTF_ALTO  = 6       # LTF alto  (0.6): DLT > LIMITE_LTF_MEDIO

LIMITE_LTF_BAJO  = 60  # días
LIMITE_LTF_MEDIO = 100 # días

DECIMALES_Z = 2        # decimales con los que se redondea el Z modificado

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("proveedores")


# ---------------------------------------------------------------------------
# PARÁMETROS (PostgreSQL)
# ---------------------------------------------------------------------------
def leer_parametros():
    ids = (ID_UMBRAL_PICO, ID_CONSTANTE_Z, ID_DIAS_DATOS,
           ID_DIAS_CONFIRMACION, ID_DIAS_DESADUANIZ, ID_DIAS_BOOKING,
           ID_LTF_BAJO, ID_LTF_MEDIO, ID_LTF_ALTO)
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

    log.info("Parámetros: umbral = %s, constante Z = %s, días toma datos = %s, "
             "días confirmación = %s, días booking = %s, días desaduanización = %s",
             valores[ID_UMBRAL_PICO], valores[ID_CONSTANTE_Z], valores[ID_DIAS_DATOS],
             valores[ID_DIAS_CONFIRMACION], valores[ID_DIAS_BOOKING], valores[ID_DIAS_DESADUANIZ])
    log.info("Parámetros LTF: bajo = %s, medio = %s, alto = %s",
             valores[ID_LTF_BAJO], valores[ID_LTF_MEDIO], valores[ID_LTF_ALTO])
    # días fijos que se suman al DLT
    dias_fijos_dlt = (valores[ID_DIAS_CONFIRMACION] + valores[ID_DIAS_BOOKING]
                      + valores[ID_DIAS_DESADUANIZ])
    factores_ltf = (valores[ID_LTF_BAJO], valores[ID_LTF_MEDIO], valores[ID_LTF_ALTO])
    return (valores[ID_UMBRAL_PICO], valores[ID_CONSTANTE_Z], int(valores[ID_DIAS_DATOS]),
            dias_fijos_dlt, factores_ltf)


# ---------------------------------------------------------------------------
# EXTRACCIÓN (PostgreSQL)
# ---------------------------------------------------------------------------
def extraer(dias_datos):
    sql = """
        SELECT
            hfr.hfr_empresa           AS empresa,
            imp.heim_codigoproveedor  AS cod_proveedor,
            imp.heim_proveedor        AS nombre_proveedor,
            ped.hpe_numeropi,
            imp.heim_agente_forwarder,
            ROUND(AVG(imp.heim_eta_real::date - imp.heim_etd_real::date), 0)           AS leadtime_promedio_etd_eta,
            ROUND(AVG(ped.hpe_fechanecesaria::date - hfr.hfr_fechadocumento::date), 0) AS leadtime_promedio,
            COUNT(*)                  AS total_registros
        FROM core.hec_facturas_reserva hfr
        INNER JOIN core.hec_importaciones imp
            ON hfr.hfr_numeropi = imp.heim_num_pi
        LEFT JOIN core.hec_pedidos ped
            ON hfr.hfr_numeropi = ped.hpe_numeropi
        WHERE hfr.hfr_fechadocumento < CURRENT_DATE - make_interval(days => %s)
    """
    params = [dias_datos]

    if FILTRO_EMPRESA:
        sql += " AND hfr.hfr_empresa = %s"
        params.append(FILTRO_EMPRESA)
    if FILTRO_PROVEEDOR:
        sql += " AND imp.heim_codigoproveedor = %s"
        params.append(FILTRO_PROVEEDOR)

    sql += """
        GROUP BY
            hfr.hfr_empresa,
            imp.heim_codigoproveedor,
            imp.heim_proveedor,
            ped.hpe_numeropi,
            imp.heim_agente_forwarder
        ORDER BY hfr.hfr_empresa, imp.heim_codigoproveedor, ped.hpe_numeropi;
    """

    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        columnas = [d[0] for d in cur.description]
        # ROUND(..., 0) llega como Decimal: se pasa a int para operar con la constante Z (float)
        i_lts = [columnas.index(c) for c in COLUMNAS_LEADTIME]
        filas = [tuple(int(v) if i in i_lts and v is not None else v for i, v in enumerate(f))
                 for f in cur.fetchall()]

    log.info("Extraídas %s filas (hfr_fechadocumento < hoy - %s días)", len(filas), dias_datos)
    return columnas, filas


# ---------------------------------------------------------------------------
# CÁLCULO por empresa + proveedor (cada fila es un pedido), para cada lead time:
#   desv_mediana = |leadtime - mediana|              (=ABS(C36-MEDX))
#   z_modificado = constante_z * (leadtime - mediana) / MADX  (=0,6745*(C36-MEDX)/MADX)
#   es_pico      = "SI" si |z_modificado| > umbral_pico   (=SI(ABS(E36)>ZTHR;"SI";"NO"))
#   leadtime_adu = leadtime si no es pico, si no 0        (=SI(F36="NO";C36;"0"))
# Las filas con leadtime NULL (pedido sin match en hec_pedidos) se muestran sin cálculo.
# Columnas nuevas: las de leadtime_promedio sin sufijo, las de ETD-ETA con "_etd_eta".
# ---------------------------------------------------------------------------
COLUMNAS_LEADTIME = {
    "leadtime_promedio_etd_eta": "_etd_eta",
    "leadtime_promedio":         "",
}


def agregar_desv_mediana(columnas, filas, umbral_pico, constante_z):
    for col, sufijo in COLUMNAS_LEADTIME.items():
        columnas, filas = agregar_calculo(columnas, filas, col, sufijo, umbral_pico, constante_z)
    return columnas, filas


def agregar_calculo(columnas, filas, col, sufijo, umbral_pico, constante_z):
    i_lt = columnas.index(col)

    leadtimes = defaultdict(list)
    for f in filas:
        if f[i_lt] is not None:
            leadtimes[(f[0], f[1])].append(f[i_lt])
    medianas = {prov: median(v) for prov, v in leadtimes.items()}
    # MADX: mediana de |leadtime - mediana| de cada empresa + proveedor
    mads = {prov: median(abs(x - medianas[prov]) for x in v) for prov, v in leadtimes.items()}

    nombres = [n + sufijo for n in ("desv_mediana", "z_modificado", "es_pico", "leadtime_adu")]
    columnas = columnas[:i_lt + 1] + nombres + columnas[i_lt + 1:]
    nuevas = []
    for f in filas:
        if f[i_lt] is None:
            nuevas.append(f[:i_lt + 1] + (None, None, None, None) + f[i_lt + 1:])
            continue
        prov = (f[0], f[1])
        dif = f[i_lt] - medianas[prov]
        # Z modificado = constante_z * (leadtime - mediana) / MADX; 0 si MADX = 0 (no se puede dividir)
        z = constante_z * dif / mads[prov] if mads[prov] else 0
        # se compara con el Z sin redondear, como en Excel
        es_pico = "SI" if abs(z) > umbral_pico else "NO"
        z_red = round(z, DECIMALES_Z)
        # leadtime para ADU: excluye los picos (se ponen en 0)
        leadtime_adu = f[i_lt] if es_pico == "NO" else 0
        nuevas.append(f[:i_lt + 1] + (abs(dif), z_red, es_pico, leadtime_adu) + f[i_lt + 1:])
    return columnas, nuevas


# ---------------------------------------------------------------------------
# DLT = días confirmación pedido + lead time producción (leadtime_adu)
#     + días coordinación booking + lead time puerto -> GYE (leadtime_adu_etd_eta)
#     + días desaduanización y recepción en bodega
# Un lead time vacío (NULL) se cuenta como 0.
# ---------------------------------------------------------------------------
def agregar_dlt(columnas, filas, dias_fijos_dlt):
    i_prod = columnas.index("leadtime_adu")
    i_etd  = columnas.index("leadtime_adu_etd_eta")
    nuevas = [f + (dias_fijos_dlt + (f[i_prod] or 0) + (f[i_etd] or 0),) for f in filas]
    return columnas + ["dlt"], nuevas


# ---------------------------------------------------------------------------
# LTF por fila (pedido) según su DLT:
#   DLT <= 60        -> DLT * LTF bajo  (0.2)
#   60 < DLT <= 100  -> DLT * LTF medio (0.4)
#   DLT > 100        -> DLT * LTF alto  (0.6)
# ---------------------------------------------------------------------------
def agregar_ltf(columnas, filas, factores_ltf):
    bajo, medio, alto = factores_ltf
    i_dlt = columnas.index("dlt")
    nuevas = []
    for f in filas:
        dlt = f[i_dlt]
        if dlt <= LIMITE_LTF_BAJO:
            factor = bajo
        elif dlt <= LIMITE_LTF_MEDIO:
            factor = medio
        else:
            factor = alto
        nuevas.append(f + (round(dlt * factor, 2),))
    return columnas + ["ltf"], nuevas


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL): crea la tabla si no existe, borra sus registros e inserta
# ---------------------------------------------------------------------------
COLUMNAS_TABLA = """
    empresa                    varchar,
    cod_proveedor              varchar,
    nombre_proveedor           varchar,
    hpe_numeropi               varchar,
    heim_agente_forwarder      varchar,
    leadtime_promedio_etd_eta  integer,
    desv_mediana_etd_eta       numeric,
    z_modificado_etd_eta       numeric,
    es_pico_etd_eta            varchar(2),
    leadtime_adu_etd_eta       integer,
    leadtime_promedio          integer,
    desv_mediana               numeric,
    z_modificado               numeric,
    es_pico                    varchar(2),
    leadtime_adu               integer,
    total_registros            integer,
    dlt                        numeric,
    ltf                        numeric
"""

CREATE = f"CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} ({COLUMNAS_TABLA})"

# Si la tabla ya existía con menos columnas, agrega las que falten (no borra la tabla)
ALTER = f"ALTER TABLE {PG_SCHEMA}.{PG_TABLA} " + ", ".join(
    f"ADD COLUMN IF NOT EXISTS {c.strip()}" for c in COLUMNAS_TABLA.strip().split(",\n"))


def cargar(columnas, filas):
    insert = f"INSERT INTO {PG_SCHEMA}.{PG_TABLA} ({', '.join(columnas)}) VALUES %s"
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
    umbral_pico, constante_z, dias_datos, dias_fijos_dlt, factores_ltf = leer_parametros()
    columnas, filas = agregar_desv_mediana(*extraer(dias_datos), umbral_pico, constante_z)
    columnas, filas = agregar_dlt(columnas, filas, dias_fijos_dlt)
    cargar(*agregar_ltf(columnas, filas, factores_ltf))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al cargar lead time por proveedor")
        raise
