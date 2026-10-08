import logging
import sys
from collections import defaultdict
from datetime import timedelta
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

# Filtros opcionales: pon None para traer todas las empresas / todos los ítems
FILTRO_EMPRESA = None #"STOX"
FILTRO_ITEM    = None  #"ST_2001143"

# Ventas que cuentan para el ADU: los mismos filtros que la vista core.vw_ddmrp_ventas
#   - sin PPTO
#   - solo vendedores (dim_vendedores.dve_categoria) de mayoreo y B2B
#   - sin los clientes relacionados (hev_cuentasocio termina en estos RUC)
CATEGORIAS_VENDEDOR = ["EQUIPO DE MAYOREO", "EQUIPO B2B"]
CLIENTES_EXCLUIDOS  = ["0190085929001", "0195092982001", "0190350533001", "0195116598001"]

# Parámetros en core.ddmrp_parametros (ddmrp_valor_num, solo ddmrp_estado = 1)
ID_DIAS_ADU    = 1     # Ventas 1 anio (365): días hacia atrás desde hoy para ADU, picos y CV
ID_VF_BAJO     = 7     # VF bajo  (0.2): CV <= LIMITE_VF_BAJO
ID_VF_MEDIO    = 8     # VF medio (0.4): LIMITE_VF_BAJO < CV <= LIMITE_VF_MEDIO, y SKUs no medibles
ID_VF_ALTO     = 9     # VF alto  (0.6): CV > LIMITE_VF_MEDIO
ID_UMBRAL_PICO = 13    # Umbral: es_pico = "SI" cuando |Z modificado| > umbral
ID_CONSTANTE_Z = 14    # Z modificado = constante * (cantidad - mediana) / MADX

LIMITE_VF_BAJO  = 0.5
LIMITE_VF_MEDIO = 1

# La ventana de días se parte en tramos de ~30 días contados hacia atrás desde hoy
# (365 / 12 = 30,42 -> tramos de 30 y 31 días que cubren los 365 días exactos).
# Cada tramo hace de "mes" para detectar picos y medir el CV.
N_TRAMOS           = 12
MIN_TRAMOS_LIMPIOS = 3  # con menos tramos limpios el CV no se puede medir -> VF medio

DIAS_ADU_60D = 60       # ADU60D: misma regla que el ADU, pero con los últimos 60 días

DECIMALES_Z = 2        # decimales con los que se redondea el Z modificado
DECIMALES_DESV = 2     # decimales con los que se redondea desviacion_estandar

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("vts_mensual_sku")


# ---------------------------------------------------------------------------
# PARÁMETROS (PostgreSQL)
# ---------------------------------------------------------------------------
def leer_parametros():
    ids = (ID_DIAS_ADU, ID_VF_BAJO, ID_VF_MEDIO, ID_VF_ALTO, ID_UMBRAL_PICO, ID_CONSTANTE_Z)
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

    log.info("Parámetros: días ADU = %s, umbral = %s, constante Z = %s, VF bajo = %s, VF medio = %s, VF alto = %s",
             valores[ID_DIAS_ADU], valores[ID_UMBRAL_PICO], valores[ID_CONSTANTE_Z],
             valores[ID_VF_BAJO], valores[ID_VF_MEDIO], valores[ID_VF_ALTO])
    factores_vf = (valores[ID_VF_BAJO], valores[ID_VF_MEDIO], valores[ID_VF_ALTO])
    return int(valores[ID_DIAS_ADU]), valores[ID_UMBRAL_PICO], valores[ID_CONSTANTE_Z], factores_vf


# ---------------------------------------------------------------------------
# TRAMOS: la ventana de 'dias' días (hoy incluido) partida en N_TRAMOS tramos.
#   días atrás d (0 = hoy, dias - 1 = el más antiguo) -> tramo = d * N_TRAMOS // dias
#   tramo 0 = el más reciente (termina hoy), tramo N_TRAMOS - 1 = el más antiguo
# Devuelve {tramo: (fecha inicio, número de días)}
# ---------------------------------------------------------------------------
def armar_tramos(hoy, dias):
    tramos = {}
    for d in range(dias):
        t = d * N_TRAMOS // dias
        _, n = tramos.get(t, (None, 0))
        tramos[t] = (hoy - timedelta(days=d), n + 1)     # el último d del tramo es su fecha inicio
    return tramos


