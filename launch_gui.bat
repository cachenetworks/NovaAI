@echo off
setlocal EnableExtensions

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    call .\setup.bat
    if errorlevel 1 exit /b 1
)

if not exist ".setup-complete" (
    call .\setup.bat
    if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" app.py --gui

endlocal
