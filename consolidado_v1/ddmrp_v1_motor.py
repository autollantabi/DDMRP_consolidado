# =============================================================================
# DDMRP CONSOLIDADO v1 - MOTOR: arma la consulta con las fórmulas de formulas_ddmrp_v1.sql
#
# No hace falta tocar este archivo para cambiar fórmulas (eso es en formulas_ddmrp_v1.sql).
#
# Cómo funciona:
#   1. Lee formulas_ddmrp_v1.sql: cada "-- @PASO" es un paso y cada  fórmula  AS "COLUMNA",  una columna.
#   2. Arma UNA consulta de solo lectura, encadenando los pasos:
#         WITH paso_0 AS (consulta de los datos de origen),
#              paso_1 AS (SELECT <columnas anteriores>, <fórmulas del paso 1> FROM paso_0),
#              paso_2 AS (SELECT ...                                          FROM paso_1), ...
#         SELECT * FROM paso_N
#      Si un paso vuelve a calcular una columna, reemplaza a la anterior.
#   3. Cambia PAR(x) por la fórmula de REDONDEA.PAR (PostgreSQL no la tiene).
# No crea tablas: se puede copiar la consulta y ejecutarla en pgAdmin.
# =============================================================================
import re
from pathlib import Path

PATRON_PASO = re.compile(r"^--\s*@PASO\s*(.*)$")
PATRON_COLUMNA = re.compile(r'\bAS\s+"([^"]+)"\s*,?\s*$', re.IGNORECASE)


class ErrorFormulas(Exception):
    """Error al leer formulas_ddmrp_v1.sql (con el número de línea)."""


def leer_formulas(ruta):
    """Devuelve la lista de pasos: [{"titulo", "descripcion", "formulas": [{"columna", "sql", "descripcion", "linea"}]}]"""
    pasos, paso = [], None
    comentarios, codigo, linea_inicio = [], [], 0
    for n, linea in enumerate(Path(ruta).read_text(encoding="utf-8").splitlines(), start=1):
        limpia = linea.strip()
        m = PATRON_PASO.match(limpia)
        if m:
            if codigo:
                raise ErrorFormulas(f"Línea {linea_inicio}: a la fórmula le falta  AS \"COLUMNA\",  al final")
            paso = {"titulo": m.group(1).strip(), "descripcion": "", "formulas": []}
            pasos.append(paso)
            comentarios = []
            continue
        if paso is None:                                    # encabezado del archivo
            continue
        if limpia.startswith("--") and not codigo:
            texto = limpia.lstrip("-").strip()
            if texto and not set(texto) <= set("=-"):
                comentarios.append(texto)
            continue
        if not limpia:
            if not codigo:
                if comentarios and not paso["formulas"] and not paso["descripcion"]:
                    paso["descripcion"] = " ".join(comentarios)
                comentarios = []
            continue
        if not codigo:
            linea_inicio = n
        codigo.append(linea.rstrip())
        m = PATRON_COLUMNA.search(limpia)
        if m and not limpia.startswith("--"):
            columna = m.group(1)
            codigo[-1] = PATRON_COLUMNA.sub("", codigo[-1].rstrip()).rstrip()
            sql = "\n".join(codigo).strip()
            if not sql:
                raise ErrorFormulas(f"Línea {n}: la columna \"{columna}\" no tiene fórmula")
            if any(f["columna"] == columna for f in paso["formulas"]):
                raise ErrorFormulas(f"Línea {n}: la columna \"{columna}\" está dos veces en el mismo paso")
            paso["formulas"].append({"columna": columna, "sql": _quitar_sangria(sql),
                                     "descripcion": " ".join(comentarios), "linea": linea_inicio,
                                     "paso": paso["titulo"]})
            comentarios, codigo = [], []
    if codigo:
        raise ErrorFormulas(f"Línea {linea_inicio}: a la fórmula le falta  AS \"COLUMNA\",  al final")
    return [p for p in pasos if p["formulas"]]


def _quitar_sangria(sql):
    lineas = sql.splitlines()
    sangria = min((len(l) - len(l.lstrip()) for l in lineas[1:] if l.strip()), default=0)
    return "\n".join([lineas[0].strip()] + [l[sangria:] for l in lineas[1:]])


def _cierre(texto, inicio):
    """Posición del paréntesis que cierra al que está en texto[inicio] (ignora comillas)."""
    nivel, comilla = 0, None
    for i in range(inicio, len(texto)):
        c = texto[i]
        if comilla:
            if c == comilla:
                comilla = None
        elif c in "'\"":
            comilla = c
        elif c == "(":
            nivel += 1
        elif c == ")":
            nivel -= 1
            if nivel == 0:
                return i
    raise ErrorFormulas(f"Falta cerrar un paréntesis en: {texto[inicio:inicio + 80]}...")


def expandir_par(sql):
    """PAR(x) -> REDONDEA.PAR(x): al par siguiente alejándose del cero.
    Se redondea x a 10 decimales antes, para que un resto de la división (36.00000000000000000001)
    no suba el pedido al par siguiente."""
    patron = re.compile(r"(?<![\w.\"])PAR\s*\(", re.IGNORECASE)
    while True:
        m = patron.search(sql)
        if not m:
            return sql
        abre = m.end() - 1
        cierra = _cierre(sql, abre)
        x = expandir_par(sql[abre + 1:cierra])
        par = f"(SIGN(ROUND(({x}), 10)) * CEIL(ABS(ROUND(({x}), 10)) / 2) * 2)"
        sql = sql[:m.start()] + par + sql[cierra + 1:]


def columnas_de(sql_select):
    """Columnas (AS "...") de la consulta de origen, en orden."""
    return re.findall(r'\bAS\s+"([^"]+)"', sql_select, re.IGNORECASE)


def armar_consulta(sql_origen, pasos, orden=('"EMPRESA"', '"CODIGO_ITEM"')):
    """Una sola consulta (solo lectura) con los datos de origen y todos los pasos encadenados."""
    columnas = columnas_de(sql_origen)
    # MATERIALIZED: cada paso se calcula una sola vez (si no, PostgreSQL repite las fórmulas de los pasos
    # anteriores dentro de los siguientes y la consulta tarda mucho más). No crea tablas.
    ctes = ["paso_0 AS MATERIALIZED (   -- datos de origen\n" + sql_origen.strip() + "\n)"]
    for i, paso in enumerate(pasos, start=1):
        nuevas = [f["columna"] for f in paso["formulas"]]
        se_quedan = [c for c in columnas if c not in nuevas]
        lineas = [f'"{c}"' for c in se_quedan]
        for f in paso["formulas"]:
            formula = expandir_par(f["sql"]).replace("\n", "\n        ")
            lineas.append(f'-- {f["columna"]}\n    {formula}\n        AS "{f["columna"]}"')
        ctes.append(f"paso_{i} AS MATERIALIZED (   -- PASO {paso['titulo']}\nSELECT\n    " + ",\n    ".join(lineas)
                    + f"\nFROM paso_{i - 1}\n)")
        columnas = se_quedan + nuevas
    return ("WITH\n" + ",\n".join(ctes) + f"\nSELECT *\nFROM paso_{len(pasos)}\nORDER BY {', '.join(orden)}",
            columnas)