# ---------------------------------------------------------------------------
# EXTRACCIÓN (PostgreSQL): venta por empresa + ítem + tramo de los últimos 'dias' días
# Mismos filtros que core.vw_ddmrp_ventas: sin PPTO, solo mayoreo / B2B, sin clientes
# relacionados (un vendedor que no está en dim_vendedores queda fuera, igual que en la vista).
# La columna 'mes' guarda la fecha de inicio del tramo.
# ---------------------------------------------------------------------------
def extraer(dias):
    sql = """
        SELECT
            hv.hev_empresa,
            hv.hev_codigoitem,
            (current_date - hv.hev_fechadocumento::date) * %(n)s / %(dias)s AS tramo,
            ROUND(SUM(hv.hev_cantidad))::integer                            AS cantidad,
            current_date                                                    AS fecha_subida,
            -- parte de la venta del tramo que cae en los últimos DIAS_ADU_60D días (para el ADU60D)
            ROUND(COALESCE(SUM(hv.hev_cantidad) FILTER (
                WHERE hv.hev_fechadocumento::date > current_date - %(dias60)s), 0))::integer AS cantidad_60d
        FROM core.hec_ventas hv
        JOIN core.dim_vendedores dve
            ON dve.dve_codigo = hv.hev_vendedor_asignado
        WHERE hv.hev_fechadocumento::date >  current_date - %(dias)s
          AND hv.hev_fechadocumento::date <= current_date
          AND hv.hev_tipodocumento <> 'PPTO'
          AND dve.dve_categoria = ANY(%(categorias)s)
          AND hv.hev_cuentasocio NOT LIKE ALL(%(clientes)s)
    """
    params = {"n": N_TRAMOS, "dias": dias, "dias60": DIAS_ADU_60D,
              "categorias": CATEGORIAS_VENDEDOR,
              "clientes": ["%" + ruc for ruc in CLIENTES_EXCLUIDOS]}   # termina en el RUC

    if FILTRO_EMPRESA:
        sql += " AND hv.hev_empresa = %(empresa)s"
        params["empresa"] = FILTRO_EMPRESA
    if FILTRO_ITEM:
        sql += " AND hv.hev_codigoitem = %(item)s"
        params["item"] = FILTRO_ITEM

    sql += """
        GROUP BY hv.hev_empresa, hv.hev_codigoitem, 3
        ORDER BY hv.hev_empresa, hv.hev_codigoitem, 3 DESC;
    """

    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute("SELECT current_date")
        hoy = cur.fetchone()[0]
        cur.execute(sql, params)
        datos = cur.fetchall()

    tramos = armar_tramos(hoy, dias)
    # tramo -> fecha de inicio del tramo (columna 'mes')
    columnas = ["hev_empresa", "hev_codigoitem", "mes", "cantidad", "fecha_subida"]
    filas = [(emp, item, tramos[t][0], cant, fsub) for emp, item, t, cant, fsub, _ in datos]
    # ADU60D: venta de los últimos 60 días por empresa + ítem + tramo
    venta_60d = {(emp, item, t): c60 for emp, item, t, _, _, c60 in datos}

    log.info("Extraídas %s filas de core.hec_ventas (últimos %s días hasta %s, %s tramos)",
             len(filas), dias, hoy, N_TRAMOS)
    return columnas, filas, tramos, venta_60d


# ---------------------------------------------------------------------------
# CÁLCULO por empresa + ítem (cada fila es un tramo):
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


