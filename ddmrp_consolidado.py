# =============================================================================
# DDMRP LLANTAS CONSOLIDADO  ->  core.ddmrp_llantas_consolidado
#
# Une en una sola tabla el DDMRP normal (master_llantas.py) y el mensualizado (llantas_mes.py),
# con las columnas y el orden del Excel REORDENADO_UNIFICADO.xlsx.
#
# NO tiene fórmulas propias: usa las de master_llantas.py y llantas_mes.py (si se cambia una
# fórmula allá, el consolidado la toma). Pasos:
#   1. Corre una sola vez las tablas resumen (ddmrp_bodega, ddmrp_inventario, ...).
#   2. En tablas temporales calcula los dos modelos con los MISMOS datos:
#        tmp_master  <- SQL_DDMRP + PASOS de master_llantas.py
#        tmp_mes     <- SQL_DDMRP + PASOS de llantas_mes.py
#   3. Crea core.ddmrp_llantas_consolidado tomando cada columna del modelo que corresponde
#      (ver COLUMNAS). No toca core.ddmrp_llantas ni core.ddmrp_llantas_mes.
#
# Todo va en una transacción: si algo falla, core.ddmrp_llantas_consolidado queda como estaba.
# =============================================================================
import logging
import re
import sys
import time

import psycopg2

import llantas_mes as mes          # modelo mensualizado
import master_llantas as master    # modelo normal
from config import POSTGRES

PG_SCHEMA = "core"
PG_TABLA  = "ddmrp_llantas_consolidado"
TABLA     = f"{PG_SCHEMA}.{PG_TABLA}"

TMP_MASTER = "tmp_master"
TMP_MES    = "tmp_mes"

log = logging.getLogger("consolidado")

# -----------------------------------------------------------------------------
# COLUMNAS del consolidado, en orden: (nombre en el consolidado, expresión)
#   m. = modelo mensualizado (llantas_mes.py)     l. = modelo normal (master_llantas.py)
#   Las marcadas "oculta" no están en el Excel unificado: van en la tabla y en el Excel
#   agrupadas/ocultas junto a las relacionadas (el export las oculta).
#   Las columnas que existen en los dos modelos con valores distintos (zonas, TOG/NFP internos
#   del master, STOCK PROYECTADO DLT del master) solo van si el Excel unificado las usa.
# -----------------------------------------------------------------------------
NUMERO = r"'^-?[0-9]+(\.[0-9]+)?$'"


def m(col, alias=None):
    return (alias or col, f'm."{col}"')


def l(col, alias=None, redondear=False):
    expr = f'ROUND(l."{col}"::numeric, 2)' if redondear else f'l."{col}"'
    return (alias or col, expr)


