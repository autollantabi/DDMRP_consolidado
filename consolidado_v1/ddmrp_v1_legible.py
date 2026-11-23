# =============================================================================
# DDMRP CONSOLIDADO v1 - FÓRMULAS LEGIBLES (solo para MOSTRAR, no calcula nada)
#
# Convierte cada fórmula de formulas_ddmrp_v1.sql a una fórmula al estilo Excel, para la pestaña
# Cálculos de la ventana. El cálculo real sigue siendo el del .sql (es lo que se ejecuta).
#
#   SQL                                            se muestra como
#   "MAX ADU"                                      [MAX ADU]
#   'AUTOLLANTA'                                   "AUTOLLANTA"
#   CASE WHEN c THEN a WHEN d THEN b ELSE e END    SI(c; a; SI(d; b; e))
#   a AND b  /  a OR b  /  NOT a                   Y(a; b)  /  O(a; b)  /  NO(a)
#   COALESCE("EN STOCK", 0)                        [EN STOCK]                 (vacío cuenta como 0, como en Excel)
#   COALESCE(a / NULLIF(b, 0), 0)                  SI.ERROR(a / b; 0)
#   COALESCE(x, y)                                 SI.VACÍO(x; y)
#   COALESCE(NULLIF(x, 0), y)                      SI.VACÍO.O.CERO(x; y)
#   GREATEST / LEAST / AVG / ROUND / PAR           MAX / MIN / PROMEDIO / REDONDEAR / REDONDEA.PAR
#   MAX(x) FILTER (WHERE c) OVER (PARTITION BY n)  MAX.SI.CONJUNTO(x; mismo [n]; c)
#   (SELECT ... ddmrp_parametros ... = 7)          PARÁMETRO(7)
#   x IS NULL  /  x IN ('A', 'B')                  ESBLANCO(x)  /  O(x = "A"; x = "B")
#   NULL                                           VACÍO
# =============================================================================
import re

_TOKEN = re.compile(r'\s+|--[^\n]*|"[^"]*"|\'[^\']*\'|\d+(?:\.\d+)?|<=|>=|<>|!=|::|\|\||[=<>+\-*/(),]'
                    r'|[A-Za-z_][A-Za-z0-9_.]*')
ANCHO_UNA_LINEA = 95          # si la fórmula es más larga, cada SI va en su propia línea

FUNCIONES = {"GREATEST": "MAX", "LEAST": "MIN", "AVG": "PROMEDIO", "ROUND": "REDONDEAR", "PAR": "REDONDEA.PAR",
             "CEIL": "REDONDEAR.MAS", "UPPER": "MAYUSC", "LOWER": "MINUSC", "TRIM": "ESPACIOS", "SIGN": "SIGNO",
             "ABS": "ABS", "SUM": "SUMA", "COUNT": "CONTAR", "MAX": "MAX", "MIN": "MIN"}
CONJUNTO = {"MAX": "MAX.SI.CONJUNTO", "MIN": "MIN.SI.CONJUNTO", "AVG": "PROMEDIO.SI.CONJUNTO",
            "SUM": "SUMAR.SI.CONJUNTO", "COUNT": "CONTAR.SI.CONJUNTO"}


def _tokens(sql):
    salida, pos = [], 0
    while pos < len(sql):
        m = _TOKEN.match(sql, pos)
        if not m:
            raise ValueError(f"no se entiende: {sql[pos:pos + 20]}")
        pos = m.end()
        t = m.group()
        if not t.isspace() and not t.startswith("--"):
            salida.append(t)
    return salida


