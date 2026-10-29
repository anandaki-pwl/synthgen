@echo off
rem Double-click to start SynthGen. The first run sets things up (takes a minute or two).
title SynthGen
cd /d "%~dp0"

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    echo Python was not found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo First-time setup: creating a private Python environment for SynthGen...
    %PY% -m venv .venv || goto :failed
)

rem Install or update packages whenever requirements.txt changes.
fc /b requirements.txt ".venv\installed.txt" >nul 2>&1
if errorlevel 1 (
    echo Installing the packages SynthGen needs. This only happens once...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :failed
    copy /y requirements.txt ".venv\installed.txt" >nul
)

echo.
echo SynthGen is starting and will open in your web browser.
echo Keep this window open while you use it. Close it to stop SynthGen.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py
exit /b 0

:failed
echo.
echo Setup failed. Check your internet connection and try again, or send the
echo messages above to whoever shared SynthGen with you.
pause
exit /b 1
