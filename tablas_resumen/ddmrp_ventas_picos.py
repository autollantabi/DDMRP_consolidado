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
# bodegas de venta por empresa: las mismas que usa ddmrp_inventario.py para los días con stock
from ddmrp_inventario import BODEGAS_POR_EMPRESA

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

# CV: la venta diaria es intermitente (la mayoría de días es 0), así que la variabilidad se mide
# en tramos de ~30 días contados hacia atrás desde hoy (365 / 12 = tramos de 30 y 31 días).
N_TRAMOS           = 12
MIN_TRAMOS_LIMPIOS = 3  # con menos tramos el CV no se puede medir -> VF medio

DIAS_ADU_60D = 60       # ADU60D: misma fórmula que el ADU, pero con los últimos 60 días

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
# EXTRACCIÓN 1 (PostgreSQL): venta POR DÍA por empresa + ítem de los últimos 'dias' días
# Mismos filtros que core.vw_ddmrp_ventas: sin PPTO, solo mayoreo / B2B, sin clientes
# relacionados (un vendedor que no está en dim_vendedores queda fuera, igual que en la vista).
# Una fila por día con movimiento (los días sin venta no tienen fila: cuentan como 0).
# ---------------------------------------------------------------------------
def extraer(dias):
    sql = """
        SELECT
            hv.hev_empresa,
            hv.hev_codigoitem,
            hv.hev_fechadocumento::date               AS fecha,
            ROUND(SUM(hv.hev_cantidad))::integer      AS cantidad,
            current_date                              AS fecha_subida
        FROM core.hec_ventas hv
        JOIN core.dim_vendedores dve
            ON dve.dve_codigo = hv.hev_vendedor_asignado
        WHERE hv.hev_fechadocumento::date >  current_date - %(dias)s
          AND hv.hev_fechadocumento::date <= current_date
          AND hv.hev_tipodocumento <> 'PPTO'
          AND dve.dve_categoria = ANY(%(categorias)s)
          AND hv.hev_cuentasocio NOT LIKE ALL(%(clientes)s)
    """
    params = {"dias": dias,
              "categorias": CATEGORIAS_VENDEDOR,
              "clientes": ["%" + ruc for ruc in CLIENTES_EXCLUIDOS]}   # termina en el RUC

    if FILTRO_EMPRESA:
        sql += " AND hv.hev_empresa = %(empresa)s"
        params["empresa"] = FILTRO_EMPRESA
    if FILTRO_ITEM:
        sql += " AND hv.hev_codigoitem = %(item)s"
        params["item"] = FILTRO_ITEM

    sql += """
        GROUP BY hv.hev_empresa, hv.hev_codigoitem, hv.hev_fechadocumento::date
        ORDER BY hv.hev_empresa, hv.hev_codigoitem, 3;
    """

    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute("SELECT current_date")
        hoy = cur.fetchone()[0]
        cur.execute(sql, params)
        filas = cur.fetchall()

    columnas = ["hev_empresa", "hev_codigoitem", "fecha", "cantidad", "fecha_subida"]
    log.info("Extraídas %s filas (ítem + día) de core.hec_ventas (últimos %s días hasta %s)",
             len(filas), dias, hoy)
    return columnas, filas, hoy


