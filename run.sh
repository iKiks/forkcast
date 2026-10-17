#!/usr/bin/env bash
# Forkcast quick start for macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
echo "Forkcast is starting at http://127.0.0.1:8000"
exec .venv/bin/python -m uvicorn forkcast.server:app --host 127.0.0.1 --port 8000
