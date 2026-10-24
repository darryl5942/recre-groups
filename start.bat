@echo off
rem Double-click to start. First run sets everything up (needs Python 3.10+).
cd /d "%~dp0"
if not exist .venv (
  echo Setting up for the first time...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --disable-pip-version-check -r requirements.txt
echo Opening http://127.0.0.1:5050 - close this window to stop.
python app.py
pause
