@echo off
setlocal
cd /d "%~dp0"

echo ================================================================
echo Mines de Costano - lokale Webansicht
echo ================================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    py start_server.py
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python start_server.py
    goto :end
)

echo FEHLER: Python 3 wurde auf diesem Computer nicht gefunden.
echo.
echo Bitte Python 3 von https://www.python.org/downloads/ installieren.
echo Danach dieses Fenster schliessen und START_WINDOWS.bat erneut starten.
echo.

:end
echo.
pause