COLUMNAS = [
    m("EMPRESA"),
    m("CODIGO_ITEM"),
    m("CODIGO PROVEEDOR"),
    m("COD. PROV1"),
    m("PROV1"),
    m("COD. PROV2"),
    m("PROV2"),
    m("DESCRIPCION"),
    m("GRUPO"), m("PROPIEDAD"), m("RIN"), m("SERIE"), m("ANCHO"),          # oculta
    m("MARCA"), m("BARRAS"), m("DISEÑO"),                                  # oculta
    m("ANT."),
    m("TOP"),
    m("CLASIF. PARETO"),
    m("ACTIVO"), m("ARTICULO_COMPRA"),                                     # oculta
    m("UN (#) - AÑO"),
    m("PICO ULT. AÑO X FACTURA"),
    m("DIF. MAX AÑO vs TOT. AÑO"),
    m("DIAS INV 1 AÑO"),
    m("DEMANDA MES - AÑO"),
    m("ADU BASE"),
    m("UN (#) - 90D"),
    m("DIAS INV 90D"),
    m("DEMANDA MES 90D"),
    m("ADU 90 DÍAS"),
    m("Ratio de cambio"), m("ADU SIN PICOS"),                              # oculta
    l("ADU", redondear=True),                                              # oculta (ADU del master)
    m("% VARIACIÓN DEMANDA"),
    m("UNIDADES MES ACTUAL"),
    m("EN STOCK"),
    m("# MESES EN STOCK", "# MESES EN STOCK CON MAX ADU"),
    m("TRANSITOS TOTAL"),
    m("TRANSITO 15D"), m("TRANSITO 30D"), m("TRANSITO 45D"), m("TRANSITO >45D"),     # oculta
    m("# MESES EN TRANSITO"),                                                        # oculta
    m("PEDIDOS"),
    m("Pedidos15D"), m("Pedidos30D"), m("Pedidos45D"), m("Pedidos>45D"),             # oculta
    m("# MESES EN PEDIDOS"),                                                         # oculta
    m("BACKORDERS"),
    m("Backorders_15D"), m("Backorders_30D"), m("Backorders>30D"),                   # oculta
    m("# MESES EN BACK ORDERS"),                                                     # oculta
    m("STOCK TOTAL"),
    m("MESES EN STOCK TOTAL", "MESES EN STOCK TOTAL CON MAX ADU"),
    l("MES INV TOTAL SEGUN DEMANDA 90D", redondear=True),                  # oculta
    m("STOCK PROYECTADO DLT", "STOCK PROYECTADO DLT CON MAX ADU"),
    m("MES DE STOCK PROYECT MAX ADU DLT"),
    # VALIDADOR: donde el mensualizado pone un número (días) va 'PEDIR BAJO CALCULO';
    # los textos (PEDIR MESES X CATEGORIA, INFINITO..., REVISAR PARA INACTIVAR) quedan igual
    ("VALIDADOR", f"""CASE WHEN m."VALIDADOR" ~ {NUMERO} THEN 'PEDIR BAJO CALCULO'::varchar
                          ELSE m."VALIDADOR" END"""),
    m("MESES EN PISO X CATEGORIA"),
    m("MESES EN PISO + DLT X CATEGORIA", "MESES EN PISO + DLT X CATEGORIA CON MAX ADU"),
    m("MESES X PEDIR TOTAL"),
    m("DLT"),
    m("LTF"), m("VF"),                                                     # oculta
    m("TAMAÑO BUFFER (TOG)"),
    m("FLUJO NETO (NFP)"),
    m("PEDIDO ESTANDAR DDMRP"),                                            # oculta
    l("TAMAÑO PEDIDO", redondear=True),
    m("FLUJO NETO (NFP) AJUSTADO"),                                        # oculta (como en el Excel)
    m("PEDIDO AJUSTADO DDMRP"),                                            # oculta
    l("NUEVO TAMAÑO PEDIDO", redondear=True),
    l("TAMAÑO 3 MESES INVENTARIO", "TAMAÑO 3 MESES INVT. SEGÚN ADU 90D", redondear=True),
    l("NFP JP", redondear=True),                                           # oculta
    l("PROD SIN VENTAS SIN STOCK"), l("PROD CON STOCK SIN VENTAS"),        # oculta
    l("PEDIDO SUGERIDO JP"),
    m("PEDIDO SUGERIDO AJUSTADO A PISO"),
    m("# DE MESES DEL PEDIDO", "# DE MESES DEL PEDIDO SEGÚN MAX ADU"),
    m("ULTIMO FOB"),
    m("ULTIMA COMPRA"),
    m("COSTO PROM"),
    m("ULT. COSTO"),
    m("P. LISTA"),
    m("P. LISTA VS ULT.COSTO"),
    m("ULTIMA VENTA"),
    m("OBSERVACIONES"),
]


def en_tabla(sql, tabla_original, tabla_nueva):
    """Cambia core.ddmrp_llantas / core.ddmrp_llantas_mes por la tabla temporal en un SQL de los otros scripts."""
    nuevo = re.sub(re.escape(tabla_original) + r"(?!\w)", tabla_nueva, sql)
    if re.search(r"core\.ddmrp_llantas\w*", nuevo):
        raise RuntimeError(f"Quedó una referencia a una tabla real en el SQL: {nuevo[:200]}")
    return nuevo


