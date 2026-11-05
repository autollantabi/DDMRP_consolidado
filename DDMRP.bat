@echo off
setlocal EnableExtensions DisableDelayedExpansion

:: ============================================================
::  ACTUALIZACION DDMRP - ejecuta los scripts Python en orden
:: ============================================================

:: ------------------- CONFIGURACION -------------------
:: Carpeta donde esta este .bat = raiz del proyecto, sin barra final
set "SCRIPTS_DIR=%~dp0"
if "%SCRIPTS_DIR:~-1%"=="\" set "SCRIPTS_DIR=%SCRIPTS_DIR:~0,-1%"
set "LOG_DIR=%SCRIPTS_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\log_actualizacion_ddmrp.txt"
set "STEP_LOG=%LOG_DIR%\_ultimo_paso.txt"

:: Si Python no esta en el PATH o usas un venv, pon la ruta completa, ej:
:: set "PYTHON=C:\ruta\a\tu\venv\Scripts\python.exe"
set "PYTHON="

:: 1 = pausar si hay error, uso manual.  0 = no pausar, Programador de tareas
set "PAUSA_EN_ERROR=1"

:: Evita errores de tildes y enie al escribir en el log
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
:: -----------------------------------------------------

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

>>"%LOG_FILE%" echo.
>>"%LOG_FILE%" echo =============== [%date% %time%] Iniciando Actualizacion DDMRP ===============

:: ---- Buscar Python: primero el entorno virtual, luego el del sistema ----
if not defined PYTHON if exist "%SCRIPTS_DIR%\venv\Scripts\python.exe"  set "PYTHON=%SCRIPTS_DIR%\venv\Scripts\python.exe"
if not defined PYTHON if exist "%SCRIPTS_DIR%\.venv\Scripts\python.exe" set "PYTHON=%SCRIPTS_DIR%\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%SCRIPTS_DIR%\env\Scripts\python.exe"   set "PYTHON=%SCRIPTS_DIR%\env\Scripts\python.exe"
:: Entorno virtual una carpeta arriba del proyecto
for %%P in ("%SCRIPTS_DIR%\..") do set "PARENT_DIR=%%~fP"
if not defined PYTHON if exist "%PARENT_DIR%\venv\Scripts\python.exe"  set "PYTHON=%PARENT_DIR%\venv\Scripts\python.exe"
if not defined PYTHON if exist "%PARENT_DIR%\.venv\Scripts\python.exe" set "PYTHON=%PARENT_DIR%\.venv\Scripts\python.exe"
if not defined PYTHON if exist "%PARENT_DIR%\env\Scripts\python.exe"   set "PYTHON=%PARENT_DIR%\env\Scripts\python.exe"
if not defined PYTHON where py >nul 2>&1 && set "PYTHON=py"
if not defined PYTHON where python >nul 2>&1 && set "PYTHON=python"
if defined PYTHON goto :python_ok
call :log "ERROR: No se encontro Python. Configura la variable PYTHON al inicio del .bat"
goto :fin_error

:python_ok
call :log "Usando Python: %PYTHON%"
echo.

:: ------------------- PASOS -------------------
:: Para agregar otro script copia una linea:  call :run_step "NOMBRE" "archivo.py" || goto :fin_error
call :run_step "MAESTRO DDMRP"                "master.py"               || goto :fin_error
call :run_step "EXPORTAR EXCEL DDMRP LLANTAS" "export_excel_llantas.py" || goto :fin_error
:: ---------------------------------------------

call :log "PROCESO COMPLETO SIN ERRORES."
>>"%LOG_FILE%" echo.
endlocal
exit /b 0


:fin_error
echo.
echo Revisa el log completo en: %LOG_FILE%
>>"%LOG_FILE%" echo =============== [%date% %time%] PROCESO DETENIDO POR ERROR ===============
>>"%LOG_FILE%" echo.
if "%PAUSA_EN_ERROR%"=="1" pause
endlocal
exit /b 1


:: ============================================================
::  :run_step "Nombre del paso" "script.py"
:: ============================================================
:run_step
set "STEP_NAME=%~1"
set "STEP_FILE=%~2"
set "STEP_SCRIPT=%SCRIPTS_DIR%\%~2"

