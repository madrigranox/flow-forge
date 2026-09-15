@echo off
rem Flow Forge - inicia o programa sem instalar nada.
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    start "" pyw main.py
    exit /b
)

where pythonw >nul 2>&1
if %errorlevel%==0 (
    start "" pythonw main.py
    exit /b
)

echo.
echo   Python nao foi encontrado neste computador.
echo.
echo   O Flow Forge precisa do Python 3.9 ou superior.
echo   Baixe em https://www.python.org/downloads/
echo   Na instalacao, marque "Add python.exe to PATH".
echo   Nao precisa ser administrador: escolha "Install for me only".
echo.
pause
