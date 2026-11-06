@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [PhyloClear] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [PhyloClear] Failed to create venv. Is Python installed and on PATH?
        pause
        exit /b 1
    )
    echo [PhyloClear] Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo [PhyloClear] Starting...
".venv\Scripts\python.exe" main.py %*
endlocal
