# Documentación técnica – Proceso DDMRP

> Carpeta: `Documents/Scripts/DDMRP`
> Documento generado a partir del código de los scripts, de las vistas de PostgreSQL que usan
> (`pg_get_viewdef`) y de la tabla `core.ddmrp_parametros` (valores vigentes al 27/09/2026).
> Los ejemplos numéricos son datos reales de `core.ddmrp` (ítem `MA_2000050`).

---

## Índice

1. [Visión general y flujo](#1-visión-general-y-flujo)
2. [Parámetros (`core.ddmrp_parametros`)](#2-parámetros-coreddmrp_parametros)
3. [`conection/config.py`](#3-conectionconfigpy)
4. [`ddmrp_bodega.py` → `core.ddmrp_bodegas`](#4-ddmrp_bodegapy--coreddmrp_bodegas)
5. [`ddmrp_inventario.py` → `core.ddmrp_inventario`](#5-ddmrp_inventariopy--coreddmrp_inventario)
6. [`ddmrp_ventas_picos.py` → `core.ddmrp_ventas_picos`](#6-ddmrp_ventas_picospy--coreddmrp_ventas_picos)
7. [`ddmrp_proveedores.py` → `core.ddmrp_proveedores`](#7-ddmrp_proveedorespy--coreddmrp_proveedores)
8. [Vistas de PostgreSQL usadas por el master](#8-vistas-de-postgresql-usadas-por-el-master)
9. [`master.py` → `core.ddmrp` (tabla final, campo por campo)](#9-masterpy--coreddmrp-tabla-final-campo-por-campo)
10. [Ejemplo completo paso a paso (MA_2000050)](#10-ejemplo-completo-paso-a-paso-ma_2000050)
11. [Observaciones y puntos a revisar](#11-observaciones-y-puntos-a-revisar)

---

## 1. Visión general y flujo

El proceso calcula, para cada ítem de cada empresa del grupo, el **buffer DDMRP** (zonas roja,
amarilla y verde), la **posición de flujo neto (NFP)** y el **pedido sugerido**.

### Orígenes de datos

| Origen | Motor | Qué se lee |
|---|---|---|
| SAP Business One | SAP HANA | Stock actual por bodega (`OITM`, `OITW`) |
| DWH | SQL Server | Historial diario de existencias (`dbo.hec_existencias`, `dbo.dim_bodegas`) |
| dwh | PostgreSQL | Ventas, importaciones, pedidos, tránsitos, facturas reserva, maestro de ítems, parámetros |

### Orden de ejecución (`master.py`)

```
master.py
 │
 ├─ 1. ddmrp_bodega.ejecutar()        HANA        → core.ddmrp_bodegas        (stock actual)
 ├─ 2. ddmrp_inventario.ejecutar()    SQL Server  → core.ddmrp_inventario     (días con stock)
 ├─ 3. ddmrp_ventas_picos.ejecutar()  PostgreSQL  → core.ddmrp_ventas_picos   (ADU, VF, picos)
 ├─ 4. ddmrp_proveedores.ejecutar()   PostgreSQL  → core.ddmrp_proveedores    (lead times, DLT)
 │
 │   Si CUALQUIERA de los 4 falla → se registra el error, NO se actualiza core.ddmrp y sale con código 1.
 │
 └─ 5. cargar_ddmrp()                 PostgreSQL  → core.ddmrp                (tabla final)
        ├─ INSERT con SQL_DDMRP (datos base + DLT + VF)
        ├─ UPDATE ADU          (desde ddmrp_ventas_picos)
        ├─ UPDATE LTF          (tramo del DLT)
        ├─ UPDATE ZONA ROJA BASE → ZONA ROJA SEGURIDAD → TOR
        ├─ UPDATE ZONA AMARILLA → TOY
        ├─ UPDATE ZONA VERDE → TOG
        └─ UPDATE NFP → PEDIDO SUGERIDO
```

### Patrón de carga común a todos los scripts

Todos los scripts siguen el mismo patrón:

1. `CREATE TABLE IF NOT EXISTS` (crea la tabla solo si no existe).
2. `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (en los que lo tienen: agrega columnas nuevas sin borrar la tabla).
3. `TRUNCATE` (borra todos los registros).
4. `INSERT` masivo (`execute_values`, páginas de 5.000 filas).

Todo dentro de **una sola transacción** (`with conn:`): si algo falla, se hace rollback y la tabla
queda con los datos de la corrida anterior (nunca vacía).

Cada script puede ejecutarse solo (`python ddmrp_xxx.py`) o desde el master.

---

## 2. Parámetros (`core.ddmrp_parametros`)

Tabla de configuración. Los scripts leen `ddmrp_valor_num` **solo de los registros con
`ddmrp_estado = 1`**; si falta un parámetro activo, el script lanza `ValueError` y se detiene.
(Excepción: la vista `vw_ddmrp_ventas` no filtra por estado y usa 365/90 por defecto si no encuentra el valor;
`master.py` tampoco filtra por estado al leer los ids 3, 4, 5 y 6).

| id | Nombre | Valor | Usado en | Para qué |
|---:|---|---:|---|---|
| 1 | Ventas 1 anio | 365 | `ddmrp_inventario.py`, `vw_ddmrp_ventas` | Días de la ventana anual (ventas y días con stock) |
| 2 | Venta 90 dias | 90 | `ddmrp_inventario.py`, `vw_ddmrp_ventas` | Días de la ventana corta |
| 3 | Ciclo Pedido | 30 | `master.py` (ZONA VERDE) | Días del ciclo de pedido (Order Cycle) |
| 4 | LTF bajo | 0.2 | `master.py` (LTF), `ddmrp_proveedores.py` | Factor de lead time |
| 5 | LTF medio | 0.4 | `master.py` (LTF), `ddmrp_proveedores.py` | Factor de lead time |
| 6 | LTF alto | 0.6 | `master.py` (LTF), `ddmrp_proveedores.py` | Factor de lead time |
| 7 | VF bajo | 0.2 | `ddmrp_ventas_picos.py` | Factor de variabilidad, CV ≤ 0.5 |
| 8 | VF medio | 0.4 | `ddmrp_ventas_picos.py` | Factor de variabilidad, 0.5 < CV ≤ 1 y SKU no medible |
| 9 | VF alto | 0.6 | `ddmrp_ventas_picos.py` | Factor de variabilidad, CV > 1 |
| 10 | Dias Confirmacion Pedido | 3 | `ddmrp_proveedores.py` (DLT) | Días fijos sumados al DLT |
| 11 | Dias Desaduanizacion y Recepcion Bodega | 3 | `ddmrp_proveedores.py` (DLT) | Días fijos sumados al DLT |
| 12 | Dias Cordinacion Booking | 3 | `ddmrp_proveedores.py` (DLT) | Días fijos sumados al DLT |
| 13 | Umbral | 3.5 | `ddmrp_ventas_picos.py`, `ddmrp_proveedores.py` | Umbral de \|Z modificado\| para marcar un pico |
| 14 | Z modificado | 0.6745 | `ddmrp_ventas_picos.py`, `ddmrp_proveedores.py` | Constante del Z modificado (Iglewicz–Hoaglin) |
| 15 | Dias toma datos | 365 | `ddmrp_proveedores.py` | Filtro de antigüedad de facturas reserva |

Constantes que están **en el código** (no en la tabla de parámetros):

| Script | Constante | Valor | Uso |
|---|---|---|---|
| `ddmrp_ventas_picos.py` | `FECHA_DESDE` | 2025-05-01 | Inicio fijo de la extracción de ventas |
| `ddmrp_ventas_picos.py` | `LIMITE_VF_BAJO` / `LIMITE_VF_MEDIO` | 0.5 / 1 | Cortes de CV para elegir el factor VF |
| `ddmrp_ventas_picos.py` | `MESES_VENTANA` | 12 | Meses completos para ADU y CV |
| `ddmrp_ventas_picos.py` | `MIN_MESES_LIMPIOS` | 3 | Mínimo de meses para medir el CV |
| `ddmrp_proveedores.py` | `LIMITE_LTF_BAJO` / `LIMITE_LTF_MEDIO` | 60 / 100 días | Tramos de DLT (columna `ltf` de proveedores) |
| `master.py` | tramos en `SQL_LTF` | 60 / 100 días | Tramos de DLT (columna `LTF` de ddmrp) |
| `vw_ddmrp_ventas` | 0.4 | 40 % | Umbral de `supera_umbral` |
| `ddmrp_ventas_picos.py`, `ddmrp_proveedores.py` | `DECIMALES_Z` | 2 | Redondeo del Z modificado |

---

## 3. `conection/config.py`

Solo define las conexiones; no calcula nada.

| Objeto | Tipo | Destino |
|---|---|---|
| `SQLSERVER` | dict | SQL Server `192.168.0.15:1433`, base `DWH` (driver ODBC "SQL Server") |
| `POSTGRES` | dict | PostgreSQL `192.168.0.89:5432`, base `dwh` |
| `HANA` | dict | SAP HANA `192.168.0.105:30015` |
| `sqlserver_conn_str()` | función | Arma la cadena ODBC `DRIVER=...;SERVER=...;DATABASE=...;UID=...;PWD=...` para `pyodbc` |

Los scripts la importan agregando `DDMRP/conection` al `sys.path`.

---

## 4. `ddmrp_bodega.py` → `core.ddmrp_bodegas`

**Objetivo:** stock físico actual (hoy) de cada ítem, sumando las bodegas de venta de cada empresa.

### 4.1 Configuración de empresas

| Empresa (`codigo`) | Abreviatura | Esquema SAP HANA | Bodegas (`OITW.WhsCode`) |
|---|---|---|---|
| STOX | ST | `SBO_STOX_PROD` | 02, 03, 07, 08, 09, 10 |
| AUTOLLANTA | AU | `SBO_AUTOLLANTA_PROD` | 01, 02, 03, 07, 08, 09, 10 |
| MAXXIMUNDO | MA | `SBO_MAXXIMUNDO_PROD` | 02, 03, 07, 08, 09, 10 |
| IKONIX | IK | `SBO_IKONIX_PROD` | 01, 02, 03, 07, 08, 09, 10 |
| AUTOMAX | ATX | `SBO_AUTOMAX_PROD1` (única con sufijo `PROD1`) | 01, 02, 03, 04, 05 |

### 4.2 Consulta (una por empresa)

```sql
SELECT T0."ItemCode" AS codigo, SUM(T1."OnHand") AS sum
FROM "<esquema>"."OITM" T0
INNER JOIN "<esquema>"."OITW" T1 ON T0."ItemCode" = T1."ItemCode"
WHERE T1."WhsCode" IN (<bodegas de la empresa>)
GROUP BY T0."ItemCode"
```

### 4.3 Campos de `core.ddmrp_bodegas`

| Campo | Tipo | Cálculo |
|---|---|---|
| `codigo` | varchar | `<abreviatura>` + `"_"` + `OITM.ItemCode`. Ej.: ItemCode `2000050` de MAXXIMUNDO → `MA_2000050`. Así coincide con `dim_item.dit_codigo`. |
| `empresa` | varchar | Código de la empresa (`STOX`, `AUTOLLANTA`, …). |
| `sum` | bigint | `SUM(OITW.OnHand)` del ítem en las bodegas listadas. `OnHand` es el stock **físico** (no descuenta lo comprometido `IsCommited` ni suma lo pedido `OnOrder`). Al guardarse como `bigint`, los decimales se redondean. |

- Aparecen todos los ítems que tengan registro en `OITW` para esas bodegas, **incluso con stock 0**.
- Es una foto del momento de la ejecución (no histórico).
- Si una empresa no devuelve filas, se registra un *warning* pero el proceso continúa.

**Uso en master:** `EN STOCK = ddmrp_bodegas.sum` (join por `empresa` + `codigo`).

---

## 5. `ddmrp_inventario.py` → `core.ddmrp_inventario`

**Objetivo:** contar **cuántos días tuvo stock** cada ítem en la ventana de 1 año y en la de 90 días.
Esto se usa después para calcular una demanda "corregida por quiebres de stock" (si un ítem estuvo
sin stock, no pudo venderse; se divide la venta solo entre los días en que sí hubo stock).

### 5.1 Parámetros y fechas

| Variable | Valor | Descripción |
|---|---|---|
| `dias_1anio` | param 1 = 365 | |
| `dias_90d` | param 2 = 90 | |
| `FECHA_CORTE` | `None` | Si se pone una fecha, las ventanas se calculan hacia atrás desde esa fecha. Con `None` = hoy. |
| `HOY` | `FECHA_CORTE` o `date.today()` | |
| `HASTA` | `HOY + 1 día` | Límite superior **exclusivo** (incluye todo el día de corte). |
| `desde_1a` | `HOY − 365 días` | Inicio **inclusivo** ventana anual. |
| `desde_90d` | `HOY − 90 días` | Inicio **inclusivo** ventana 90 días. |
| `FILTRO_EMPRESA`, `FILTRO_ITEM` | `None` | Filtros opcionales para pruebas. |

Bodegas consideradas (`BODEGAS_POR_EMPRESA`, códigos `dim_bodegas.dib_codigobodega`): **las mismas
que en `ddmrp_bodega.py`** (ver 4.1).

### 5.2 Consulta (SQL Server)

```sql
SELECT hex_empresa, hex_identificadoritem,
       COUNT(DISTINCT CAST(hex_fechasubida AS DATE))                    AS dias_stock_1anio,
       COUNT(DISTINCT CASE WHEN hex_fechasubida >= :desde_90d
                           THEN CAST(hex_fechasubida AS DATE) END)      AS dias_stock_90d
FROM DWH.dbo.hec_existencias
WHERE hex_fechasubida >= :desde_1a
  AND hex_fechasubida <  :hasta
  AND hex_stock > 0
  AND EXISTS (SELECT 1 FROM DWH.dbo.dim_bodegas b
              WHERE b.dib_nombreempresa = hex_empresa
                AND b.dib_nombrebodega  = hex_nombrealmacen
                AND ( (b.dib_nombreempresa='MAXXIMUNDO' AND b.dib_codigobodega IN (...)) OR ... ))
GROUP BY hex_empresa, hex_identificadoritem
```

`hec_existencias` es una foto diaria del stock por ítem y almacén (`hex_fechasubida` = fecha de la foto).
El `EXISTS` limita a las bodegas de venta: cruza por **nombre** del almacén con `dim_bodegas` y valida el
**código** de bodega de la empresa.

### 5.3 Campos de `core.ddmrp_inventario`

| Campo | Tipo | Cálculo |
|---|---|---|
| `ddmpr_empresa` | varchar | `hex_empresa`. (Nota: el nombre tiene la errata `ddmpr`; el master la usa igual.) |
| `ddmrp_item` | varchar | `hex_identificadoritem`. En el master se cruza con `dim_item.dit_identificador` (no con `dit_codigo`). |
| `ddmrp_stock_inv_1anio` | double | Número de **días distintos** entre `desde_1a` y `HOY` (ambos incluidos) en que el ítem tuvo `hex_stock > 0` en **al menos una** de las bodegas de venta. |
| `ddmrp_stock_inv_90D` | double | Igual, pero solo días con `hex_fechasubida >= desde_90d`. |

Detalles importantes:

- Basta con que **una** bodega tenga stock > 0 ese día para contar el día (no se suma el stock de las bodegas).
- Los ítems que no tuvieron stock ningún día de la ventana **no aparecen** en la tabla → en el master sus días quedan `NULL` y las demandas mensuales salen 0.
- Como el inicio es inclusivo (`HOY − 365`) y el fin también (`< HOY + 1`), la ventana abarca hasta **366** fechas calendario (y hasta **91** en la de 90 días). El valor real depende de los días en que haya foto cargada en `hec_existencias`.

**Uso en master:** `DIAS INV 1 AÑO`, `DIAS INV 90D` y como divisor de `DEMANDA MES 1 AÑO` / `DEMANDA MES 90D`.

---

## 6. `ddmrp_ventas_picos.py` → `core.ddmrp_ventas_picos`

**Objetivo:** a partir de la venta mensual de cada ítem, detectar meses atípicos (picos) con el
**Z modificado** y calcular el **ADU** (demanda diaria promedio), el **CV** (coeficiente de variación)
y el **VF** (factor de variabilidad).

La tabla tiene **una fila por empresa + ítem + mes**; ADU, CV y VF se repiten en todas las filas del ítem.

### 6.1 Extracción

```sql
SELECT hev_empresa, hev_codigoitem,
       date_trunc('month', hev_fechadocumento)::date AS mes,
       ROUND(SUM(hev_cantidad))::integer             AS cantidad,
       current_date                                  AS fecha_subida
FROM core.hec_ventas
WHERE hev_fechadocumento::date >= '2025-05-01'      -- FECHA_DESDE (fija en el código)
  AND hev_tipodocumento <> 'PPTO'                    -- excluye presupuesto
GROUP BY hev_empresa, hev_codigoitem, mes
```

- `cantidad` = suma de unidades del mes, redondeada a entero. Puede ser **negativa** (meses con más devoluciones/notas de crédito que ventas).
- Solo existen filas para los meses **con movimiento**; los meses sin venta no generan fila.
- Incluye el **mes en curso** (incompleto).
- **No** filtra por canal/vendedor ni excluye clientes (a diferencia de `vw_ddmrp_ventas`, ver §8.1).

### 6.2 Detección de picos (por empresa + ítem)

Para cada ítem se toman **todas** sus filas mensuales extraídas (desde 2025-05, incluido el mes en curso):

| Paso | Fórmula | Equivalente Excel |
|---|---|---|
| Mediana | `MEDX = mediana(cantidad de todos los meses del ítem)` | `=MEDIANA(...)` |
| MAD | `MADX = mediana( \|cantidad − MEDX\| )` | |
| `desv_mediana` | `\|cantidad − MEDX\|` | `=ABS(C36-MEDX)` |
| `z_modificado` | `0.6745 × (cantidad − MEDX) / MADX` ; si `MADX = 0` → `0` | `=0,6745*(C36-MEDX)/MADX` |
| `es_pico` | `"SI"` si `\|z\| > 3.5`, si no `"NO"` (se compara con el Z **sin redondear**) | `=SI(ABS(E36)>ZTHR;"SI";"NO")` |
| `demanda_adu` | `cantidad` si `es_pico = "NO"`, si no `0` | `=SI(F36="NO";C36;"0")` |

- La mediana es la de `statistics.median` de Python (con cantidad par de datos, promedio de los dos centrales).
- `z_modificado` se guarda redondeado a 2 decimales.
- Si `MADX = 0` (más de la mitad de los meses con la misma cantidad) el Z es 0 y **ningún mes se marca como pico**.
- `demanda_adu` es **informativa**: el ADU **no** se calcula con esta columna (ver 6.3).

### 6.3 ADU, CV y VF (por empresa + ítem)

**Serie mensual del ítem:**

1. `mes_actual` = primer día del mes de hoy (el mes en curso **no entra**, está incompleto).
2. `ini_ventana` = `mes_actual − 12 meses`.
3. La serie va desde `max(primer mes con venta del ítem, ini_ventana)` hasta el mes anterior a `mes_actual`
   → como máximo **12 meses completos**; si el ítem es nuevo, desde su primer mes con venta.
4. Los meses **sin venta** cuentan como **0**.
5. Se **quitan de la serie** (no se ponen en 0, se eliminan) los **picos altos**:
   `es_pico = "SI"` **y** `z_modificado > 0` (mes por encima de la mediana).
   Los picos bajos (z < 0) se quedan en la serie con su valor.

**Cálculos:**

| Campo | Fórmula | Redondeo |
|---|---|---|
| `ADU` | `max( promedio(serie) / 30 ; 0 )` → unidades por día. Serie vacía → 0. | 2 dec. |
| `desviacion_estandar` | **Es el CV**, no la desviación: `CV = desv.estándar muestral(serie) / promedio(serie)` (equivale a desviación / ADU, la unidad se cancela). | 2 dec. |
| `VF` | `CV × factor del tramo` (ver tabla) | 2 dec. |

| Condición | Factor | VF resultante |
|---|---|---|
| CV ≤ 0.5 | VF bajo (param 7) = 0.2 | CV × 0.2 |
| 0.5 < CV ≤ 1 | VF medio (param 8) = 0.4 | CV × 0.4 |
| CV > 1 | VF alto (param 9) = 0.6 | CV × 0.6 |
| **No medible**: serie con menos de 3 meses **o** promedio ≤ 0 | — | CV = 0, **VF = 0.40** (el factor medio tal cual, sin multiplicar) |

- `stdev` es la desviación estándar **muestral** (divide entre n − 1), como `DESVEST.M` de Excel.
- El `/30` es fijo (mes estándar de 30 días), no usa los días reales del mes.

### 6.4 Campos de `core.ddmrp_ventas_picos`

| Campo | Tipo | Nivel | Descripción |
|---|---|---|---|
| `hev_empresa` | varchar | fila | Empresa. |
| `hev_codigoitem` | varchar | fila | Código de ítem (formato `MA_2000050`). |
| `mes` | date | fila | Primer día del mes. |
| `cantidad` | integer | fila | Unidades vendidas netas del mes (§6.1). |
| `desv_mediana` | numeric | fila | `\|cantidad − mediana\|`. |
| `z_modificado` | numeric | fila | Z modificado (2 dec.). |
| `es_pico` | varchar(2) | fila | `SI`/`NO`. |
| `demanda_adu` | integer | fila | Cantidad sin picos (picos altos y bajos en 0). Informativa. |
| `fecha_subida` | date | fila | Fecha de ejecución. |
| `desviacion_estandar` | numeric | ítem | **CV** de la serie limpia (§6.3). |
| `VF` | numeric | ítem | Factor de variabilidad (§6.3). |
| `ADU` | numeric | ítem | Demanda diaria promedio (§6.3). |

**Uso en master:** `ADU` y `VF` (con `SELECT DISTINCT` por empresa + ítem).

---

## 7. `ddmrp_proveedores.py` → `core.ddmrp_proveedores`

**Objetivo:** calcular el lead time de cada **pedido de importación (PI)** por proveedor, limpiar picos
con el Z modificado y armar el **DLT** (Decoupled Lead Time) por pedido.
La tabla tiene **una fila por empresa + proveedor + PI + forwarder**.

### 7.1 Extracción

```sql
SELECT hfr.hfr_empresa          AS empresa,
       imp.heim_codigoproveedor AS cod_proveedor,
       imp.heim_proveedor       AS nombre_proveedor,
       ped.hpe_numeropi,
       imp.heim_agente_forwarder,
       ROUND(AVG(imp.heim_eta_real::date - imp.heim_etd_real::date), 0)           AS leadtime_promedio_etd_eta,
       ROUND(AVG(ped.hpe_fechanecesaria::date - hfr.hfr_fechadocumento::date), 0) AS leadtime_promedio,
       COUNT(*) AS total_registros
FROM core.hec_facturas_reserva hfr
JOIN core.hec_importaciones imp ON hfr.hfr_numeropi = imp.heim_num_pi
LEFT JOIN core.hec_pedidos ped  ON hfr.hfr_numeropi = ped.hpe_numeropi
WHERE hfr.hfr_fechadocumento < CURRENT_DATE - 365      -- param 15
GROUP BY empresa, cod_proveedor, nombre_proveedor, ped.hpe_numeropi, heim_agente_forwarder
```

| Campo extraído | Significado | Cálculo |
|---|---|---|
| `leadtime_promedio_etd_eta` | Lead time **puerto de origen → Guayaquil** (tránsito marítimo) | Promedio de `ETA real − ETD real` en días, redondeado a entero |
| `leadtime_promedio` | Lead time de **producción** del proveedor | Promedio de `fecha necesaria del pedido − fecha documento de la factura reserva` en días, redondeado a entero |
| `total_registros` | Número de filas unidas | `COUNT(*)` del join (líneas de factura × registros de importación × registros de pedido) |

- Filtro de fecha: solo facturas reserva con fecha **anterior** a hoy − 365 días (param 15).
- Si el PI **no existe en `hec_pedidos`** (LEFT JOIN sin match), `hpe_numeropi` y `leadtime_promedio` salen `NULL`. Todas esas facturas del mismo proveedor/forwarder se agrupan en **una sola fila** con PI `NULL`.
- Los promedios `ROUND(...,0)` se convierten a `int` en Python.

### 7.2 Picos de lead time (Z modificado)

Se aplica **dos veces**, de forma independiente: una sobre `leadtime_promedio_etd_eta` (columnas con sufijo `_etd_eta`) y otra sobre `leadtime_promedio` (columnas sin sufijo). Agrupación: **empresa + cod_proveedor** (todas las filas/PI del proveedor).

| Campo | Fórmula |
|---|---|
| Mediana | `MEDX = mediana(lead times no nulos del proveedor)` |
| MAD | `MADX = mediana(\|leadtime − MEDX\|)` |
| `desv_mediana[_etd_eta]` | `\|leadtime − MEDX\|` |
| `z_modificado[_etd_eta]` | `0.6745 × (leadtime − MEDX) / MADX` (0 si MADX = 0); guardado con 2 dec. |
| `es_pico[_etd_eta]` | `"SI"` si `\|z\| > 3.5` (Z sin redondear) |
| `leadtime_adu[_etd_eta]` | `leadtime` si `es_pico = "NO"`; **0** si es pico (altos **y** bajos) |

Filas con lead time `NULL`: las 4 columnas calculadas quedan `NULL`.

### 7.3 DLT por pedido

```
dlt = Días confirmación pedido (param 10 = 3)
    + leadtime_adu                (producción, sin picos; NULL → 0)
    + Días coordinación booking   (param 12 = 3)
    + leadtime_adu_etd_eta        (tránsito puerto → GYE, sin picos; NULL → 0)
    + Días desaduanización y recepción en bodega (param 11 = 3)

    = 9 + leadtime_adu + leadtime_adu_etd_eta        (con los parámetros actuales)
```

Un lead time marcado como pico vale 0, así que ese pedido queda con un DLT menor (no se excluye la fila).

### 7.4 Columna `ltf` (de esta tabla)

```
DLT ≤ 60          → ltf = DLT × 0.2  (param 4, "LTF bajo")
60 < DLT ≤ 100    → ltf = DLT × 0.4  (param 5, "LTF medio")
DLT > 100         → ltf = DLT × 0.6  (param 6, "LTF alto")
redondeado a 2 decimales
```

Es un valor en **días** (DLT × factor). **El master no usa esta columna**: calcula su propio `LTF` (ver §9.3), con los tramos **al revés** (ver §11).

### 7.5 Campos de `core.ddmrp_proveedores`

| Campo | Tipo | Descripción |
|---|---|---|
| `empresa` | varchar | `hfr_empresa` |
| `cod_proveedor` | varchar | `heim_codigoproveedor` |
| `nombre_proveedor` | varchar | `heim_proveedor` |
| `hpe_numeropi` | varchar | Número de PI (NULL si no está en `hec_pedidos`) |
| `heim_agente_forwarder` | varchar | Forwarder |
| `leadtime_promedio_etd_eta` | integer | Tránsito ETA − ETD (§7.1) |
| `desv_mediana_etd_eta` | numeric | §7.2 |
| `z_modificado_etd_eta` | numeric | §7.2 |
| `es_pico_etd_eta` | varchar(2) | §7.2 |
| `leadtime_adu_etd_eta` | integer | §7.2 |
| `leadtime_promedio` | integer | Producción: fecha necesaria − fecha documento (§7.1) |
| `desv_mediana` | numeric | §7.2 |
| `z_modificado` | numeric | §7.2 |
| `es_pico` | varchar(2) | §7.2 |
| `leadtime_adu` | integer | §7.2 |
| `total_registros` | integer | §7.1 |
| `dlt` | numeric | §7.3 |
| `ltf` | numeric | §7.4 |

**Uso en master:** solo la columna `dlt` (§9.2, campo `DLT`).

---

## 8. Vistas de PostgreSQL usadas por el master

Estas vistas **no están en los scripts**; viven en la base `dwh`. Definición obtenida con `pg_get_viewdef`.

### 8.1 `core.vw_ddmrp_ventas` (ventas 365 / 90 días / mes)

Una fila por `hev_empresa` + `hev_codigoitem`.

**Filtros:**
- `hev_tipodocumento <> 'PPTO'`.
- Solo vendedores (`hev_vendedor_asignado` → `dim_vendedores.dve_codigo`) de categoría **`EQUIPO DE MAYOREO`** o **`EQUIPO B2B`**. Ventas con vendedor que no esté en `dim_vendedores` quedan fuera (JOIN interno).
- Excluye 4 clientes cuyo `hev_cuentasocio` termina en: `0190085929001`, `0195092982001`, `0190350533001`, `0195116598001`.
- Ítem debe existir en `dim_item` (JOIN por `dit_codigo`).
- `hev_fechadocumento >= CURRENT_DATE − 365 días` (param 1; si no existe, 365).

| Columna | Cálculo |
|---|---|
| `365D` | `SUM(hev_cantidad)` de la ventana; si la suma ≤ 0 → 0 |
| `max_cantidad_anio` | `MAX(hev_cantidad)` — la **línea de documento** con más unidades del año (no el mes con más venta); 0 si la suma anual ≤ 0 |
| `supera_umbral` | `'SI'` si `MAX(hev_cantidad) > 0.4 × SUM(hev_cantidad)`, si no `'NO'` (una sola venta representa más del 40 % del año) |
| `90D` | `SUM(hev_cantidad)` con `hev_fechadocumento >= CURRENT_DATE − 90` (param 2); 0 si no hay |
| `MES` | `SUM(hev_cantidad)` desde el día 1 del mes actual; 0 si no hay |

### 8.2 `core.vw_ddmrp_trans_ped` (suministro abierto)

Una fila por ítem de `dim_item` (`dit_codigo`, `dit_empresa`). Los tránsitos y facturas se agrupan **solo por código de ítem** (el código ya incluye el prefijo de empresa, p. ej. `MA_`).

| Columna | Origen | Cálculo |
|---|---|---|
| `30D` | `core.hec_transitos` | `SUM(het_cantidad)` con `het_estado = 'ABIERTO'` y `het_fechaentrega` entre **hoy y hoy + 30** (inclusive) |
| `60D` | `core.hec_transitos` | `SUM(het_cantidad)` con `het_estado = 'ABIERTO'` y `het_fechaentrega` **> hoy + 30 y ≤ hoy + 60** |
| `pedido` | `core.hec_facturas_reserva` | `SUM(hfr_backorder)` con `hfr_estado = 'ABIERTO'` y `hfr_pedidocompleto = 'PEDIDO'` |
| `backorder` | `core.hec_facturas_reserva` | `SUM(hfr_backorder)` con `hfr_estado = 'ABIERTO'` y `hfr_pedidocompleto = 'BACKORDER'` |

Todo con `COALESCE(...,0)`.
Tránsitos abiertos con fecha de entrega **anterior a hoy** (vencidos) o **posterior a hoy + 60** no se cuentan en ninguna columna.

### 8.3 `core.vw_ddmrp_item_proveedor` (relación ítem ↔ proveedor)

```sql
SELECT DISTINCT hfr.hfr_empresa AS empresa, hfr.hfr_codigoitem AS codigoitem, imp.heim_codigoproveedor
FROM core.hec_facturas_reserva hfr
JOIN core.hec_importaciones imp ON hfr.hfr_numeropi = imp.heim_num_pi
```

Todos los proveedores a los que alguna vez se importó el ítem (sin filtro de fecha). Se usa para
llevar el DLT del proveedor al ítem.

---

## 9. `master.py` → `core.ddmrp` (tabla final, campo por campo)

### 9.1 Construcción de la tabla

1. `CREATE TABLE IF NOT EXISTS core.ddmrp AS <SQL_DDMRP> WITH NO DATA` (estructura = columnas del SELECT).
2. Crea una tabla temporal vacía con el mismo SELECT, lee sus columnas/tipos de `pg_attribute` y hace `ADD COLUMN IF NOT EXISTS` de cada una (si se agregan columnas al SELECT, aparecen solas en la tabla).
3. Agrega (si no existen) las columnas calculadas por UPDATE, todas `numeric DEFAULT 0`: `ADU`, `ZONA ROJA BASE`, `ZONA ROJA SEGURIDAD`, `TOR`, `ZONA AMARILLA`, `TOY`, `ZONA VERDE`, `TOG`, `NFP`, `PEDIDO SUGERIDO`.
4. `TRUNCATE` + `INSERT ... SQL_DDMRP`.
5. UPDATEs en este orden: ADU → LTF → ZONA ROJA BASE → ZONA ROJA SEGURIDAD → TOR → ZONA AMARILLA → TOY → ZONA VERDE → TOG → NFP → PEDIDO SUGERIDO.

Todo es **una transacción**.

**Universo de filas:** una fila por registro de `core.dim_item` (todos los ítems del maestro, activos o no, con o sin venta). Los demás orígenes entran con `LEFT JOIN`.

| Alias | Origen | Join |
|---|---|---|
| `b` | `core.dim_item` | base |
| `a` | `core.vw_ddmrp_ventas` | `hev_empresa = dit_empresa AND hev_codigoitem = dit_codigo` |
| `c` | `core.ddmrp_inventario` | `ddmpr_empresa = dit_empresa AND ddmrp_item = dit_identificador` |
| `d` | `core.ddmrp_bodegas` | `empresa = dit_empresa AND codigo = dit_codigo` |
| `e` | `core.vw_ddmrp_trans_ped` | `dit_empresa` + `dit_codigo` |
| `f` | subconsulta DLT (§9.2 DLT) | `empresa` + `codigoitem` |
| `g` | `DISTINCT hev_empresa, hev_codigoitem, "VF"` de `ddmrp_ventas_picos` | `hev_empresa` + `hev_codigoitem` |

### 9.2 Campos descriptivos

| Campo | Origen | Cálculo |
|---|---|---|
| `EMPRESA` | `dim_item.dit_empresa` | directo |
| `CODIGO_ITEM` | `dim_item.dit_codigo` | directo (ej. `MA_2000050`) |
| `DESCRIPCION` | `dim_item.dit_nombre` | directo |
| `GRUPO` | `dim_item.dit_grupo` | directo |
| `RIN` | `dim_item.dit_rin` | directo |
| `SERIE` | `dim_item.dit_serie` | directo |
| `ANCHO` | `dim_item.dit_ancho` | directo |
| `MARCA` | `dim_item.dit_nombrefabricante` | directo |
| `BARRAS` | `dim_item.dit_codigobarras` | directo |
| `DISEÑO` | `dim_item.dit_disenio` | directo |
| `ACTIVO` | `dim_item.dit_activo` | directo |
| `ARTICULO_COMPRA` | `dim_item.dit_compra` | directo |

### 9.3 Campos de demanda

Notación: `V365 = a."365D"`, `V90 = a."90D"`, `D365 = c.ddmrp_stock_inv_1anio`, `D90 = c."ddmrp_stock_inv_90D"`.

| Campo | Fórmula | Explicación |
|---|---|---|
| `VTAS_1_AÑO` | `ROUND(V365, 2)` | Unidades vendidas netas últimos 365 días, canal mayoreo/B2B (§8.1). `NULL` si el ítem no tuvo venta. |
| `VENTAS MES PICO` | `ROUND(max_cantidad_anio, 2)` | La línea de venta individual más grande del año (§8.1). |
| `DIF PICO VTAS ULT AÑO VS # VTAS ULT AÑO` | `supera_umbral` | `SI` si esa línea supera el 40 % de la venta anual. |
| `DIAS INV 1 AÑO` | `ROUND(D365, 2)` | Días con stock en el último año (§5). |
| `DEMANDA MES 1 AÑO` | `ROUND( COALESCE( V365 / NULLIF(D365,0) × 30 , 0), 2)` | Venta por **día con stock** × 30 = demanda mensual corregida por quiebres. 0 si no hay días con stock o no hay venta. |
| `VENTA 90D` | `ROUND(V90, 2)` | Venta últimos 90 días (§8.1). |
| `DIAS INV 90D` | `ROUND(D90, 2)` | Días con stock últimos 90 días (§5). |
| `DEMANDA MES 90D` | `ROUND( COALESCE( V90 / NULLIF(D90,0) × 30 , 0), 2)` | Igual que la anual, con la ventana de 90 días. |
| `% VAR DEMANDA` | `ROUND( COALESCE( ( (V90/D90) / (V365/D365) − 1 ) × 100 , 0), 2)` | Variación % de la demanda diaria reciente (90d) contra la anual. Positivo = la demanda está subiendo. 0 si no se puede dividir. |
| `VENTAS MES ACTUAL` | `ROUND(a."MES", 2)` | Venta desde el día 1 del mes en curso. |

### 9.4 Campos de inventario y suministro

| Campo | Fórmula | Explicación |
|---|---|---|
| `EN STOCK` | `ROUND(d.sum, 2)` | Stock físico actual en bodegas de venta (SAP HANA, §4). |
| `TRANSITO 30D` | `ROUND(e."30D", 2)` | Tránsitos abiertos que llegan en 0–30 días (§8.2). |
| `TRANSITO 60D` | `ROUND(e."60D", 2)` | Tránsitos abiertos que llegan en 31–60 días (§8.2). |
| `PEDIDOS` | `ROUND(e.pedido, 2)` | Pendiente de facturas reserva abiertas tipo PEDIDO (§8.2). |
| `BACKORDERS` | `ROUND(e.backorder, 2)` | Pendiente de facturas reserva abiertas tipo BACKORDER (§8.2). |
| `STOCK TOTAL` | `ROUND( EN STOCK + TRANSITO 30D + TRANSITO 60D + PEDIDOS + BACKORDERS , 2)` (nulos = 0) | Inventario físico + todo el suministro abierto. |
| `MES INV TOTAL` | `ROUND( COALESCE( STOCK TOTAL / NULLIF(DEMANDA MES 90D, 0) , 0), 2)` | Meses de cobertura del stock total con la demanda de 90 días. 0 si la demanda es 0. |

### 9.5 Campos DDMRP de entrada

| Campo | Cálculo |
|---|---|
| `DLT` | **Paso 1** – por proveedor: `AVG(dlt)` de todas sus filas en `ddmrp_proveedores` (empresa + cod_proveedor), 2 dec.<br>**Paso 2** – por ítem: `AVG` de los DLT de los proveedores del ítem según `vw_ddmrp_item_proveedor` (si tiene varios, se promedian), 2 dec.<br>Ítem sin proveedor / sin historial → **0**. |
| `VF` | `VF` del ítem en `ddmrp_ventas_picos` (§6.3). Ítem sin ventas desde 2025-05 → **0**. |
| `ADU` | `ADU` del ítem en `ddmrp_ventas_picos` (§6.3), UPDATE por `EMPRESA` + `CODIGO_ITEM`. Sin venta → **0** (default). |
| `LTF` | Se inserta en 0 y luego `SQL_LTF`:<br>`DLT = 0` → **0**<br>`DLT ≤ 60` → param 6 = **0.6**<br>`60 < DLT ≤ 100` → param 5 = **0.4**<br>`DLT > 100` → param 4 = **0.2**<br>(lead time corto → factor alto; lead time largo → factor bajo). |

### 9.6 Zonas del buffer

| Campo | Fórmula | Redondeo | Significado |
|---|---|---|---|
| `ZONA ROJA BASE` | `ADU × DLT × LTF` | 2 dec. | Base de la zona de seguridad. |
| `ZONA ROJA SEGURIDAD` | `ZONA ROJA BASE × VF` | 2 dec. | Refuerzo por variabilidad de la demanda. |
| `TOR` (Top of Red) | `ZONA ROJA BASE + ZONA ROJA SEGURIDAD` | — | Zona roja total. |
| `ZONA AMARILLA` | `ADU × DLT` | 2 dec. | Demanda esperada durante el lead time. |
| `TOY` (Top of Yellow) | `TOR + ZONA AMARILLA` | — | Nivel de disparo de la orden. |
| `ZONA VERDE` | `GREATEST( ROUND(ADU × Ciclo de Pedido (param 3 = 30), 2) ; ZONA ROJA BASE )` | 2 dec. | Tamaño/frecuencia de la orden. **Sin MOQ** por ahora. |
| `TOG` (Top of Green) | `TOY + ZONA VERDE` | — | Tope máximo del buffer. |

### 9.7 Posición de flujo y pedido

| Campo | Fórmula | Explicación |
|---|---|---|
| `NFP` | `STOCK TOTAL − 0` | Net Flow Position = disponible + suministro abierto − demanda calificada. La **demanda calificada está en 0** (pendiente traer pedidos abiertos de clientes desde SAP). Hoy `NFP = STOCK TOTAL`. |
| `PEDIDO SUGERIDO` | si `NFP ≤ TOY` → `GREATEST(TOG − NFP, 0)`; si no → `0` | Solo se pide cuando la posición cae a la zona amarilla o roja; se repone hasta el TOG. |

**Casos particulares:**

| Situación | Resultado |
|---|---|
| ADU = 0 (sin venta) | Todas las zonas = 0 → TOG = 0 → pedido = 0. |
| DLT = 0 (sin historial de importación) | LTF = 0 → ROJA = 0, AMARILLA = 0, TOY = 0; VERDE = ADU × 30; TOG = ADU × 30. Solo se pide si `NFP ≤ 0`, y se pide `ADU × 30 − NFP`. |
| NFP > TOY | Pedido = 0 aunque esté por debajo del TOG. |

---

## 10. Ejemplo completo paso a paso (MA_2000050)

Ítem `MA_2000050` – APLUS 185/60 R-14 A609 82H – MAXXIMUNDO. Valores reales de la corrida del 27/09/2026.

### 10.1 ADU y VF (`ddmrp_ventas_picos`)

Venta mensual desde 2025-05 (ningún mes marcado como pico; el Z más alto fue 2.46 en 2026-08, menor que 3.5):

| Mes | 2025-09 | 10 | 11 | 12 | 2026-01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Cantidad | 95 | 54 | 86 | 255 | 191 | 419 | 554 | 205 | −14 | −9 | 331 | 688 |

(Mayo–agosto 2025 y septiembre 2026 están en la tabla pero fuera de la serie: los primeros por la ventana de 12 meses y septiembre 2026 por ser el mes en curso.)

- Suma = 2.855 → promedio = 237,92 u/mes
- **ADU** = 237,92 / 30 = **7,93** u/día
- **CV** = desviación estándar muestral / promedio = **0,94** → tramo 0,5 < CV ≤ 1 → factor 0,4
- **VF** = 0,94 × 0,4 = 0,376 → **0,38**

### 10.2 DLT (`ddmrp_proveedores`)

Proveedor único `P4444444444444`, 20 PIs. Ej. PI `LABZ-MX240614`: producción 30 días + tránsito 34 días + 9 fijos = **73**.
Promedio del DLT de las 20 filas = **65,70** → tramo 60 < DLT ≤ 100 → **LTF = 0,4**.

### 10.3 Demanda (`vw_ddmrp_ventas` + `ddmrp_inventario`)

| Campo | Cálculo | Valor |
|---|---|---|
| DEMANDA MES 1 AÑO | 3.165 / 278 × 30 | 341,55 |
| DEMANDA MES 90D | 1.423 / 63 × 30 | 677,62 |
| % VAR DEMANDA | (22,587 / 11,385 − 1) × 100 | 98,40 % |

### 10.4 Suministro

| EN STOCK | TRANSITO 30D | TRANSITO 60D | PEDIDOS | BACKORDERS | STOCK TOTAL | MES INV TOTAL |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 0 | 310 | 400 | 0 | **712** | 712 / 677,62 = **1,05** |

### 10.5 Buffer y pedido

| Campo | Cálculo | Valor |
|---|---|---:|
| ZONA ROJA BASE | 7,93 × 65,70 × 0,4 | 208,40 |
| ZONA ROJA SEGURIDAD | 208,40 × 0,38 | 79,19 |
| TOR | 208,40 + 79,19 | 287,59 |
| ZONA AMARILLA | 7,93 × 65,70 | 521,00 |
| TOY | 287,59 + 521,00 | 808,59 |
| ZONA VERDE | máx(7,93 × 30 = 237,90 ; 208,40) | 237,90 |
| TOG | 808,59 + 237,90 | 1.046,49 |
| NFP | STOCK TOTAL − 0 | 712,00 |
| PEDIDO SUGERIDO | 712 ≤ 808,59 → 1.046,49 − 712 | **334,49** |

---

## 11. Observaciones y puntos a revisar

Hallazgos del análisis del código. **No se modificó nada**; son preguntas para confirmar si el comportamiento es el esperado.

### Lógica de negocio

1. **Tramos de LTF invertidos entre scripts.** En `ddmrp_proveedores.py` (columna `ltf`), DLT ≤ 60 usa el factor **0.2** y DLT > 100 usa **0.6**. En `master.py` (columna `LTF`) es al revés: DLT ≤ 60 → **0.6**, DLT > 100 → **0.2**. El master es el que se usa en las zonas y coincide con el criterio estándar DDMRP (lead time largo → factor bajo). La columna `ltf` de proveedores además está en días (DLT × factor), no es el factor.
2. **VF = CV × factor.** En DDMRP estándar el VF es el factor del tramo (0.2 / 0.4 / 0.6). Aquí se multiplica por el CV, así que un CV de 0.3 da VF 0.06 y un CV de 2 da VF 1.2; en cambio un SKU no medible recibe 0.40 sin multiplicar. Confirmar que es la regla deseada.
3. **Ventas distintas para ADU y para las columnas de demanda.** `ADU` sale de `ddmrp_ventas_picos` (todas las ventas, sin filtro de canal ni de clientes), mientras que `VTAS_1_AÑO`, `VENTA 90D`, `DEMANDA MES …` salen de `vw_ddmrp_ventas` (solo mayoreo/B2B y sin 4 clientes). El buffer se calcula con una demanda distinta a la que se muestra.
4. **Picos de lead time cuentan como 0 en el DLT.** En `ddmrp_proveedores` el pedido con pico no se excluye: queda con `leadtime_adu = 0` y su DLT baja a 9 + el otro tramo, y después entra al promedio del master. Esto **reduce** el DLT del proveedor. Igual pasa con las filas con `leadtime_promedio` NULL (PI sin match en `hec_pedidos`), que entran con producción = 0.
5. **Filtro de fecha de proveedores.** `hfr_fechadocumento < CURRENT_DATE − 365` toma solo facturas **de hace más de un año**, no las del último año. Confirmar si es intencional (p. ej. para usar solo importaciones cerradas).
6. **Ítems sin DLT.** En la corrida actual, de 12.419 ítems solo 1.277 tienen DLT > 0 (5.550 tienen ADU > 0). Para el resto, LTF = 0 y el buffer se reduce a la zona verde (ADU × 30); solo sugieren pedido cuando NFP ≤ 0.
7. **Demanda calificada = 0 en el NFP** (pendiente, ya comentado en el código).
8. **Sin MOQ en la zona verde** (pendiente, ya comentado en el código).
9. **Tránsitos vencidos no se cuentan.** `vw_ddmrp_trans_ped` solo toma tránsitos con entrega entre hoy y hoy + 60. Un tránsito abierto con fecha ya pasada (atrasado) o a más de 60 días no suma al NFP.
10. **`VENTAS MES PICO` no es un mes.** Es `MAX(hev_cantidad)` de líneas de documento individuales. Igual `supera_umbral` compara esa línea contra el 40 % del año.

### Detalles técnicos

11. **`desviacion_estandar` guarda el CV**, no la desviación estándar (el nombre confunde).
12. **Picos de ventas calculados sobre todo el histórico** desde 2025-05-01 (fijo en el código) incluyendo el mes en curso incompleto, mientras que el ADU usa solo los últimos 12 meses completos. La mediana/MAD no incluye los meses sin venta (no tienen fila), pero la serie del ADU sí los cuenta como 0.
13. **`FECHA_DESDE` fija (2025-05-01).** A medida que pase el tiempo el histórico para picos crecerá sin límite; podría pasarse a parámetro o a ventana móvil.
14. **`ddmrp_inventario`**: la ventana cuenta hasta 366 / 91 fechas (inicio y fin inclusivos). El comentario del código (`2026-09-22 -> 2025-09-21`) no coincide con el cálculo real (daría 2025-09-22).
15. **Bodegas duplicadas** en `ddmrp_bodega.py` (`EMPRESAS_CONFIG`) y `ddmrp_inventario.py` (`BODEGAS_POR_EMPRESA`): si cambia una bodega hay que actualizar ambos.
16. **`ddmrp_bodegas.sum` es `bigint`**: si `OnHand` tuviera decimales, se redondean.
17. **`ddmrp_inventario` usa `FECHA_CORTE`**, pero las vistas y `ddmrp_ventas_picos` siempre usan la fecha de hoy; si se corre con fecha de corte, las ventanas no quedan alineadas.
18. **`master.py` lee los parámetros 3–6 sin filtrar `ddmrp_estado = 1`** (los otros scripts sí filtran).
19. **Credenciales en texto plano** en `conection/config.py` (SQL Server con usuario `sa`, PostgreSQL y HANA). Conviene moverlas a variables de entorno o a un archivo fuera del control de versiones.
