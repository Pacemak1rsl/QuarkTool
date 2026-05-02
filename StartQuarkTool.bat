@echo off
cd /d "%~dp0"
set "PYTHONPATH=%cd%\src"

set "PY_EXE="
for /f "usebackq delims=" %%I in (`python -c "import sys; print(sys.executable)" 2^>nul`) do set "PY_EXE=%%I"

if defined PY_EXE (
    set "PYW_EXE=%PY_EXE:python.exe=pythonw.exe%"
    if exist "%PYW_EXE%" (
        start "" "%PYW_EXE%" app_launcher.py
        exit /b 0
    )
)

for /f "usebackq delims=" %%I in (`py -3.8 -c "import sys; print(sys.executable)" 2^>nul`) do set "PY_EXE=%%I"
if defined PY_EXE (
    set "PYW_EXE=%PY_EXE:python.exe=pythonw.exe%"
    if exist "%PYW_EXE%" (
        start "" "%PYW_EXE%" app_launcher.py
        exit /b 0
    )
)

echo.
echo Launch failed. Please make sure Python and dependencies are installed.
echo Suggested command: pip install -r requirements.txt
pause
