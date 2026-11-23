-- =============================================================================
-- DDMRP CONSOLIDADO v1 - FÓRMULAS
-- =============================================================================
-- Aquí están TODOS los cálculos del reporte, uno por columna, en el orden en que se hacen.
-- Para corregir una fórmula se cambia solo la línea (o líneas) de esa columna.
--
-- CÓMO SE LEE:
--   -- @PASO 3 · DEMANDA                        <- empieza un paso (las columnas de un paso
--                                                   pueden usar las de los pasos ANTERIORES)
--   -- explicación de la columna                <- las líneas con -- son comentarios
--   COALESCE("UN (#) - AÑO" * 30 / NULLIF("DIAS INV 1 AÑO", 0), 0)    AS "DEMANDA MES - AÑO",
--   └──────────────── la fórmula ────────────────────────────────┘    └─ la columna que crea ─┘
--
--   - Los nombres de columna van entre comillas dobles: "EN STOCK".  Los textos van entre comillas
--     simples: 'AUTOLLANTA'.
--   - Cada fórmula termina en  AS "NOMBRE DE LA COLUMNA",   (con coma al final).
--   - Una columna puede volver a calcularse en un paso posterior (se reemplaza).
--   - Se calcula con TODOS los decimales. Solo se redondea donde la fórmula lo dice.
--   - Una columna nueva se muestra en el reporte si se agrega a COLUMNAS_REPORTE en ddmrp_consolidado_v1.py.
--   - Las columnas que empiezan con _ son auxiliares (se usan en otras fórmulas, no se muestran).
--   - Vacío (NULL) en los PEDIDOS y en MESES X PEDIR PARA PISO = lo que en Excel sale como "E".
--
-- DICCIONARIO EXCEL -> SQL:
--   SI(cond; a; b)                  CASE WHEN cond THEN a ELSE b END
--   SI(cond1; a; SI(cond2; b; c))   CASE WHEN cond1 THEN a WHEN cond2 THEN b ELSE c END
--   Y(a; b)  /  O(a; b)             a AND b  /  a OR b
--   SI.ERROR(x; 0)                  COALESCE(x, 0)
--   a / b sin error si b = 0        a / NULLIF(b, 0)              (da vacío; con COALESCE queda 0)
--   celda vacía cuenta como 0       COALESCE("COLUMNA", 0)
--   MAX(a; b)  /  MIN(a; b)         GREATEST(a, b)  /  LEAST(a, b)
--   REDONDEAR(x; 2)                 ROUND(x, 2)
--   REDONDEA.PAR(x)                 PAR(x)        (al par siguiente alejándose del cero: 7.3 -> 8)
--   <> (distinto)                   <>
--
-- Origen de los datos: ver la consulta SQL_ITEMS en ddmrp_consolidado_v1.py (o la pestaña Filtros).
-- Los parámetros salen de core.ddmrp_parametros (ddmrp_id = número del parámetro).
-- =============================================================================


-- @PASO 1 · AUXILIARES
-- Nombre del ítem para unir el mismo ítem entre empresas (homologación)
UPPER(TRIM("DESCRIPCION"))                                                    AS "_NOMBRE",

-- DLT del proveedor que le toca al ítem: con BACKORDERS el DLT máximo (incluye el tiempo de backorder),
-- sin BACKORDERS el mínimo. Sin proveedor con DLT = 0.
COALESCE(CASE WHEN COALESCE("BACKORDERS", 0) > 0 THEN "_DLT MAX PROVEEDOR"
              ELSE "_DLT MIN PROVEEDOR" END, 0)                               AS "_DLT PROVEEDOR",


-- @PASO 2 · HOMOLOGACIÓN (la empresa que planifica toma los datos de la otra, por el mismo nombre)
--   ROADWING PESADO: AUTOLLANTA toma de STOX     |  CST MOTO: STOX toma de MAXXIMUNDO
--   IKONIX (al revés): IKONIX toma de MAXXIMUNDO (marcas UYUSTOOLS, DONGCHENG, SATA)
-- Si cambia algún caso, cambiarlo también en ddmrp_ventas_picos.py, ddmrp_bodega.py y la vista de ventas.

