@echo off
cd /d "%~dp0"
echo Installing Python packages if needed...
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 -m pip install -r requirements.txt
  echo Starting CTDF — Coil-Tubing Data Fusion...
  py -3 app.py
) else (
  python -m pip install -r requirements.txt
  echo Starting CTDF — Coil-Tubing Data Fusion...
  python app.py
)
pause
