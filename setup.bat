@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "BOOTSTRAP=.venv\Scripts\python.exe"
) else (
    set "BOOTSTRAP="
    where py >nul 2>nul && set "BOOTSTRAP=py"
    if not defined BOOTSTRAP where python >nul 2>nul && set "BOOTSTRAP=python"

    if not defined BOOTSTRAP (
        echo Python was not found.
        echo Install Python 3.11 or newer, then run setup.bat again.
        exit /b 1
    )

    !BOOTSTRAP! -m venv .venv
    if errorlevel 1 exit /b 1
    set "BOOTSTRAP=.venv\Scripts\python.exe"
)

"%BOOTSTRAP%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

"%BOOTSTRAP%" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

if not exist "data" mkdir data
if not exist "audio" mkdir audio

if not exist ".env" copy /y ".env.example" ".env" >nul
if not exist "data\profile.json" if exist "data\profile.example.json" copy /y "data\profile.example.json" "data\profile.json" >nul

echo.
echo NovaAI setup complete.
echo.
echo Next steps:
echo 1. Install Ollama if you have not already.
echo 2. Pull your chat model, for example: ollama pull dolphin3
echo 3. Review .env and adjust voice or model settings if you want.
echo 4. Run the app with: .\.venv\Scripts\python.exe app.py
echo.
echo Optional GPU note:
echo If you use an NVIDIA GPU, you can swap PyTorch to CUDA wheels after setup.

endlocal