-- DIAS INV 1 AÑO: AUTOLLANTA (ROADWING PESADO) y STOX (CST MOTO) toman los días de la otra empresa
CASE
    WHEN "EMPRESA" = 'AUTOLLANTA' THEN COALESCE(MAX("DIAS INV 1 AÑO") FILTER (WHERE "EMPRESA" = 'STOX' AND "PROPIEDAD" = 'ROADWING PESADO') OVER (PARTITION BY "_NOMBRE"), "DIAS INV 1 AÑO")
    WHEN "EMPRESA" = 'STOX'       THEN COALESCE(MAX("DIAS INV 1 AÑO") FILTER (WHERE "EMPRESA" = 'MAXXIMUNDO' AND "MARCA" = 'CST' AND "GRUPO" = 'LLANTAS MOTO') OVER (PARTITION BY "_NOMBRE"), "DIAS INV 1 AÑO")
    ELSE "DIAS INV 1 AÑO"
END                                                                           AS "DIAS INV 1 AÑO",

-- DIAS INV 90D: igual que DIAS INV 1 AÑO
CASE
    WHEN "EMPRESA" = 'AUTOLLANTA' THEN COALESCE(MAX("DIAS INV 90D") FILTER (WHERE "EMPRESA" = 'STOX' AND "PROPIEDAD" = 'ROADWING PESADO') OVER (PARTITION BY "_NOMBRE"), "DIAS INV 90D")
    WHEN "EMPRESA" = 'STOX'       THEN COALESCE(MAX("DIAS INV 90D") FILTER (WHERE "EMPRESA" = 'MAXXIMUNDO' AND "MARCA" = 'CST' AND "GRUPO" = 'LLANTAS MOTO') OVER (PARTITION BY "_NOMBRE"), "DIAS INV 90D")
    ELSE "DIAS INV 90D"
END                                                                           AS "DIAS INV 90D",

-- COSTO PROM, ULT. COSTO y P. LISTA salen del COMERCIALIZADOR (si allá está en 0 o vacío, queda el propio)
CASE
    WHEN "EMPRESA" = 'AUTOLLANTA' THEN COALESCE(NULLIF(MAX("COSTO PROM") FILTER (WHERE "EMPRESA" = 'STOX' AND "PROPIEDAD" = 'ROADWING PESADO') OVER (PARTITION BY "_NOMBRE"), 0), "COSTO PROM")
    WHEN "EMPRESA" = 'STOX'       THEN COALESCE(NULLIF(MAX("COSTO PROM") FILTER (WHERE "EMPRESA" = 'MAXXIMUNDO' AND "MARCA" = 'CST' AND "GRUPO" = 'LLANTAS MOTO') OVER (PARTITION BY "_NOMBRE"), 0), "COSTO PROM")
    ELSE "COSTO PROM"
END                                                                           AS "COSTO PROM",

CASE
    WHEN "EMPRESA" = 'AUTOLLANTA' THEN COALESCE(NULLIF(MAX("ULT. COSTO") FILTER (WHERE "EMPRESA" = 'STOX' AND "PROPIEDAD" = 'ROADWING PESADO') OVER (PARTITION BY "_NOMBRE"), 0), "ULT. COSTO")
    WHEN "EMPRESA" = 'STOX'       THEN COALESCE(NULLIF(MAX("ULT. COSTO") FILTER (WHERE "EMPRESA" = 'MAXXIMUNDO' AND "MARCA" = 'CST' AND "GRUPO" = 'LLANTAS MOTO') OVER (PARTITION BY "_NOMBRE"), 0), "ULT. COSTO")
    ELSE "ULT. COSTO"
END                                                                           AS "ULT. COSTO",

CASE
    WHEN "EMPRESA" = 'AUTOLLANTA' THEN COALESCE(NULLIF(MAX("P. LISTA") FILTER (WHERE "EMPRESA" = 'STOX' AND "PROPIEDAD" = 'ROADWING PESADO') OVER (PARTITION BY "_NOMBRE"), 0), "P. LISTA")
    WHEN "EMPRESA" = 'STOX'       THEN COALESCE(NULLIF(MAX("P. LISTA") FILTER (WHERE "EMPRESA" = 'MAXXIMUNDO' AND "MARCA" = 'CST' AND "GRUPO" = 'LLANTAS MOTO') OVER (PARTITION BY "_NOMBRE"), 0), "P. LISTA")
    ELSE "P. LISTA"
