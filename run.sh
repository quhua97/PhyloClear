#!/usr/bin/env bash
# PhyloClear launcher (macOS / Linux). On Windows, use run.bat.
set -e
cd "$(dirname "$0")"

if [ -f ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"
else
    echo "[PhyloClear] Creating virtual environment..."
    python3 -m venv .venv
    PY=".venv/bin/python"
    echo "[PhyloClear] Installing dependencies..."
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements.txt
fi

exec "$PY" main.py "$@"