# ---------------------------------------------------------------------------
# EXTRACCIÓN 2 (PostgreSQL): días CON inventario por empresa + ítem (core.hec_inventario, misma
# ventana). Un día cuenta si el ítem tuvo stock > 0 en al menos una bodega de venta (misma regla
# que ddmrp_inventario.py). inv_id viene con prefijo (AU_2000487), igual que hev_codigoitem.
# Devuelve {(empresa, ítem): set(fechas con inventario)}
# ---------------------------------------------------------------------------
def extraer_dias_stock(dias):
    bodegas = tuple((empresa, codigo) for empresa, codigos in BODEGAS_POR_EMPRESA.items()
                    for codigo in codigos)
    sql = """
        SELECT inv_empresa, inv_id, array_agg(DISTINCT inv_fecha_subida::date)
        FROM core.hec_inventario
        WHERE inv_fecha_subida::date >  current_date - %(dias)s
          AND inv_fecha_subida::date <= current_date
          AND inv_stock > 0
          AND (inv_empresa, inv_codigo_bodega) IN %(bodegas)s
    """
    params = {"dias": dias, "bodegas": bodegas}
    if FILTRO_EMPRESA:
        sql += " AND inv_empresa = %(empresa)s"
        params["empresa"] = FILTRO_EMPRESA
    if FILTRO_ITEM:
        sql += " AND inv_id = %(item)s"
        params["item"] = FILTRO_ITEM
    sql += " GROUP BY 1, 2"

    with psycopg2.connect(**POSTGRES) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        stock = {(e, i): set(fechas) for e, i, fechas in cur.fetchall()}

    log.info("Días con inventario leídos de core.hec_inventario: %s ítems", len(stock))
    return stock