END                                                                           AS "P. LISTA",

-- ULTIMO FOB sale del IMPORTADOR: IKONIX lo toma de MAXXIMUNDO (si allá está en 0 o vacío, queda el propio)
CASE
    WHEN "EMPRESA" = 'IKONIX' THEN COALESCE(NULLIF(MAX("ULTIMO FOB") FILTER (WHERE "EMPRESA" = 'MAXXIMUNDO' AND "MARCA" IN ('UYUSTOOLS', 'DONGCHENG', 'SATA')) OVER (PARTITION BY "_NOMBRE"), 0), "ULTIMO FOB")
    ELSE "ULTIMO FOB"
END                                                                           AS "ULTIMO FOB",

-- DLT: el del proveedor; si quedó en 0, el promedio del DLT de los ítems de la misma MARCA que sí tienen
CASE
    WHEN "_DLT PROVEEDOR" = 0 AND "MARCA" IS NOT NULL
        THEN COALESCE(AVG("_DLT PROVEEDOR") FILTER (WHERE "_DLT PROVEEDOR" > 0) OVER (PARTITION BY "MARCA"), 0)
    ELSE "_DLT PROVEEDOR"
END                                                                           AS "DLT",


-- @PASO 3 · DÍAS MÍNIMOS
-- Si el ítem tiene más de 4 unidades en stock y un DIAS INV está en 0, pasa a 1
CASE WHEN COALESCE("EN STOCK", 0) > 4 AND COALESCE("DIAS INV 1 AÑO", 0) = 0 THEN 1
     ELSE "DIAS INV 1 AÑO" END                                                AS "DIAS INV 1 AÑO",

CASE WHEN COALESCE("EN STOCK", 0) > 4 AND COALESCE("DIAS INV 90D", 0) = 0 THEN 1
     ELSE "DIAS INV 90D" END                                                  AS "DIAS INV 90D",


-- @PASO 4 · STOCK, DEMANDA, ADU Y FACTORES
-- STOCK TOTAL = EN STOCK + TRANSITOS TOTAL + PEDIDOS + BACKORDERS   (vacíos = 0)
COALESCE("EN STOCK", 0) + COALESCE("TRANSITOS TOTAL", 0)
  + COALESCE("PEDIDOS", 0) + COALESCE("BACKORDERS", 0)                        AS "STOCK TOTAL",

