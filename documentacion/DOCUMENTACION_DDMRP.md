# Documentación técnica – Proceso DDMRP del Grupo Vii

> Actualizada al **23/11/2026**, a partir del código actual.
> La misma lógica está en dos carpetas: `Documents\Scripts\DDMRP` (trabajo) y
> `Documents\GitHub\DDMRP_consolidado` (repositorio). Ver [Las dos carpetas](#13-ejecutar-y-mantener).
> La versión completa, con ejemplos, diagramas y las consultas de las vistas, es **`DOCUMENTACION_DDMRP.html`**
> (en Scripts también está en PDF).

---

## Índice

1. [En un minuto](#1-en-un-minuto)
2. [Glosario](#2-glosario)
3. [Reportes y el .bat](#3-reportes-y-el-bat)
4. [Flujo de ejecución](#4-flujo-de-ejecución)
5. [Importador y comercializador (homologaciones)](#5-importador-y-comercializador-homologaciones)
6. [Tablas resumen](#6-tablas-resumen)
7. [Vistas PostgreSQL](#7-vistas-postgresql)
8. [Cálculo en el master (`master_llantas.py`)](#8-cálculo-en-el-master-master_llantaspy)
9. [Reportes en Excel](#9-reportes-en-excel)
10. [Consolidado v1 (programa con ventana)](#10-consolidado-v1-programa-con-ventana)
11. [Parámetros](#11-parámetros)
12. [Observaciones y pendientes](#12-observaciones-y-pendientes)
13. [Ejecutar y mantener](#13-ejecutar-y-mantener)

---

## 1. En un minuto

Para cada ítem de llantas de cada empresa del grupo se calcula cuánto se vende por día (ADU), cuánto tarda
en llegar la mercadería (DLT), el buffer (zonas roja, amarilla y verde), el flujo neto y cuánto hay que pedir.

- Todo se corre con **`DDMRP.bat`** (menú de 4 opciones, ver [sección 3](#3-reportes-y-el-bat)).
- **Normal:** `master_llantas.py` → `core.ddmrp_llantas` (una fila por ítem).
- **Mensualizado:** `llantas_mes.py` → `core.ddmrp_llantas_mes`.
- **Consolidado:** `ddmrp_consolidado.py` → `core.ddmrp_llantas_consolidado` (une los dos anteriores).
- **Consolidado v1:** programa con ventana, solo lectura (`consolidado_v1\`).

Pasos: **1. Leer datos** (SAP HANA y DWH) → **2. Resumir** (7 tablas resumen) → **3. Calcular** (fórmulas
en orden) → **4. Reportar** (un Excel por tabla).

| Dato | Valor |
|---|---|
| Ítems calculados | 5,723 llantas activas de compra (13/11/2026) |
| Empresas | 5: AUTOLLANTA · MAXXIMUNDO · STOX · IKONIX · AUTOMAX |
| Ventana de análisis | 365 días, y 90 días para la demanda reciente |
| Homologaciones | 3: ROADWING pesado · CST moto · marcas de IKONIX |

---

## 2. Glosario

| Término | Significado |
|---|---|
| **ADU** (Average Daily Usage) | Venta promedio por día = ventas ÷ días con inventario. Las fórmulas usan el ADU **con picos**; ADU SIN PICOS es solo referencia. |
| **DLT** (Decoupled Lead Time) | Días que tarda en llegar un pedido del proveedor. |
| **LTF** (Lead Time Factor) | Factor según el DLT: plazos cortos más seguridad (0.6), largos menos (0.2). |
| **CV · VF** | Qué tan irregular es la venta. Más irregular = más seguridad (VF 0.2 / 0.4 / 0.6). |
| **TOR** (ZONA ROJA) | Stock de seguridad. |
| **TOY** (LIMITE ZONA AMARILLA) | Seguridad + la demanda mientras llega el pedido. |
| **TOG** (TAMAÑO BUFFER) | Nivel máximo: hasta aquí se llena cuando se pide. |
| **NFP** (FLUJO NETO) | Posición del ítem para compararla con el buffer. |
| **Pico** | Día de venta muy por encima de lo normal (Z modificado > 4). No se quita del ADU que usan las fórmulas. |
| **Días con inventario** | Días con **4 o más unidades** en al menos una bodega de venta (`inv_stock > 3`). |
| **Importador / comercializador** | Empresa que compra al proveedor / empresa que vende. |

---

## 3. Reportes y el .bat

`DDMRP.bat` muestra un menú; también se le puede pasar el número (`DDMRP.bat 4`) para el Programador de
tareas. Cada opción corre primero las 7 tablas resumen y luego su cálculo y su Excel. Si un paso falla, se
detiene y muestra dónde (archivo, línea y error).

| Opción | Reporte | Scripts | Tabla | Excel (`REPORTES DDMRP\DD-MM-AAAA\`) |
|---|---|---|---|---|
| 1 | DDMRP LLANTAS (normal) | `master_llantas.py` + `export_excel_llantas.py` | `core.ddmrp_llantas` | Reporte de Pedidos (NEUMATICOS) (TODAS) (DD-MM-AAAA).xlsx |
| 2 | DDMRP LLANTAS MENSUALIZADO | `llantas_mes.py` + `export_excel_llantas_mes.py` | `core.ddmrp_llantas_mes` | Reporte de Pedidos Mensualizado (…).xlsx |
| 3 | DDMRP LLANTAS CONSOLIDADO | `ddmrp_consolidado.py` + `export_excel_consolidado.py` | `core.ddmrp_llantas_consolidado` | Reporte de Pedidos Consolidado (…).xlsx |
| 4 | TODOS | 1, 2 y 3 seguidos | las 3 | los 3 |

- **Normal:** el cálculo de la [sección 8](#8-cálculo-en-el-master-master_llantaspy). Solo entran ítems
  `ACTIVO = 'SI'`, `ARTICULO_COMPRA = 'Y'` y grupo `LLANTAS` o `LLANTAS MOTO` (filtro en la consulta base).
- **Mensualizado:** fórmulas del Excel *DDMRP_GRUPOVI_LLANTAS_V16*. Pide para tener en piso a lo más
  **3 meses** (CLASIF. PARETO A o B) o **2 meses** (el resto), más lo que cubre el DLT (meses de 30 días).
  Mismas tablas resumen y mismo filtro de ítems. Las homologaciones están en la lista `HOMOLOGACIONES`.
- **Consolidado:** une el normal y el mensualizado con las columnas y el orden de *REORDENADO_UNIFICADO.xlsx*.
  **No tiene fórmulas propias:** calcula los dos modelos en tablas temporales con los mismos datos y toma cada
  columna del que corresponde (lista `COLUMNAS`). No toca `core.ddmrp_llantas` ni `core.ddmrp_llantas_mes`.

**Carpetas que se crean solas** (no se copian ni se suben a GitHub):

- `logs\`: la crea el .bat. `log_actualizacion_ddmrp.txt` (historial) y `_ultimo_paso.txt` (último script).
- `REPORTES DDMRP\DD-MM-AAAA\`: la crea cada exportador. Hay **una carpeta por día** de ejecución.

Las tablas resumen se **borran y se vuelven a cargar** en cada corrida (`TRUNCATE` + `INSERT`), salvo
`ddmrp_proveedores_dlt`, que solo se actualiza.

---

## 4. Flujo de ejecución

```
Datos de origen                Tablas resumen (en orden)            Cálculo                    Resultado
SAP HANA (OITM/OITW/OITG) ──┐  1 ddmrp_bodega        stock actual    master_llantas.py ──────→ core.ddmrp_llantas
hec_ventas                  │  2 ddmrp_inventario    días con stock  llantas_mes.py ─────────→ core.ddmrp_llantas_mes
hec_inventario              ├→ 3 ddmrp_ventas_picos  ADU, CV, VF  →  ddmrp_consolidado.py ───→ core.ddmrp_llantas_consolidado
hec_transitos / reservas    │  4 ddmrp_proveedores_dlt DLT max/min   + vw_ddmrp_ventas         export_excel_*.py → Excel
dim_item · parámetros ──────┘  5 ddmrp_proveedor_item proveedor 1/2  + vw_ddmrp_trans_ped
                               6 ddmrp_medidas_top   TOP
                               7 ddmrp_abc           pareto
```

- Si falla cualquiera de las tablas resumen, se registra el error, **no** se actualiza la tabla final y el
  proceso termina con código 1.
- Cada carga es **una sola transacción**: si algo falla, la tabla conserva la corrida anterior.
- Patrón de carga: `CREATE TABLE IF NOT EXISTS` → `ALTER TABLE … ADD COLUMN IF NOT EXISTS` (las columnas nuevas
  quedan al final; para que salgan en su lugar hay que hacer `DROP TABLE` antes) → `TRUNCATE` → `INSERT`.
- `ddmrp_proveedores.py` (DLT anterior, por PI) está comentado y ya no corre.

---

## 5. Importador y comercializador (homologaciones)

Cada marca se planifica en una sola empresa; si otra la compra, vende o guarda, sus datos pasan a la que planifica.

| De | A | Qué | Cómo |
|---|---|---|---|
| STOX | AUTOLLANTA | ROADWING, propiedad ROADWING PESADO | por nombre (ej. ST_2001114 → AU_2003841) |
| MAXXIMUNDO | STOX | CST, grupo LLANTAS MOTO | por nombre (ej. MA_2000236 → ST_2000028) |
| MAXXIMUNDO | IKONIX | UYUSTOOLS · SATA · DONG CHEN (al revés: planifica IKONIX) | por marca → proveedor de MAXXIMUNDO |

| Dato | Dónde | Cómo se pasa |
|---|---|---|
| Ventas (UN AÑO, 90D, MES, pico, última venta) | `vw_ddmrp_ventas` | se mueven; el origen queda sin ellas |
| ADU, ADU sin picos, CV, VF y sus días | `ddmrp_ventas_picos.py` | las ventas diarias se suman al destino |
| Stock (EN STOCK) | `ddmrp_bodega.py` | se suma al destino; **el origen lo conserva** |
| DIAS INV 1 AÑO / 90D | master `[H1]` | el destino toma los del origen |
| P. LISTA | master `[H2]` | el destino toma el del origen (solo ROADWING) |
| DLT y proveedor (IKONIX) | master `[8]` · `ddmrp_proveedor_item.py` | por marca (`MARCA_PROVEEDOR_IKONIX`) |

AUTOMAX se planifica por separado con sus propias ventas y stock.

---

## 6. Tablas resumen

Carpeta `tablas_resumen\`. Cada script prepara una tabla que después usan los cálculos.

| Script → tabla | Origen | Qué calcula | Lo usa |
|---|---|---|---|
| `ddmrp_bodega.py` → `core.ddmrp_bodegas` | SAP HANA | Stock actual en las bodegas de venta (+ homologación del stock) | EN STOCK |
| `ddmrp_inventario.py` → `core.ddmrp_inventario` | `hec_inventario` | Días del año y de 90 días en que alguna bodega de venta tuvo 4 o más unidades (`inv_stock > 3`, por bodega, no sobre la suma) | DIAS INV 1 AÑO / 90D, divisor del ADU |
| `ddmrp_ventas_picos.py` → `core.ddmrp_ventas_picos` | `hec_ventas` | Venta por día, picos (Z modificado), ADU con y sin picos, CV y VF. Últimos 365 días, sin PPTO, solo EQUIPO DE MAYOREO y B2B, sin 4 clientes relacionados | ADU, ADU SIN PICOS, VF |
| `ddmrp_proveedores_dlt.py` → `core.ddmrp_proveedores_dlt` | tabla cargada a mano (29 proveedores) | DLT MAX = confirmación + producción + backorder + booking + tránsito + aduana; DLT MIN = sin backorder | DLT |
| `ddmrp_proveedor_item.py` → `core.ddmrp_proveedor_item` | `dim_item`, importaciones | Proveedor 1 y 2 con nombre (IKONIX por marca) | COD. PROV1/2, PROV1/2 |
| `ddmrp_medidas_top.py` → `core.ddmrp_medidas_top` | `core.ddmrp_medidastop` | TOP = 'SI' si la descripción tiene una medida TOP | TOP |
| `ddmrp_abc.py` → `core.ddmrp_abc` | `hec_ventas` | Score 20 % unidades + 30 % venta + 50 % utilidad: A hasta 80 %, B hasta 95 %, C el resto; nuevo → C; venta ≤ 0 → D | CLASIF. PARETO |

**Picos y ADU** (`ddmrp_ventas_picos`): `Z = 0.6745 × (venta del día − mediana) ÷ MAD`; pico si |Z| > 4 (parámetro 13).
`ADU_CON_PICOS = ventas del año ÷ días con inventario` (el que usan las fórmulas);
`ADU_SIN_PICOS` descuenta los picos altos. CV: el año en 12 tramos de ~30 días (sin días pico alto),
`CV = desviación ÷ promedio`; con menos de 3 tramos o sin venta → no medible (CV 0).

---

## 7. Vistas PostgreSQL

| Vista | Qué da | Columnas en la tabla final |
|---|---|---|
| `core.vw_ddmrp_ventas` | Ventas por empresa + ítem (365 días, 90 días, mes actual, mayor línea, última venta), con las homologaciones y lubricantes a volumen | UN (#) - AÑO, UN (#) - 90D, UNIDADES MES ACTUAL, PICO ULT. AÑO X FACTURA, DIF. MAX AÑO vs TOT. AÑO (> 40 %), ULTIMA VENTA |
| `core.vw_ddmrp_trans_ped` | Tránsitos (`hec_transitos`), pedidos y backorders (`hec_facturas_reserva`) abiertos, por tramos de días | TRANSITOS, Pedidos, Backorders y sus tramos |
| `core.vw_ddmrp_item_proveedor` | Proveedor principal del ítem | para buscar el DLT |

Las consultas completas de las vistas están en el HTML.

---

## 8. Cálculo en el master (`master_llantas.py`)

`master_llantas.py` → `core.ddmrp_llantas`. Una fila por ítem de `dim_item` que sea llanta (LLANTAS o
LLANTAS MOTO), activa y de compra. Primero se carga la tabla base (`SQL_DDMRP`) y luego los pasos de la lista
`PASOS`, en orden. En el código cada fórmula tiene su número: buscar `[n]`.

**A · Días con inventario**

| Paso | Columna | Cálculo |
|---|---|---|
| H1 | DIAS INV 1 AÑO · 90D | El importador toma los días del comercializador (AUTOLLANTA ← STOX ROADWING PESADO; STOX ← MAXXIMUNDO CST moto) |
| H3 | DIAS INV 1 AÑO · 90D | Si EN STOCK > 4, cada una que esté en 0 pasa a 1 |

**B · Stock y demanda**

| Paso | Columna | Cálculo |
|---|---|---|
| 1 | TOP | de `ddmrp_medidas_top` |
| 2 | STOCK TOTAL | EN STOCK + TRANSITOS TOTAL + PEDIDOS + BACKORDERS |
| 3 | DEMANDA MES - AÑO | UN (#) - AÑO ÷ DIAS INV 1 AÑO × 30 |
| 4 | DEMANDA MES 90D | UN (#) - 90D ÷ DIAS INV 90D × 30 |
| 5 | % VARIACIÓN DEMANDA | (demanda diaria 90D ÷ demanda diaria del año − 1) × 100 |
| 6 | MES INV TOTAL SEGUN DEMANDA 90D | STOCK TOTAL ÷ DEMANDA MES 90D · 9999 si no vendió y tiene stock |
| 12 | ADU · ADU SIN PICOS | de `ddmrp_ventas_picos` (los cálculos usan el ADU con picos) |
| 13 | STOCK PROYECTADO DLT | STOCK TOTAL − DLT × ADU |

**C · Lead time y variabilidad**

| Paso | Columna | Cálculo |
|---|---|---|
| 7 | DLT | del proveedor principal: DLT MAX si tiene BACKORDERS, si no DLT MIN |
| 8 | DLT (IKONIX) | del proveedor que le toca por marca |
| 9 | DLT (si quedó en 0) | promedio del DLT de la misma marca |
| 10 · 11 | VF | según el CV: ≤ 0.5 → 0.2 · ≤ 1 → 0.4 · > 1 → 0.6 · si quedó en 0 → 0.20 |
| 14 · 15 | LTF | según el DLT: ≤ 60 → 0.6 · ≤ 100 → 0.4 · > 100 → 0.2 · si quedó en 0 → 0.20 |

**D · Buffer**

| Paso | Columna | Cálculo |
|---|---|---|
| 16 | ZONA ROJA BASE | ADU × DLT × LTF |
| 17 | ZONA ROJA SEGURIDAD | ZONA ROJA BASE × VF |
| 18 | ZONA ROJA (TOR) | BASE + SEGURIDAD |
| 19 | ZONA AMARILLA | ADU × DLT |
| 20 | LIMITE ZONA AMARILLA (TOY) | TOR + ZONA AMARILLA |
| 21 | ZONA VERDE | MAX(ADU × 30 ; ZONA ROJA BASE) |
| 22 | TAMAÑO BUFFER (TOG) | TOY + ZONA VERDE |

**E · Pedido**

| Paso | Columna | Cálculo |
|---|---|---|
| 23 | FLUJO NETO (NFP) | STOCK TOTAL − ADU × DLT |
| 24 | TAMAÑO PEDIDO | TOG − NFP si NFP ≤ TOG; si no 0 |
| 25 | NUEVO TAMAÑO PEDIDO | 0 si MES INV TOTAL > 4; si no TAMAÑO PEDIDO al par de arriba |
| 26 | TAMAÑO 3 MESES INVENTARIO | ADU × 90 |
| JP | NFP JP | par(STOCK TOTAL − ADU × DLT ÷ 3) |
| JP | PROD SIN VENTAS SIN STOCK | 'REVISAR' si TAMAÑO PEDIDO = 0 y STOCK TOTAL = 0, si no '0' |
| JP | PROD CON STOCK SIN VENTAS | 'LIQUIDAR' si TAMAÑO PEDIDO = 0 y STOCK PROYECTADO DLT ≠ 0, si no '0' |
| JP | VALIDADOR | TAMAÑO PEDIDO |
| JP | PEDIDO SUGERIDO JP | par(TOG) si VALIDADOR > 0 y NFP JP ≤ 0 · par(TOG − NFP JP) si TOG > 0 y NFP JP < TOG · '0' en otro caso. **Usa el TOG desde el 09/11/2026** (antes TAMAÑO PEDIDO, y el último caso daba 'REVISAR') |
| OBS | OBSERVACIONES | 'INACTIVAR' · 'LIQUIDAR' · '-' (último paso) |

**F · Costos e información:** ULTIMO FOB, COSTO PROM, ULT. COSTO, P. LISTA (`dim_item`; AUTOLLANTA toma el P. LISTA
de STOX en ROADWING PESADO), P. LISTA VS ULT.COSTO, proveedor 1 y 2, ULTIMA VENTA, ULTIMA COMPRA.

Excel de JP: `=SI(Y(BO2>0;BL2<=0);REDONDEA.PAR(BG2);SI(Y(BG2>0;BL2<BG2);REDONDEA.PAR(BG2-BL2);SI(Y(BG2>0;BL2>BG2);0;0)))`
(BG = TOG, BL = NFP JP, BO = VALIDADOR). `par()` = `REDONDEA.PAR`.

Para calcular con el ADU sin picos: en `SQL_ADU` (paso 12) cambiar `"ADU_CON_PICOS" AS adu` por `"ADU_SIN_PICOS" AS adu`.

---

## 9. Reportes en Excel

Los tres exportadores buscan las columnas por **nombre** (no por letra) y crean la carpeta del día.

| Script | Formato | Qué exporta |
|---|---|---|
| `export_excel_llantas.py` | *Manual Formato de Reporte de DDMRP* | `core.ddmrp_llantas`, MES INV 9999 → INFINITO, ordenado por BARRAS |
| `export_excel_llantas_mes.py` | *DDMRP_GRUPOVI_LLANTAS_V16* | `core.ddmrp_llantas_mes` |
| `export_excel_consolidado.py` | *REORDENADO_UNIFICADO.xlsx* | `core.ddmrp_llantas_consolidado` |

Colores de fila (el último gana): **naranja** DIAS INV 90D < 68 · **rojo** además DIAS INV 1 AÑO < 275 ·
**verde** DIF. MAX AÑO vs TOT. AÑO = SI. Encima van los colores de columna. Cada Excel lleva la hoja
EXPLICACIÓN COLORES, columnas ocultas y grupos (+ / −).

---

## 10. Consolidado v1 (programa con ventana)

Carpeta `consolidado_v1\`. Hace **todos los cálculos** del Excel *Reporte de Pedidos Consolidado (final,
revisado 12-11-2026)* (95 columnas) en una sola consulta y los muestra en una ventana. Es de **solo lectura**:
no crea ni cambia tablas en el DWH. Lee las tablas resumen tal como están, así que conviene correr antes el
.bat (opción 4). Necesita `PySide6-Essentials` (está en `requirements.txt`).

```
C:\Users\plituma\Documents\Scripts\.venv\Scripts\python.exe consolidado_v1\ddmrp_consolidado_v1.py
```

| Archivo | Qué tiene |
|---|---|
| `ddmrp_consolidado_v1.py` | Se ejecuta este. Filtros del DDMRP, consulta de origen (`SQL_ITEMS`), columnas en el orden del Excel, grupos, ocultas, colores de fila, indicadores, filtros de la ventana y las 24 fórmulas del *Excel de validación* (`FORMULAS_EXCEL_VALIDACION`) |
| `formulas_ddmrp_v1.sql` | **Todas las fórmulas** (62, en 11 pasos), una por columna. **Aquí se cambia un cálculo.** |
| `ddmrp_v1_motor.py` | Arma la consulta de solo lectura (`WITH paso_0 AS MATERIALIZED (…) …`); cambia `PAR(x)` por REDONDEA.PAR. No se toca. |
| `ddmrp_v1_ventana.py` | La ventana (Qt / PySide6). |
| `ddmrp_v1_legible.py` | Pestaña Cálculos: muestra cada fórmula del .sql como fórmula de Excel. Solo muestra. |
| `ddmrp_v1_excel.py` | Botones *Exportar a Excel* y *Excel de validación*. |

**Cómo cambiar una fórmula:** abrir `formulas_ddmrp_v1.sql` (cada paso empieza con `-- @PASO n · TÍTULO`; cada
fórmula termina en `AS "COLUMNA",`; las líneas `--` son la explicación), cambiar solo esa fórmula (puede usar
columnas de pasos **anteriores**; el diccionario Excel → SQL está al inicio del archivo) y en la ventana dar
**⟳ Actualizar datos**. Si hay un error, lo dice con el número de línea y deja los datos de antes. Se calcula
con **todos los decimales**; el selector *Decimales* solo cambia cómo se ve.

**La ventana:**
- Barra de arriba: *DATOS AL* (fecha y hora de la lectura), *Actualizar datos* y filtros fijos.
- *Datos del ítem*: indicadores (ítems mostrados, con pedido a piso, PEDIDO AJUSTADO DDMRP, PEDIDO AJUSTADO
  DDMRP JP, PEDIDO SUGERIDO AJUSTADO A PISO), buscador, 8 filtros (activos en amarillo), columnas ancladas hasta
  `ANT.`, grupos `[+]`/`[-]`, colores de fila, ordenar con clic en el encabezado.
- *Filtros*: embudo de los filtros fijos, filtros puestos (✕ para quitar) y la consulta SQL para pgAdmin.
- *Cálculos*: cada columna con explicación, fórmula estilo Excel, **ejemplo con los valores de un ítem**, qué
  usa y dónde se usa.

**Exportar a Excel:** guarda lo que se ve (filtros y orden) con el formato del Excel final (SUBTOTAL en la fila 1,
colores, grupos, anclado hasta `ANT.`, hoja EXPLICACIÓN COLORES con la fecha de los datos).

**Excel de validación:** las 24 columnas que en el Excel original son fórmulas van como fórmulas de Excel, más las
hojas VALIDACIÓN (OK / DIF) y VALORES PROGRAMA. Prueba del 13/11/2026 (5,723 ítems): 21 columnas iguales; las 73
diferencias son de `REDONDEA.PAR` en Excel, que da 2 unidades más por su redondeo interno.

**Pendientes del v1:** quitar el `ROUND(…, 2)` de costos y DLT promedio en `SQL_ITEMS`; CV/ADU con 2 decimales en
`ddmrp_ventas_picos` (28 ítems con CV en 0.50 / 1.00); observaciones de las fórmulas del Excel (MESES X PEDIR
PARA PISO con stock de sobra, zonas con ADU BASE y ADU 90 DÍAS, casos "E" / #¡VALOR!); guardar tabla en el DWH
cuando se dé por lista.

---

## 11. Parámetros

En `core.ddmrp_parametros` (se cambian ahí, sin tocar código).

| id | Parámetro | Valor | Para qué |
|---|---|---|---|
| 1 | Ventas 1 año | 365 | ventana anual |
| 2 | Venta 90 días | 90 | ventana corta |
| 3 | Ciclo de pedido | 30 | zona verde |
| 4 · 5 · 6 | LTF bajo · medio · alto | 0.2 · 0.4 · 0.6 | DLT > 100 · 61–100 · ≤ 60 |
| 7 · 8 · 9 | VF bajo · medio · alto | 0.2 · 0.4 · 0.6 | CV ≤ 0.5 · ≤ 1 · > 1 |
| 13 | Umbral de pico | 4 | \|Z\| > 4 = pico |
| 14 | Constante Z | 0.6745 | Z modificado |

Valores escritos en el código: `inv_stock > 3` (ddmrp_inventario), `EN STOCK > 4` (master [H3]), 60 / 100 días
(tramos del LTF), 4 meses y 90 días (NUEVO TAMAÑO PEDIDO, TAMAÑO 3 MESES), 40 % (vista de ventas),
3 / 2 meses en piso (mensualizado).

---

## 12. Observaciones y pendientes

1. **El FLUJO NETO resta la demanda del lead time** (negocio): ya está en la zona amarilla, se cuenta dos veces.
2. **LIQUIDAR marca también ítems que sí venden** (negocio): conviene agregar ADU = 0 si debe ser "sin ventas".
3. **Regla de disparo del pedido** (negocio): se pide con NFP ≤ TOG; en DDMRP es NFP ≤ TOY.
4. **Picos por día** (negocio): en venta irregular se marcan como pico muchas ventas normales.
5. **Ventas duplicadas por nombres repetidos** en `vw_ddmrp_ventas` (técnico).
6. **Ítems que venden con DLT 0** (dato): su proveedor no tiene tiempos cargados.
7. **Stock homologado contado dos veces** (técnico): el comercializador conserva el stock.
8. **Regla CST distinta según el archivo** y **9 ítems CST moto sin ítem en STOX** (dato).
9. **DONG CHEN no existe en dim_item** y el mapa de IKONIX la tiene como `DONGCHENG` (dato).
10. **Solo 29 proveedores con DLT** (dato); **VF de ítems no medibles** termina en 0.20 (técnico).
11. **Dos reglas de "4 unidades"** que no coinciden (`inv_stock > 3` por bodega vs `EN STOCK > 4` en la suma).
12. **365 frente a 366 días** entre la vista de ventas y el ADU; **lubricantes** en volumen vs unidades.
13. **ULTIMA COMPRA en 01/01/2017** en ~7,100 ítems; **bodegas de IKONIX** y **50 TRANSITO** de AUTOLLANTA no
    entra en EN STOCK; **tránsitos viejos de IKONIX**; **AUTOLLANTA guarda stock de otras marcas**.
14. Pendientes del consolidado v1: ver la [sección 10](#10-consolidado-v1-programa-con-ventana).

El detalle de cada punto, con ejemplos, está en el HTML.

---

## 13. Ejecutar y mantener

```
DDMRP.bat                 (menú 1 · 2 · 3 · 4)
DDMRP.bat 4               (todo, sin preguntar: para el Programador de tareas)
C:\Users\plituma\Documents\Scripts\.venv\Scripts\python.exe master_llantas.py
C:\Users\plituma\Documents\Scripts\.venv\Scripts\python.exe consolidado_v1\ddmrp_consolidado_v1.py
```

### Las dos carpetas

| | `Scripts\DDMRP` (trabajo) | `GitHub\DDMRP_consolidado` (repositorio) |
|---|---|---|
| Lógica | La misma: scripts, fórmulas, tablas resumen, .bat y consolidado v1 | igual |
| Rutas | Exportadores y ventana v1 guardan en `C:\Users\plituma\Documents\Scripts\DDMRP\REPORTES DDMRP`; el .bat usa esa carpeta fija | Todo es relativo a la carpeta del proyecto (el .bat usa `%~dp0`) |
| Conexión | Tablas resumen y cálculos: `conection\config.py`. Exportadores: `C:\Users\plituma\Documents\Scripts\config.py` | Todo usa `conection\config.py` (no se sube: se crea copiando `config_example.py`) |
| Librerías | `requirements.txt` (incluye SQLAlchemy y PySide6-Essentials) | igual |
| No se copian | `logs\`, `REPORTES DDMRP\` (se crean solas, están en `.gitignore`), `__pycache__`, `consolidado_v1\ddmrp_v1_ventana_tk.py` (respaldo, solo en Scripts) | |

### ¿Dónde cambio…?

| Quiero… | Dónde |
|---|---|
| Agregar o mover una columna | `SQL_DDMRP` o `COLUMNAS_CALCULADAS` en `master_llantas.py` (o `llantas_mes.py`), y luego `DROP TABLE core.ddmrp_llantas;` (o `core.ddmrp_llantas_mes`) |
| Agregar una fórmula | Un bloque `SQL_…` y una línea en `PASOS` (si no está en `PASOS`, no se calcula) |
| Cambiar una fórmula del consolidado v1 | `consolidado_v1\formulas_ddmrp_v1.sql` y botón *Actualizar datos* |
| Cambiar columnas, grupos, colores o filtros de la ventana v1 | sección 3 de `consolidado_v1\ddmrp_consolidado_v1.py` |
| Cambiar qué columnas toma el consolidado de cada modelo | lista `COLUMNAS` en `ddmrp_consolidado.py` |
| Agregar una homologación | vista de ventas · `HOMOLOGACIONES` en ventas_picos · `ddmrp_bodega.py` · pasos `[H1]`/`[H2]` del master |
| Cambiar días, factores o umbral | `core.ddmrp_parametros` |
| Agregar un proveedor con DLT | cargar sus tiempos en `core.ddmrp_proveedores_dlt` |
| Cambiar el formato de un Excel | bloques de configuración al inicio de `export_excel_llantas.py` / `_llantas_mes.py` / `_consolidado.py` |
| Agregar un reporte al .bat | `call :run_step "NOMBRE" "archivo.py" \|\| goto :fin_error` en la opción que corresponda |

**Errores comunes:** *column "…" specified more than once* (dos columnas con el mismo nombre en `SQL_DDMRP`);
*function … does not exist* (una función de Excel o un error de tipeo; las columnas se suman con `+`);
columna nueva vacía (su fórmula no está en `PASOS`).
