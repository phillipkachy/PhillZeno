#!/usr/bin/env bash
# PhillZeno one-time setup for Mac / Linux.
# Run from the phillzeno folder:   bash setup.sh
# Safe to run again any time (e.g. after new packages are added).
set -e
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python

echo "== Checking your machine =="
$PY tools/check_machine.py

if [ ! -d .venv ]; then
  echo "== Creating the project's private Python environment (.venv) =="
  $PY -m venv .venv
fi

echo "== Installing Python packages from requirements.txt =="
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet

echo
echo "Setup done. From now on, start every session with:"
echo "    source .venv/bin/activate"