-- DEMANDA MES - AÑO = UN (#) - AÑO * 30 / DIAS INV 1 AÑO   (0 si no hay días)
COALESCE("UN (#) - AÑO" * 30 / NULLIF("DIAS INV 1 AÑO", 0), 0)                AS "DEMANDA MES - AÑO",

-- DEMANDA MES 90D = UN (#) - 90D * 30 / DIAS INV 90D   (0 si no hay días)
COALESCE("UN (#) - 90D" * 30 / NULLIF("DIAS INV 90D", 0), 0)                  AS "DEMANDA MES 90D",

-- ADU BASE = UN (#) - AÑO / DIAS INV 1 AÑO   (demanda diaria del año; 0 si no hay días)
COALESCE("UN (#) - AÑO" / NULLIF("DIAS INV 1 AÑO", 0), 0)                     AS "ADU BASE",

-- ADU 90 DÍAS = UN (#) - 90D / DIAS INV 90D   (= DEMANDA MES 90D / 30; 0 si no hay días)
COALESCE("UN (#) - 90D" / NULLIF("DIAS INV 90D", 0), 0)                       AS "ADU 90 DÍAS",

-- % VARIACIÓN DEMANDA = (demanda diaria 90D / demanda diaria del año - 1) * 100   (0 si no se puede)
COALESCE(("UN (#) - 90D" * NULLIF("DIAS INV 1 AÑO", 0)
          / NULLIF("DIAS INV 90D" * "UN (#) - AÑO", 0) - 1) * 100, 0)         AS "% VARIACIÓN DEMANDA",

-- ADU SIN PICOS = el de core.ddmrp_ventas_picos (solo informativo; 0 si no tiene ventas)
COALESCE("_ADU SIN PICOS", 0)                                                 AS "ADU SIN PICOS",

-- VF (factor de variabilidad) según el CV de las ventas: <= 0.5 -> parámetro 7 (0.2) | <= 1 -> parámetro 8 (0.4)
-- | más -> parámetro 9 (0.6) | sin ventas o CV = 0 -> 0.20
CASE
    WHEN NOT "_EN VENTAS PICOS" OR "_CV" = 0 THEN 0.20
    WHEN "_CV" <= 0.5 THEN (SELECT ddmrp_valor_num::numeric FROM core.ddmrp_parametros WHERE ddmrp_id = 7)
    WHEN "_CV" <= 1   THEN (SELECT ddmrp_valor_num::numeric FROM core.ddmrp_parametros WHERE ddmrp_id = 8)
    ELSE                   (SELECT ddmrp_valor_num::numeric FROM core.ddmrp_parametros WHERE ddmrp_id = 9)
END                                                                           AS "VF",

-- LTF (factor de lead time) según el DLT: <= 60 -> parámetro 6 (0.6) | <= 100 -> parámetro 5 (0.4)
-- | más -> parámetro 4 (0.2) | sin DLT -> 0.20
CASE
    WHEN "DLT" = 0    THEN 0.20
    WHEN "DLT" <= 60  THEN (SELECT ddmrp_valor_num::numeric FROM core.ddmrp_parametros WHERE ddmrp_id = 6)
    WHEN "DLT" <= 100 THEN (SELECT ddmrp_valor_num::numeric FROM core.ddmrp_parametros WHERE ddmrp_id = 5)
    ELSE                   (SELECT ddmrp_valor_num::numeric FROM core.ddmrp_parametros WHERE ddmrp_id = 4)
END                                                                           AS "LTF",

-- MESES EN PISO X CATEGORIA: 3 meses si el PARETO es A o B, si no 2
CASE WHEN "CLASIF. PARETO" IN ('A', 'B') THEN 3 ELSE 2 END                    AS "MESES EN PISO X CATEGORIA",

-- P. LISTA VS ULT.COSTO = (P. LISTA - ULT. COSTO) * 100 / P. LISTA   (sin ULT. COSTO = 0; sin P. LISTA = 0)
COALESCE(("P. LISTA" - COALESCE("ULT. COSTO", 0)) * 100 / NULLIF("P. LISTA", 0), 0)
                                                                              AS "P. LISTA VS ULT.COSTO",


-- @PASO 5 · MAX ADU Y NFP
-- MAX ADU = MAX(ADU BASE; ADU 90 DÍAS)
GREATEST("ADU BASE", "ADU 90 DÍAS")                                           AS "MAX ADU",

-- FLUJO NETO (NFP) = STOCK TOTAL
"STOCK TOTAL"                                                                 AS "FLUJO NETO (NFP)",

-- # MES INV TOTAL SEGUN DEMANDA 90D = STOCK TOTAL / DEMANDA MES 90D
-- (sin ventas en el año ni en 90 días y con stock = 9999; sin demanda = 0)
CASE
    WHEN COALESCE("UN (#) - AÑO", 0) = 0 AND COALESCE("UN (#) - 90D", 0) = 0 AND "STOCK TOTAL" > 0 THEN 9999
    ELSE COALESCE("STOCK TOTAL" * NULLIF("DIAS INV 90D", 0) / NULLIF("UN (#) - 90D" * 30, 0), 0)
END                                                                           AS "# MES INV TOTAL SEGUN DEMANDA 90D",

-- MESES EN PISO + DLT X CATEGORIA CON MAX ADU = DLT / 30 + MESES EN PISO X CATEGORIA
"DLT" / 30 + "MESES EN PISO X CATEGORIA"                                      AS "MESES EN PISO + DLT X CATEGORIA CON MAX ADU",

-- Zonas del buffer (Excel: roja y amarilla con ADU BASE, verde con ADU 90 DÍAS)
-- ZONA ROJA BASE = DLT * ADU BASE * LTF
"DLT" * "ADU BASE" * "LTF"                                                    AS "ZONA ROJA BASE",

-- ZONA AMARILLA = DLT * ADU BASE
"DLT" * "ADU BASE"                                                            AS "ZONA AMARILLA",

-- ZONA VERDE = ADU 90 DÍAS * 30
"ADU 90 DÍAS" * 30                                                            AS "ZONA VERDE",

-- OBSERVACIONES (lógica del ddmrp anterior, con el ADU CON PICOS de core.ddmrp_ventas_picos): zona roja base
ROUND(COALESCE("_ADU CON PICOS", 0) * "DLT" * "LTF", 2)                       AS "_OBS ROJA BASE",


-- @PASO 6 · MESES QUE CUBRE CADA CANTIDAD Y VALIDADOR
-- # MESES EN STOCK CON MAX ADU = EN STOCK / MAX ADU / 30   (0 si no hay ADU)
COALESCE(COALESCE("EN STOCK", 0) / NULLIF("MAX ADU", 0) / 30, 0)              AS "# MESES EN STOCK CON MAX ADU",

-- MESES STOCK EN SEGÚN ADU = EN STOCK / ADU BASE / 30   (0 si no hay ADU BASE)
COALESCE(COALESCE("EN STOCK", 0) / NULLIF("ADU BASE", 0) / 30, 0)             AS "MESES STOCK EN SEGÚN ADU",

-- # MESES EN TRANSITO = TRANSITOS TOTAL / MAX ADU / 30
COALESCE(COALESCE("TRANSITOS TOTAL", 0) / NULLIF("MAX ADU", 0) / 30, 0)       AS "# MESES EN TRANSITO",

-- # MESES EN PEDIDOS = PEDIDOS / MAX ADU / 30
COALESCE(COALESCE("PEDIDOS", 0) / NULLIF("MAX ADU", 0) / 30, 0)               AS "# MESES EN PEDIDOS",

-- # MESES EN BACK ORDERS = BACKORDERS / MAX ADU / 30
COALESCE(COALESCE("BACKORDERS", 0) / NULLIF("MAX ADU", 0) / 30, 0)            AS "# MESES EN BACK ORDERS",

-- # MESES EN STOCK TOTALSEGUN ADU = STOCK TOTAL / ADU BASE / 30
COALESCE("STOCK TOTAL" / NULLIF("ADU BASE", 0) / 30, 0)                       AS "# MESES EN STOCK TOTALSEGUN ADU",

-- # MESES EN STOCK TOTAL CON MAX ADU = STOCK TOTAL / MAX ADU / 30
COALESCE("STOCK TOTAL" / NULLIF("MAX ADU", 0) / 30, 0)                        AS "# MESES EN STOCK TOTAL CON MAX ADU",

-- STOCK PROYECTADO DLT CON MAX ADU = STOCK TOTAL - DLT * MAX ADU
"STOCK TOTAL" - "DLT" * "MAX ADU"                                             AS "STOCK PROYECTADO DLT CON MAX ADU",

-- VALIDADOR
CASE
    WHEN "STOCK TOTAL" = 0 AND "MAX ADU" = 0 THEN 'REVISAR PARA INACTIVAR'
    WHEN "STOCK TOTAL" = 0 AND "MAX ADU" > 0 THEN 'PEDIR MESES X CATEGORIA'
    WHEN "STOCK TOTAL" > 0 AND "MAX ADU" = 0 THEN 'INFINITO REVISAR FALTA DE VENTAS'
    WHEN "STOCK TOTAL" > 0 AND "MAX ADU" > 0 THEN 'PEDIR BAJO CALCULO'
    ELSE 'FALSO'
END                                                                           AS "VALIDADOR",

-- ZONA ROJA SEGURIDAD = ZONA ROJA BASE * VF
"ZONA ROJA BASE" * "VF"                                                       AS "ZONA ROJA SEGURIDAD",

-- TAMAÑO 3 MESES SEGÚN MAX ADU = MAX ADU * 90
"MAX ADU" * 90                                                                AS "TAMAÑO 3 MESES SEGÚN MAX ADU",

-- FLUJO NETO (NFP) AJUSTADO = NFP - DLT * MAX ADU   (0 si queda negativo)
GREATEST("FLUJO NETO (NFP)" - "DLT" * "MAX ADU", 0)                           AS "FLUJO NETO (NFP) AJUSTADO",

-- FLUJO NETO (NFP) AJUSTADO JP = NFP - MAX ADU * DLT / 3   (0 si queda negativo)
GREATEST("FLUJO NETO (NFP)" - "MAX ADU" * "DLT" / 3, 0)                       AS "FLUJO NETO (NFP) AJUSTADO JP",

-- OBSERVACIONES (lógica anterior): TOG, NFP y stock proyectado con el ADU con picos (ciclo = parámetro 3)
"_OBS ROJA BASE" + ROUND("_OBS ROJA BASE" * "VF", 2) + ROUND(COALESCE("_ADU CON PICOS", 0) * "DLT", 2)
  + GREATEST(ROUND(COALESCE("_ADU CON PICOS", 0)
                   * (SELECT ddmrp_valor_num::numeric FROM core.ddmrp_parametros WHERE ddmrp_id = 3), 2),
             "_OBS ROJA BASE")                                                AS "_OBS TOG",

"STOCK TOTAL" - COALESCE("_ADU CON PICOS", 0) * "DLT"                         AS "_OBS NFP",

ROUND("STOCK TOTAL" - "DLT" * COALESCE("_ADU CON PICOS", 0), 2)               AS "_OBS STOCK PROY",


-- @PASO 7 · MESES DE STOCK, MESES A PEDIR Y ZONAS
-- Meses que cubre el stock proyectado (número; vacío = infinito). Lo usan las dos columnas de abajo.
--   REVISAR PARA INACTIVAR -> 0 | PEDIR MESES X CATEGORIA -> MESES EN PISO X CATEGORIA
--   PEDIR BAJO CALCULO -> STOCK PROYECTADO DLT CON MAX ADU / MAX ADU / 30 | INFINITO... -> vacío
CASE "VALIDADOR"
    WHEN 'REVISAR PARA INACTIVAR'  THEN 0
    WHEN 'PEDIR MESES X CATEGORIA' THEN "MESES EN PISO X CATEGORIA"
    WHEN 'PEDIR BAJO CALCULO'      THEN "STOCK PROYECTADO DLT CON MAX ADU" / "MAX ADU" / 30
    WHEN 'FALSO'                   THEN 0
END                                                                           AS "_MES DE STOCK",

-- MESES X PEDIR PARA PISO (Excel: =SI.ERROR(SI(BH<=0; BK; SI(Y(BH>0; BH/AF/30>BK); BK;
--   SI(Y(BH>0; BH/AF/30<BK); BK-BH/AF/30; "E"))); 0)   BH = stock proyectado, AF = MAX ADU, BK = meses en piso)
CASE
    WHEN "STOCK PROYECTADO DLT CON MAX ADU" <= 0 THEN "MESES EN PISO X CATEGORIA"
    WHEN "MAX ADU" = 0 THEN 0
    WHEN "STOCK PROYECTADO DLT CON MAX ADU" / "MAX ADU" / 30 > "MESES EN PISO X CATEGORIA" THEN "MESES EN PISO X CATEGORIA"
    WHEN "STOCK PROYECTADO DLT CON MAX ADU" / "MAX ADU" / 30 < "MESES EN PISO X CATEGORIA"
        THEN "MESES EN PISO X CATEGORIA" - "STOCK PROYECTADO DLT CON MAX ADU" / "MAX ADU" / 30
END                                                                           AS "MESES X PEDIR PARA PISO",

-- ZONA ROJA (TOR) = ZONA ROJA BASE + ZONA ROJA SEGURIDAD
"ZONA ROJA BASE" + "ZONA ROJA SEGURIDAD"                                      AS "ZONA ROJA (TOR)",

-- OBSERVACIONES (lógica anterior): tamaño de pedido = TOG - NFP si NFP <= TOG (mínimo 0), si no 0
CASE WHEN "_OBS NFP" <= "_OBS TOG" THEN GREATEST("_OBS TOG" - "_OBS NFP", 0) ELSE 0 END
                                                                              AS "_OBS TAMAÑO PEDIDO",


-- @PASO 8 · BUFFER Y PEDIDO A PISO
-- # MES DE STOCK PROYECT MAX ADU DLT: los meses del stock proyectado, o INFINITO si no hay ventas
CASE WHEN "VALIDADOR" = 'INFINITO REVISAR FALTA DE VENTAS' THEN 'INFINITO'
     ELSE "_MES DE STOCK"::text END                                           AS "# MES DE STOCK PROYECT MAX ADU DLT",

-- MESES X PEDIR TOTAL = MESES EN PISO + DLT - meses de stock proyectado   (0 si es negativo o infinito)
CASE WHEN "VALIDADOR" = 'INFINITO REVISAR FALTA DE VENTAS' THEN 0
     ELSE GREATEST("MESES EN PISO + DLT X CATEGORIA CON MAX ADU" - "_MES DE STOCK", 0) END
                                                                              AS "MESES X PEDIR TOTAL",

-- LIMITE ZONA AMARILLA (TOY) = ZONA AMARILLA + ZONA ROJA (TOR)
"ZONA AMARILLA" + "ZONA ROJA (TOR)"                                           AS "LIMITE ZONA AMARILLA (TOY)",

-- PEDIDO SUGERIDO AJUSTADO A PISO = REDONDEA.PAR(MESES X PEDIR PARA PISO * MAX ADU * 30)
PAR("MESES X PEDIR PARA PISO" * "MAX ADU" * 30)                               AS "PEDIDO SUGERIDO AJUSTADO A PISO",

-- OBSERVACIONES: INACTIVAR si el tamaño de pedido es 0 y no hay stock | LIQUIDAR si es 0 y queda stock proyectado
CASE
    WHEN "_OBS TAMAÑO PEDIDO" = 0 AND "STOCK TOTAL" = 0      THEN 'INACTIVAR'
    WHEN "_OBS TAMAÑO PEDIDO" = 0 AND "_OBS STOCK PROY" <> 0 THEN 'LIQUIDAR'
    ELSE '-'
END                                                                           AS "OBSERVACIONES",


-- @PASO 9 · TAMAÑO DEL BUFFER
-- TAMAÑO BUFFER (TOG) = ZONA VERDE + LIMITE ZONA AMARILLA (TOY)
"ZONA VERDE" + "LIMITE ZONA AMARILLA (TOY)"                                   AS "TAMAÑO BUFFER (TOG)",

-- # DE MESES DEL PEDIDO SEGÚN MAX ADU = PEDIDO SUGERIDO AJUSTADO A PISO / MAX ADU / 30   (0 si no hay ADU)
COALESCE("PEDIDO SUGERIDO AJUSTADO A PISO" / NULLIF("MAX ADU", 0) / 30, 0)    AS "# DE MESES DEL PEDIDO SEGÚN MAX ADU",


-- @PASO 10 · PEDIDOS DDMRP
-- PEDIDO ESTANDAR DDMRP = REDONDEA.PAR(TOG - NFP) si el NFP es menor al TOG; 0 si el NFP es mayor
--   (Excel: =SI(Y(TOG=0; NFP=0); 0; SI(Y(TOG>=0; NFP>=0; NFP>TOG); 0; SI(Y(TOG>=0; NFP>=0; NFP<TOG); REDONDEA.PAR(TOG-NFP); "E"))))
CASE
    WHEN "TAMAÑO BUFFER (TOG)" = 0 AND "FLUJO NETO (NFP)" = 0 THEN 0
    WHEN "TAMAÑO BUFFER (TOG)" >= 0 AND "FLUJO NETO (NFP)" >= 0 AND "FLUJO NETO (NFP)" > "TAMAÑO BUFFER (TOG)" THEN 0
    WHEN "TAMAÑO BUFFER (TOG)" >= 0 AND "FLUJO NETO (NFP)" >= 0 AND "FLUJO NETO (NFP)" < "TAMAÑO BUFFER (TOG)"
        THEN PAR("TAMAÑO BUFFER (TOG)" - "FLUJO NETO (NFP)")
END                                                                           AS "PEDIDO ESTANDAR DDMRP",

-- PEDIDO AJUSTADO DDMRP = igual, con FLUJO NETO (NFP) AJUSTADO
CASE
    WHEN "TAMAÑO BUFFER (TOG)" = 0 AND "FLUJO NETO (NFP) AJUSTADO" = 0 THEN 0
    WHEN "TAMAÑO BUFFER (TOG)" >= 0 AND "FLUJO NETO (NFP) AJUSTADO" >= 0 AND "FLUJO NETO (NFP) AJUSTADO" > "TAMAÑO BUFFER (TOG)" THEN 0
    WHEN "TAMAÑO BUFFER (TOG)" >= 0 AND "FLUJO NETO (NFP) AJUSTADO" >= 0 AND "FLUJO NETO (NFP) AJUSTADO" < "TAMAÑO BUFFER (TOG)"
        THEN PAR("TAMAÑO BUFFER (TOG)" - "FLUJO NETO (NFP) AJUSTADO")
END                                                                           AS "PEDIDO AJUSTADO DDMRP",

-- PEDIDO AJUSTADO DDMRP JP = igual, con FLUJO NETO (NFP) AJUSTADO JP
CASE
    WHEN "TAMAÑO BUFFER (TOG)" = 0 AND "FLUJO NETO (NFP) AJUSTADO JP" = 0 THEN 0
    WHEN "TAMAÑO BUFFER (TOG)" >= 0 AND "FLUJO NETO (NFP) AJUSTADO JP" >= 0 AND "FLUJO NETO (NFP) AJUSTADO JP" > "TAMAÑO BUFFER (TOG)" THEN 0
    WHEN "TAMAÑO BUFFER (TOG)" >= 0 AND "FLUJO NETO (NFP) AJUSTADO JP" >= 0 AND "FLUJO NETO (NFP) AJUSTADO JP" < "TAMAÑO BUFFER (TOG)"
        THEN PAR("TAMAÑO BUFFER (TOG)" - "FLUJO NETO (NFP) AJUSTADO JP")
END                                                                           AS "PEDIDO AJUSTADO DDMRP JP",


-- @PASO 11 · PEDIDOS AJUSTADOS A 3 MESES
-- PEDIDO ESTANDAR DDMRP AJUS TAMAÑO MAX 3 MESES: el pedido, pero a lo más el tamaño de 3 meses
--   (Excel: =SI(Y(PEDIDO=0; 3 MESES=0); 0; SI(PEDIDO > 3 MESES; 3 MESES; PEDIDO)); si el pedido es "E" queda el de 3 meses)
CASE
    WHEN "PEDIDO ESTANDAR DDMRP" = 0 AND "TAMAÑO 3 MESES SEGÚN MAX ADU" = 0 THEN 0
    WHEN "PEDIDO ESTANDAR DDMRP" IS NULL OR "PEDIDO ESTANDAR DDMRP" > "TAMAÑO 3 MESES SEGÚN MAX ADU"
        THEN "TAMAÑO 3 MESES SEGÚN MAX ADU"
    ELSE "PEDIDO ESTANDAR DDMRP"
END                                                                           AS "PEDIDO ESTANDAR DDMRP AJUS TAMAÑO MAX 3 MESES",

-- PEDIDO AJUSTADO DDMRP AJUS TAMAÑO MAX 3 MESES: igual, con el PEDIDO AJUSTADO DDMRP
CASE
    WHEN "PEDIDO AJUSTADO DDMRP" = 0 AND "TAMAÑO 3 MESES SEGÚN MAX ADU" = 0 THEN 0
    WHEN "PEDIDO AJUSTADO DDMRP" IS NULL OR "PEDIDO AJUSTADO DDMRP" > "TAMAÑO 3 MESES SEGÚN MAX ADU"
        THEN "TAMAÑO 3 MESES SEGÚN MAX ADU"
    ELSE "PEDIDO AJUSTADO DDMRP"
END                                                                           AS "PEDIDO AJUSTADO DDMRP AJUS TAMAÑO MAX 3 MESES",