def calcular_modelo(cur, modulo, tmp):
    """Crea la tabla temporal con SQL_DDMRP del módulo, agrega sus columnas calculadas y corre sus PASOS."""
    cur.execute(f"CREATE TEMP TABLE {tmp} ON COMMIT DROP AS {modulo.SQL_DDMRP}")
    filas = cur.rowcount
    for nombre, tipo in modulo.COLUMNAS_CALCULADAS:
        cur.execute(f'ALTER TABLE {tmp} ADD COLUMN "{nombre}" {tipo}')
    for nombre, sql, *params in modulo.PASOS:
        cur.execute(en_tabla(sql, modulo.TABLA, tmp), *params)
        log.info("[%s] %-40s %s ítems", modulo.__name__, nombre, cur.rowcount)
    return filas


def cargar_consolidado():
    conn = psycopg2.connect(**POSTGRES)
    try:
        with conn:
            with conn.cursor() as cur:
                n_master = calcular_modelo(cur, master, TMP_MASTER)
                n_mes = calcular_modelo(cur, mes, TMP_MES)

                # los dos modelos deben tener exactamente los mismos ítems
                cur.execute(f"""
                    SELECT COUNT(*) FILTER (WHERE l."CODIGO_ITEM" IS NULL),
                           COUNT(*) FILTER (WHERE m."CODIGO_ITEM" IS NULL)
                    FROM {TMP_MES} m
                    FULL JOIN {TMP_MASTER} l ON l."EMPRESA" = m."EMPRESA" AND l."CODIGO_ITEM" = m."CODIGO_ITEM"
                """)
                solo_mes, solo_master = cur.fetchone()
                if n_master != n_mes or solo_mes or solo_master:
                    raise RuntimeError(f"Los modelos no cuadran: master {n_master}, mensualizado {n_mes}, "
                                       f"solo en mensualizado {solo_mes}, solo en master {solo_master}")

                select = ",\n    ".join(f'{expr} AS "{nombre}"' for nombre, expr in COLUMNAS)
                # se crea de nuevo en cada corrida para que el orden de columnas sea siempre el de COLUMNAS
                cur.execute(f"DROP TABLE IF EXISTS {TABLA}")
                cur.execute(f"""
                    CREATE TABLE {TABLA} AS
                    SELECT
                        {select}
                    FROM {TMP_MES} m
                    JOIN {TMP_MASTER} l ON l."EMPRESA" = m."EMPRESA" AND l."CODIGO_ITEM" = m."CODIGO_ITEM"
                """)
                filas = cur.rowcount
        log.info("Cargadas %s filas en %s", filas, TABLA)
    finally:
        conn.close()


def main():
    # 1. tablas resumen (las mismas que corren master_llantas.py y llantas_mes.py), una sola vez
    fallidos = []
    for nombre, ejecutar in master.PROCESOS:
        log.info("=== Inicio %s ===", nombre)
        inicio = time.time()
        try:
            ejecutar()
            log.info("=== Fin %s (%.1f s) ===", nombre, time.time() - inicio)
        except Exception:
            log.exception("=== Error en %s ===", nombre)
            fallidos.append(nombre)

    if fallidos:
        log.error("Terminó con errores en: %s", ", ".join(fallidos))
        log.error("No se actualiza %s porque fallaron procesos previos", TABLA)
        sys.exit(1)

    # 2-3. los dos modelos y la tabla consolidada
    log.info("=== Inicio %s ===", PG_TABLA)
    inicio = time.time()
    try:
        cargar_consolidado()
        log.info("=== Fin %s (%.1f s) ===", PG_TABLA, time.time() - inicio)
    except Exception:
        log.exception("=== Error en %s ===", PG_TABLA)
        sys.exit(1)

    log.info("Todos los procesos terminaron correctamente")


if __name__ == "__main__":
    main()
