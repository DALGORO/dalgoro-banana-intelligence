@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0interfaz_banano.py"
    exit /b 0
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "%~dp0interfaz_banano.py"
    exit /b %errorlevel%
)

echo.
echo No se encontro el entorno virtual:
echo %~dp0.venv\Scripts\python.exe
echo.
echo Active o reinstale el entorno virtual antes de abrir la interfaz.
pause
exit /b 1