# ---------------------------------------------------------------------------
# PICOS POR DÍA, por empresa + ítem (cada fila es un día con venta):
#   desv_mediana = |cantidad - mediana|              (=ABS(C36-MEDX))
#   z_modificado = constante_z * (cantidad - mediana) / MADX  (=0,6745*(C36-MEDX)/MADX)
#   es_pico      = "SI" si |z_modificado| > umbral_pico   (=SI(ABS(E36)>ZTHR;"SI";"NO"))
#   demanda_adu  = cantidad si no es pico, si no 0        (=SI(F36="NO";C36;"0"))
#   La mediana y el MAD son los de los días con venta del ítem.
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
# ADU, ADU60D, CV y VF por empresa + ítem (se repiten en todas las filas del SKU).
# Días pico = días con pico ALTO (es_pico = "SI" y cantidad sobre la mediana, z_modificado > 0).
#
# ADU = (ventas - ventas de los días pico) / (días del año - días pico - días sin inventario)
#       días sin inventario: sin stock > 0 en ninguna bodega de venta (core.hec_inventario);
#       un día que es pico y además sin inventario se descuenta una sola vez.
#       Si el ítem vendió pero no tiene ningún día con inventario registrado, se divide entre los
#       días calendario desde su primera venta, sin los días pico.  (u/día; 0 si sale negativo)
# ADU60D = misma fórmula con los últimos 60 días.
#
# CV (desviacion_estandar) y VF: en N_TRAMOS tramos de ~30 días desde el tramo de la primera venta;
#   venta diaria del tramo = venta del tramo sin días pico / días del tramo sin días pico.
#   CV = stdev / promedio de esas ventas diarias.
#   VF = CV * factor: CV <= 0.5 -> 0.2 | 0.5 < CV <= 1 -> 0.4 | CV > 1 -> 0.6
#   no medible (menos de 3 tramos o promedio <= 0) -> VF = 0.40, CV = 0
# ---------------------------------------------------------------------------
def agregar_adu_vf(columnas, filas, hoy, dias, stock, factores_vf):
    bajo, medio, alto = factores_vf
    i_fecha = columnas.index("fecha")
    i_cant  = columnas.index("cantidad")
    i_pico  = columnas.index("es_pico")
    i_z     = columnas.index("z_modificado")

    ventas = defaultdict(dict)                          # sku -> {días atrás: (cantidad, pico alto)}
    for f in filas:
        d = (hoy - f[i_fecha]).days                     # 0 = hoy, dias - 1 = el más antiguo
        ventas[(f[0], f[1])][d] = (f[i_cant], f[i_pico] == "SI" and f[i_z] > 0)

    calculos = {}
    sin_inventario = 0
    for sku, por_dia in ventas.items():
        con_stock = {(hoy - fecha).days for fecha in stock.get(sku, ())}
        pico = {d for d, (_, es) in por_dia.items() if es}
        primer_dia = max(por_dia)                       # días atrás de la primera venta en la ventana

        def adu_ventana(n_dias):
            """(ventas - ventas pico) / (n_dias - días pico - días sin inventario) en los últimos n_dias."""
            venta = sum(c for d, (c, es) in por_dia.items() if d < n_dias and not es)
            validos = sum(1 for d in range(n_dias) if d not in pico and d in con_stock)
            if validos:
                return max(venta / validos, 0), True
            # sin inventario registrado: días calendario desde la primera venta, sin días pico
            calendario = sum(1 for d in range(min(n_dias, primer_dia + 1)) if d not in pico)
            return (max(venta / calendario, 0) if calendario else 0), False

        adu, con_inv = adu_ventana(dias)
        sin_inventario += not con_inv
        adu_60d, _ = adu_ventana(DIAS_ADU_60D)

        # CV en tramos de ~30 días, desde el tramo de la primera venta, sin los días pico
        tramo_primero = primer_dia * N_TRAMOS // dias
        diarias = []
        for t in range(tramo_primero + 1):
            dias_t = [d for d in range(dias) if d * N_TRAMOS // dias == t and d not in pico]
            if dias_t:
                diarias.append(sum(por_dia[d][0] for d in dias_t if d in por_dia) / len(dias_t))
        promedio = mean(diarias) if diarias else 0
        if len(diarias) >= MIN_TRAMOS_LIMPIOS and promedio > 0:
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

        calculos[sku] = (con_stock, round(cv, DECIMALES_DESV), vf, round(adu, 2), round(adu_60d, 2))

    if sin_inventario:
        log.info("ADU: %s ítems con venta sin ningún día con inventario -> divididos entre días calendario",
                 sin_inventario)

    nuevas = []
    for f in filas:
        con_stock, cv, vf, adu, adu_60d = calculos[(f[0], f[1])]
        hay_stock = "SI" if (hoy - f[i_fecha]).days in con_stock else "NO"
        nuevas.append(f + (hay_stock, cv, vf, adu, adu_60d))
    return columnas + ["con_stock", "desviacion_estandar", "VF", "ADU", "ADU60D"], nuevas


# ---------------------------------------------------------------------------
# CARGA (PostgreSQL): crea la tabla si no existe, borra sus registros e inserta
# Una fila por empresa + ítem + día con venta.
# ---------------------------------------------------------------------------
CREATE = f"""
CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.{PG_TABLA} (
    hev_empresa          varchar,
    hev_codigoitem       varchar,
    fecha                date,
    cantidad             integer,
    desv_mediana         numeric,
    z_modificado         numeric,
    es_pico              varchar(2),
    demanda_adu          integer,
    fecha_subida         date,
    con_stock            varchar(2),
    desviacion_estandar  numeric,
    "VF"                 numeric,
    "ADU"                numeric,
    "ADU60D"             numeric
)
"""

# Si la tabla ya existía con la estructura anterior (por tramo, columna 'mes'): CREATE TABLE IF
# NOT EXISTS no la cambia; se agregan las columnas nuevas y se quitan las que ya no se usan.
ALTER = (f"ALTER TABLE {PG_SCHEMA}.{PG_TABLA} "
         f'ADD COLUMN IF NOT EXISTS fecha date, ADD COLUMN IF NOT EXISTS con_stock varchar(2), '
         f'ADD COLUMN IF NOT EXISTS desviacion_estandar numeric, ADD COLUMN IF NOT EXISTS "VF" numeric, '
         f'ADD COLUMN IF NOT EXISTS "ADU" numeric, ADD COLUMN IF NOT EXISTS "ADU60D" numeric, '
         f'DROP COLUMN IF EXISTS mes, DROP COLUMN IF EXISTS "ADU_90"')


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
    columnas, filas, hoy = extraer(dias)
    stock = extraer_dias_stock(dias)
    columnas, filas = agregar_desv_mediana(columnas, filas, umbral_pico, constante_z)
    cargar(*agregar_adu_vf(columnas, filas, hoy, dias, stock, factores_vf))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        ejecutar()
    except Exception:
        log.exception("Error al cargar ventas diarias")
        raise
