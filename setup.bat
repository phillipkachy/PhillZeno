@echo off
REM PhillZeno one-time setup for Windows.
REM Double-click this file, or run it from the phillzeno folder:   setup.bat
REM Safe to run again any time (e.g. after new packages are added).
cd /d "%~dp0"

echo == Checking your machine ==
py tools\check_machine.py
if errorlevel 1 (
  echo Python not found. Install it with:  winget install Python.Python.3.11
  echo Then close this window, open a new one, and run setup.bat again.
  pause
  exit /b 1
)

if not exist .venv (
  echo == Creating the project's private Python environment ^(.venv^) ==
  py -m venv .venv
)

echo == Installing Python packages from requirements.txt ==
.venv\Scripts\python -m pip install --upgrade pip --quiet
.venv\Scripts\python -m pip install -r requirements.txt --quiet

echo.
echo Setup done. From now on, start every session with:
echo     .venv\Scripts\activate
pause
