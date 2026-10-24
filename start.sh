#!/bin/sh
# Mac/Linux: run `sh start.sh` in Terminal. First run sets everything up (needs Python 3.10+).
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Setting up for the first time..."; python3 -m venv .venv; }
. .venv/bin/activate
python -m pip install -q --disable-pip-version-check -r requirements.txt
echo "Opening http://127.0.0.1:5050 - press Ctrl+C to stop."
python app.py
