@echo off
cd /d "%~dp0"
echo Installing app packages...
where py >nul 2>&1
if %errorlevel%==0 goto :use_py
python -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :fail
echo Building CTDF.exe...
python -m PyInstaller --noconfirm ctdf.spec
if errorlevel 1 goto :fail
goto :sign

:use_py
py -3 -m pip install -r requirements.txt -r requirements-build.txt
if errorlevel 1 goto :fail
echo Building CTDF.exe...
py -3 -m PyInstaller --noconfirm ctdf.spec
if errorlevel 1 goto :fail

:sign
if defined CTDF_SIGN_CERT (
  echo Signing CTDF.exe...
  if defined CTDF_SIGN_PASSWORD (
    signtool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /f "%CTDF_SIGN_CERT%" /p "%CTDF_SIGN_PASSWORD%" "dist\CTDF\CTDF.exe"
  ) else (
    signtool sign /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com /f "%CTDF_SIGN_CERT%" "dist\CTDF\CTDF.exe"
  )
  if errorlevel 1 goto :fail
) else (
  echo No CTDF_SIGN_CERT set -- exe is unsigned. SmartScreen will warn until you sign it.
)

echo.
echo Built dist\CTDF\CTDF.exe
echo Zip the whole dist\CTDF folder to share. Job data is not included.
exit /b 0

:fail
echo Build failed.
exit /b 1