call :log "Iniciando: %STEP_NAME% - %STEP_FILE% ..."

if exist "%STEP_SCRIPT%" goto :run_step_ejecutar
call :log "ERROR en [%STEP_NAME%]: no existe el archivo %STEP_SCRIPT%"
exit /b 1

:run_step_ejecutar
:: Se ejecuta desde la carpeta del script para que funcionen las rutas relativas
pushd "%SCRIPTS_DIR%"
"%PYTHON%" -u "%STEP_SCRIPT%" > "%STEP_LOG%" 2>&1
set "RC=%ERRORLEVEL%"
popd

:: Copiar la salida del script al log general
type "%STEP_LOG%" >> "%LOG_FILE%"

if not "%RC%"=="0" goto :run_step_fallo
call :log "OK: %STEP_NAME% completado."
echo.
exit /b 0

:run_step_fallo
echo.
call :log "ERROR en el paso [%STEP_NAME%] - %STEP_FILE% termino con codigo %RC%"
call :detalle_error
exit /b 1


:: ============================================================
::  Lee el traceback de Python y muestra DONDE y QUE fallo
:: ============================================================
:detalle_error
set "ERR_UBIC="
set "ERR_UBIC_TU="
set "ERR_MSG="

:: Ultima linea  File "...", line N  = donde reviento, puede ser dentro de una libreria
for /f "usebackq delims=" %%L in (`findstr /b /c:"  File " "%STEP_LOG%"`) do set "ERR_UBIC=%%L"

:: Ultima linea de TU codigo, excluye librerias como pandas o sqlalchemy
for /f "usebackq delims=" %%L in (`findstr /b /c:"  File " "%STEP_LOG%" ^| findstr /v /i /c:"site-packages" /c:"<frozen"`) do set "ERR_UBIC_TU=%%L"

:: Ultima linea no vacia = mensaje del error, ej: KeyError: 'COD_ITEM'
for /f "usebackq delims=" %%L in ("%STEP_LOG%") do set "ERR_MSG=%%L"

:: Delayed expansion para imprimir sin que < > " del traceback rompan el echo
setlocal EnableDelayedExpansion
echo ---------------------------------------------------------------
echo   Paso   : !STEP_NAME!
echo   Script : !STEP_FILE!
if defined ERR_UBIC_TU echo   Donde  : !ERR_UBIC_TU:~2!
if defined ERR_UBIC_TU if not "!ERR_UBIC_TU!"=="!ERR_UBIC!" echo   Origen : !ERR_UBIC:~2!
if not defined ERR_UBIC_TU if defined ERR_UBIC echo   Donde  : !ERR_UBIC:~2!
if not defined ERR_UBIC echo   Donde  : sin traceback de Python - sys.exit, error externo o Python no arranco
if defined ERR_MSG echo   Error  : !ERR_MSG!
echo ---------------------------------------------------------------
echo   Ultimas lineas de salida del script:
echo.
powershell -NoProfile -Command "Get-Content -LiteralPath '!STEP_LOG!' -Tail 15 -Encoding UTF8"
echo ---------------------------------------------------------------

>>"%LOG_FILE%" echo [%date% %time%] RESUMEN DEL ERROR
>>"%LOG_FILE%" echo   Paso   : !STEP_NAME! - !STEP_FILE!
if defined ERR_UBIC_TU >>"%LOG_FILE%" echo   Donde  : !ERR_UBIC_TU:~2!
if defined ERR_UBIC_TU if not "!ERR_UBIC_TU!"=="!ERR_UBIC!" >>"%LOG_FILE%" echo   Origen : !ERR_UBIC:~2!
if not defined ERR_UBIC_TU if defined ERR_UBIC >>"%LOG_FILE%" echo   Donde  : !ERR_UBIC:~2!
if defined ERR_MSG     >>"%LOG_FILE%" echo   Error  : !ERR_MSG!
endlocal
exit /b 0


:: ============================================================
::  :log "mensaje"  -> consola + archivo de log
:: ============================================================
:log
echo [%time:~0,8%] %~1
>>"%LOG_FILE%" echo [%date% %time%] %~1
exit /b 0