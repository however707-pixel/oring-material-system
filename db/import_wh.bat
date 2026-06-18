@echo off
set PYTHONIOENCODING=utf-8
set PROJ=C:\Users\T26019\Desktop\oring_project_v8\oring_project
set PYEXE=C:\Users\T26019\AppData\Local\Python\pythoncore-3.14-64\python.exe
set NAS_DIR=\\192.168.2.34\MO_Storage

rem Check NAS reachable
if not exist "%NAS_DIR%" (
    echo [ERROR] NAS not reachable. Check VPN/network. >> "%PROJ%\data\import.log"
    exit /b 1
)

"%PYEXE%" "%PROJ%\db\import_to_db.py" >> "%PROJ%\data\import.log" 2>&1
exit /b %errorlevel%
