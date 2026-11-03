#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then python3 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.txt
echo "Buka http://127.0.0.1:8000 di browser"
.venv/bin/python run.py