# ---------------------------------------------------------------------------
# ADU, CV y VF por empresa + ítem (se repiten en todas las filas del SKU).
# Serie del SKU: tramos desde el más reciente (termina hoy) hasta el más antiguo con venta
#   (si el ítem es nuevo, empieza en el tramo de su primera venta)
#   - los tramos sin venta cuentan como 0
#   - se quitan los picos ALTOS (es_pico = "SI" y cantidad sobre la mediana, z_modificado > 0):
#     se quitan su venta Y sus días
# ADU                 = venta de la serie / días de la serie   (u/día; 0 si sale negativo)
#                       sin picos: dias = 365; con picos altos: 365 - días de esos tramos
# desviacion_estandar = CV = stdev(venta diaria por tramo) / promedio(venta diaria por tramo)
#                       (venta diaria del tramo = cantidad / días del tramo; tramos de 30 y 31 días)
# VF = CV * factor del tramo de CV:
#   CV <= 0.5        -> CV * 0.2 (VF bajo)
#   0.5 < CV <= 1    -> CV * 0.4 (VF medio)
#   CV > 1           -> CV * 0.6 (VF alto)
#   no medible (menos de 3 tramos limpios o promedio <= 0) -> VF = 0.40, CV = 0
# ADU60D              = misma regla que el ADU, pero solo con los últimos 60 días:
#                       venta de esos 60 días fuera de tramos con pico alto
#                       / días de esos 60 que caen en tramos sin pico alto
#                       (los 60 días caen en los tramos 0 y 1; si el ítem es nuevo, desde su primer tramo)
# ---------------------------------------------------------------------------
def agregar_adu_vf(columnas, filas, tramos, venta_60d, factores_vf):
    bajo, medio, alto = factores_vf
    i_mes  = columnas.index("mes")
    i_cant = columnas.index("cantidad")
    i_pico = columnas.index("es_pico")
    i_z    = columnas.index("z_modificado")

    tramo_de = {inicio: t for t, (inicio, _) in tramos.items()}   # fecha inicio -> tramo
    dias_ventana = sum(n for _, n in tramos.values())
    # días de cada tramo que caen dentro de los últimos 60 días (d = 0 es hoy)
    dias_60d = defaultdict(int)
    for d in range(DIAS_ADU_60D):
        dias_60d[d * N_TRAMOS // dias_ventana] += 1

    tramo_mas_antiguo = {}
    ventas = defaultdict(dict)                         # sku -> {tramo: cantidad, o None si es pico alto}
    for f in filas:
        sku = (f[0], f[1])
        t = tramo_de[f[i_mes]]
        tramo_mas_antiguo[sku] = max(tramo_mas_antiguo.get(sku, t), t)
        pico_alto = f[i_pico] == "SI" and f[i_z] > 0
        ventas[sku][t] = None if pico_alto else f[i_cant]

    calculos = {}
    for sku, por_tramo in ventas.items():
        # serie: (cantidad, días) de cada tramo limpio, desde el tramo 0 hasta el más antiguo con venta
        serie = []
        for t in range(tramo_mas_antiguo[sku] + 1):
            cantidad = por_tramo.get(t, 0)             # tramo sin venta = 0
            if cantidad is not None:                   # None = pico alto: se quitan venta y días
                serie.append((cantidad, tramos[t][1]))

        total_cant = sum(c for c, _ in serie)
        total_dias = sum(d for _, d in serie)
        adu = max(total_cant / total_dias, 0) if total_dias else 0

        diarias = [c / d for c, d in serie]            # venta diaria de cada tramo
        promedio = mean(diarias) if diarias else 0
        if len(diarias) >= MIN_TRAMOS_LIMPIOS and promedio > 0:
            # CV = desviación estándar / promedio (misma serie; la unidad se cancela)
            cv = stdev(diarias) / promedio
            if cv <= LIMITE_VF_BAJO:
                factor = bajo
            elif cv <= LIMITE_VF_MEDIO:
                factor = medio
            else:
                factor = alto
            vf = round(cv * factor, DECIMALES_DESV)    # VF = CV * factor del tramo
        else:
            cv, vf = 0, medio                          # CV no medible -> VF = 0.40

        # ADU60D: tramos que tocan los últimos 60 días, sin los de pico alto (venta y días)
        cant_60 = dias_60 = 0
        for t, n in dias_60d.items():
            if t <= tramo_mas_antiguo[sku] and por_tramo.get(t, 0) is not None:
                cant_60 += venta_60d.get((sku[0], sku[1], t), 0)
                dias_60 += n
        adu_60d = max(cant_60 / dias_60, 0) if dias_60 else 0

        calculos[sku] = (round(cv, DECIMALES_DESV), vf, round(adu, 2), round(adu_60d, 2))

    return (columnas + ["desviacion_estandar", "VF", "ADU", "ADU60D"],
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
    "ADU"                numeric,
    "ADU60D"             numeric
)
"""

# Si la tabla ya existía sin las columnas: CREATE TABLE IF NOT EXISTS no agrega columnas.
# El ADU_90 ya no se usa: se borra la columna si existe.
ALTER = (f"ALTER TABLE {PG_SCHEMA}.{PG_TABLA} "
         f'ADD COLUMN IF NOT EXISTS desviacion_estandar numeric, ADD COLUMN IF NOT EXISTS "VF" numeric, '
         f'ADD COLUMN IF NOT EXISTS "ADU" numeric, ADD COLUMN IF NOT EXISTS "ADU60D" numeric, '
         f'DROP COLUMN IF EXISTS "ADU_90"')


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
    dias, umbral_pico, constante_z, factores_vf = leer_parametros()
    columnas, filas, tramos, venta_60d = extraer(dias)
    columnas, filas = agregar_desv_mediana(columnas, filas, umbral_pico, constante_z)
    cargar(*agregar_adu_vf(columnas, filas, tramos, venta_60d, factores_vf))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al cargar ventas mensuales")
        raise
