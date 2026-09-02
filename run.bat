@echo off
cd /d "%~dp0"
echo Installing Python packages if needed...
py -3 -m pip install -r requirements.txt
if errorlevel 1 python -m pip install -r requirements.txt
echo Starting CTDF — Coil-Tubing Data Fusion...
py -3 app.py
if errorlevel 1 python app.py
pause