class _Lector:
    """Lee la fórmula SQL y la convierte en un árbol (tuplas)."""
    def __init__(self, sql):
        self.t, self.i = _tokens(sql), 0

    def ver(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def es(self, *palabras):
        v = self.ver()
        return v is not None and v.upper() in palabras

    def tomar(self, esperado=None):
        v = self.ver()
        if v is None or (esperado and v.upper() != esperado):
            raise ValueError(f"se esperaba {esperado or 'algo'} y vino {v}")
        self.i += 1
        return v

    def todo(self):
        arbol = self.expr()
        if self.ver() is not None:
            raise ValueError(f"sobra: {self.ver()}")
        return arbol

    def expr(self):
        partes = [self.y()]
        while self.es("OR"):
            self.tomar()
            partes.append(self.y())
        return partes[0] if len(partes) == 1 else ("O", partes)

    def y(self):
        partes = [self.no()]
        while self.es("AND"):
            self.tomar()
            partes.append(self.no())
        return partes[0] if len(partes) == 1 else ("Y", partes)

    def no(self):
        if self.es("NOT") and (self.ver(1) or "").upper() != "IN":
            self.tomar()
            return ("NO", self.no())
        return self.comparar()

    def comparar(self):
        a = self.suma()
        v = self.ver()
        if v in ("=", "<>", "!=", "<", ">", "<=", ">="):
            self.tomar()
            return ("cmp", "<>" if v == "!=" else v, a, self.suma())
        if self.es("IS"):
            self.tomar()
            negado = self.es("NOT")
            if negado:
                self.tomar()
            self.tomar("NULL")
            return ("esnulo", a, negado)
        negado = self.es("NOT")
        if negado:
            self.tomar()
        if self.es("IN"):
            self.tomar()
            self.tomar("(")
            lista = [self.expr()]
            while self.ver() == ",":
                self.tomar()
                lista.append(self.expr())
            self.tomar(")")
            return ("en", a, lista, negado)
        return a

    def suma(self):
        a = self.mult()
        while self.ver() in ("+", "-", "||"):
            op = self.tomar()
            a = ("bin", op, a, self.mult())
        return a

    def mult(self):
        a = self.unario()
        while self.ver() in ("*", "/"):
            op = self.tomar()
            a = ("bin", op, a, self.unario())
        return a

    def unario(self):
        if self.ver() == "-":
            self.tomar()
            return ("neg", self.unario())
        a = self.primario()
        while self.ver() == "::":
            self.tomar()
            a = ("cast", a, self.tomar().lower())
        return a

    def primario(self):
        v = self.ver()
        if v is None:
            raise ValueError("fórmula incompleta")
        if v.startswith('"'):
            self.tomar()
            return ("col", v[1:-1])
        if v.startswith("'"):
            self.tomar()
            return ("txt", v[1:-1])
        if re.fullmatch(r"\d+(\.\d+)?", v):
            self.tomar()
            return ("num", v)
        if v == "(":
            if (self.ver(1) or "").upper() == "SELECT":
                return self.subconsulta()
            self.tomar()
            a = self.expr()
            self.tomar(")")
            return ("par", a)
        if v.upper() == "CASE":
            return self.caso()
        if v.upper() == "NULL":
            self.tomar()
            return ("nulo",)
        if v.upper() in ("TRUE", "FALSE"):
            self.tomar()
            return ("bool", v.upper() == "TRUE")
        if self.ver(1) == "(":
            nombre = self.tomar().upper()
            self.tomar("(")
            args = []
            if self.ver() != ")":
                args.append(self.expr())
                while self.ver() == ",":
                    self.tomar()
                    args.append(self.expr())
            self.tomar(")")
            filtro = grupo = None
            if self.es("FILTER"):
                self.tomar()
                self.tomar("(")
                self.tomar("WHERE")
                filtro = self.expr()
                self.tomar(")")
            if self.es("OVER"):
                self.tomar()
                self.tomar("(")
                self.tomar("PARTITION")
                self.tomar("BY")
                grupo = [self.expr()]
                while self.ver() == ",":
                    self.tomar()
                    grupo.append(self.expr())
                self.tomar(")")
            return ("fn", nombre, args, filtro, grupo)
        self.tomar()
        return ("palabra", v)

    def subconsulta(self):
        self.tomar("(")
        nivel, partes = 1, []
        while nivel:
            v = self.tomar()
            nivel += {"(": 1, ")": -1}.get(v, 0)
            if nivel:
                partes.append(v)
        texto = " ".join(partes)
        m = re.search(r"ddmrp_parametros.*ddmrp_id\s*=\s*(\d+)", texto, re.IGNORECASE)
        return ("param", m.group(1)) if m else ("sub", texto)

    def caso(self):
        self.tomar("CASE")
        base = None if self.es("WHEN") else self.expr()
        ramas = []
        while self.es("WHEN"):
            self.tomar()
            condicion = self.expr()
            self.tomar("THEN")
            ramas.append((condicion, self.expr()))
        otro = None
        if self.es("ELSE"):
            self.tomar()
            otro = self.expr()
        self.tomar("END")
        if base is not None:
            ramas = [(("cmp", "=", base, c), v) for c, v in ramas]
        return ("si", ramas, otro)


def _tiene_nullif(n):
    if not isinstance(n, tuple):
        return False
    if n[0] == "fn" and n[1] == "NULLIF":
        return True
    return any(_tiene_nullif(x) if isinstance(x, tuple) else any(_tiene_nullif(y) for y in x)
               if isinstance(x, list) else False for x in n[1:])


def _es_cero(n):
    return n[0] == "num" and float(n[1]) == 0


def _sin_nullif(n):
    """NULLIF(x, 0) -> x (para mostrar dentro de SI.ERROR). Si x es una operación va entre paréntesis:
    a / NULLIF(b * c, 0) -> a / (b * c)."""
    if not isinstance(n, tuple):
        return n
    if n[0] == "fn" and n[1] == "NULLIF":
        x = _sin_nullif(n[2][0])
        return ("par", x) if x[0] == "bin" else x
    return tuple([n[0]] + [_sin_nullif(x) if isinstance(x, tuple)
                           else [_sin_nullif(y) for y in x] if isinstance(x, list) else x for x in n[1:]])


def _condiciones(n):
    """Y(a; b; c) -> [a, b, c] (para MAX.SI.CONJUNTO)."""
    return n[1] if n[0] == "Y" else [n]


def _f(n):
    """Árbol -> texto de la fórmula (en una línea)."""
    tipo = n[0]
    if tipo == "col":
        return f"[{n[1]}]"
    if tipo == "txt":
        return f'"{n[1]}"'
    if tipo == "num":
        return n[1]
    if tipo == "nulo":
        return "VACÍO"
    if tipo == "bool":
        return "VERDADERO" if n[1] else "FALSO"
    if tipo == "palabra":
        return n[1]
    if tipo == "par":
        return f"({_f(n[1])})"
    if tipo == "neg":
        return f"-{_f(n[1])}"
    if tipo == "cast":
        return f"TEXTO({_f(n[1])})" if n[2] in ("text", "varchar") else _f(n[1])
    if tipo == "bin":
        return f"{_f(n[2])} {'&' if n[1] == '||' else n[1]} {_f(n[3])}"
    if tipo == "cmp":
        return f"{_f(n[2])} {n[1]} {_f(n[3])}"
    if tipo in ("Y", "O"):
        return f"{tipo}(" + "; ".join(_f(x) for x in n[1]) + ")"
    if tipo == "NO":
        return f"NO({_f(n[1])})"
    if tipo == "esnulo":
        return f"NO(ESBLANCO({_f(n[1])}))" if n[2] else f"ESBLANCO({_f(n[1])})"
    if tipo == "en":
        texto = "O(" + "; ".join(f"{_f(n[1])} = {_f(x)}" for x in n[2]) + ")"
        return f"NO({texto})" if n[3] else texto
    if tipo == "param":
        return f"PARÁMETRO({n[1]})"
    if tipo == "sub":
        return f"(consulta: {n[1]})"
    if tipo == "si":
        return _si(n, en_linea=True)
    if tipo == "fn":
        return _funcion(n)
    return str(n)


def _funcion(n):
    _, nombre, args, filtro, grupo = n
    if nombre == "COALESCE" and len(args) == 2:
        x, y = args
        if _es_cero(y):
            if x[0] == "col":
                return _f(x)                                    # vacío cuenta como 0 (como en Excel)
            if _tiene_nullif(x):
                return f"SI.ERROR({_f(_sin_nullif(x))}; 0)"
            return f"SI.VACÍO({_f(x)}; 0)"
        if x[0] == "fn" and x[1] == "NULLIF" and len(x[2]) == 2 and _es_cero(x[2][1]):
            return f"SI.VACÍO.O.CERO({_f(x[2][0])}; {_f(y)})"
        return f"SI.VACÍO({_f(x)}; {_f(y)})"
    if nombre == "COALESCE":
        return "SI.VACÍO(" + "; ".join(_f(a) for a in args) + ")"
    if nombre == "NULLIF":
        return f"({_f(args[0])})" if args[0][0] == "bin" else _f(args[0])
    if grupo is not None or filtro is not None:
        partes = [_f(a) for a in args]
        partes += [f"mismo {_f(g)}" for g in (grupo or [])]
        partes += [_f(c) for c in (_condiciones(filtro) if filtro is not None else [])]
        return f"{CONJUNTO.get(nombre, nombre + '.SI.CONJUNTO')}(" + "; ".join(partes) + ")"
    if nombre == "CEIL":
        return f"REDONDEAR.MAS({_f(args[0])}; 0)"
    return f"{FUNCIONES.get(nombre, nombre)}(" + "; ".join(_f(a) for a in args) + ")"


def _si(n, en_linea=False):
    """CASE -> SI anidados. Si es largo, cada condición en su línea:
         SI(condición 1;  valor 1;
         SI(condición 2;  valor 2;
            si no se cumple ninguna))"""
    ramas, otro = n[1], n[2]
    final = _f(otro) if otro is not None else "VACÍO"
    una = final
    for c, v in reversed(ramas):
        una = f"SI({_f(c)}; {_f(v)}; {una})"
    if en_linea or len(una) <= ANCHO_UNA_LINEA:
        return una
    lineas = [f"SI({_f(c)};   {_f(v)};" for c, v in ramas]
    lineas.append("   " + final + ")" * len(ramas))
    return "\n".join(lineas)


def a_formula(sql):
    """Fórmula SQL -> fórmula al estilo Excel (texto). None si no se pudo convertir."""
    try:
        arbol = _Lector(sql).todo()
    except (ValueError, IndexError):
        return None
    texto = _si(arbol) if arbol[0] == "si" else _f(arbol)
    return "= " + texto.replace("\n", "\n  ")                 # las líneas de los SI, alineadas


# Ayuda de la pestaña Cálculos: si la fórmula tiene <patrón>, se explica qué significa.
AYUDA = [
    (r"\[", "<b>[COLUMNA]</b> = el valor de esa columna para el ítem. Una celda vacía cuenta como 0 en las sumas y "
            "comparaciones, igual que en Excel."),
    (r"(?<![.\w])SI\(", "<b>SI</b>(condición; valor si se cumple; valor si no). Con varios SI seguidos se revisan en "
                        "orden y se usa el primero que se cumple."),
    (r"(?<![.\w])Y\(", "<b>Y</b>(a; b; …) = se cumplen todas."),
    (r"(?<![.\w])O\(", "<b>O</b>(a; b; …) = se cumple al menos una."),
    (r"(?<![.\w])NO\(", "<b>NO</b>(a) = no se cumple a."),
    (r"SI\.ERROR\(", "<b>SI.ERROR</b>(cálculo; 0) = si el cálculo no se puede hacer (dividir para 0 o falta un dato) da 0."),
    (r"SI\.VACÍO\(", "<b>SI.VACÍO</b>(x; y) = usa x; si x está vacío, usa y."),
    (r"SI\.VACÍO\.O\.CERO\(", "<b>SI.VACÍO.O.CERO</b>(x; y) = usa x; si x está vacío o es 0, usa y."),
    (r"(?<![.\w])MAX\(", "<b>MAX</b>(a; b) = el mayor de los valores."),
    (r"(?<![.\w])MIN\(", "<b>MIN</b>(a; b) = el menor de los valores."),
    (r"\.SI\.CONJUNTO\(", "<b>MAX.SI.CONJUNTO</b>(x; mismo [COLUMNA]; condiciones) = el mayor valor de x entre las filas "
                          "que tienen el mismo valor de [COLUMNA] que este ítem (por ejemplo el mismo ítem en otra "
                          "empresa) y que cumplen las condiciones. <b>PROMEDIO.SI.CONJUNTO</b> igual, con el promedio."),
    (r"REDONDEA\.PAR\(", "<b>REDONDEA.PAR</b>(x) = sube al número par siguiente: 7.3 → 8, 8 → 8 (como en Excel)."),
    (r"(?<![.\w])REDONDEAR\(", "<b>REDONDEAR</b>(x; n) = redondea x a n decimales."),
    (r"REDONDEAR\.MAS\(", "<b>REDONDEAR.MAS</b>(x; 0) = sube al entero siguiente: 7.1 → 8."),
    (r"PARÁMETRO\(", "<b>PARÁMETRO</b>(n) = el valor n de la tabla de parámetros del DDMRP (core.ddmrp_parametros). "
                     "Se cambia en esa tabla."),
    (r"ESBLANCO\(", "<b>ESBLANCO</b>(x) = x está vacío."),
    (r"MAYUSC\(|ESPACIOS\(", "<b>MAYUSC</b>(x) = en mayúsculas;  <b>ESPACIOS</b>(x) = sin espacios en los extremos."),
    (r"TEXTO\(", "<b>TEXTO</b>(x) = el número como texto."),
    (r"VACÍO(?!\()", "<b>VACÍO</b> = sin valor. En el reporte, los pedidos y MESES X PEDIR PARA PISO vacíos se muestran "
                     "como E (como el \"E\" del Excel)."),
    (r" & ", "<b>a &amp; b</b> = une los textos."),
]
