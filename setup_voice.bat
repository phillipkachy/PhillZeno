@echo off
REM PhillZeno voice cloning add-on (Windows). Optional and BIG. Run once:  setup_voice.bat
REM Installs Chatterbox (MIT license) into its own folder, .venv-voice, so the main tools stay safe.
cd /d "%~dp0"

echo.
echo  ===================== VOICE CLONING ADD-ON =====================
echo   What:  Chatterbox, a free voice model by Resemble AI (MIT license, commercial use OK)
echo   Why:   narrate your scripts in a clone of YOUR voice
echo   Disk:  about 1 GB now (no NVIDIA card) or about 3.5 GB (NVIDIA card),
echo          plus about 3 GB for the voice model, downloaded the first time you narrate.
echo          Turbo mode adds about 2 GB more if you ever use it.
echo   Remove it any time by deleting the .venv-voice folder.
echo  ================================================================
echo.
set /p OK=Install it? Type y and press Enter:
if /i not "%OK%"=="y" (
  echo Cancelled. Nothing was installed.
  pause
  exit /b 0
)

if not exist .venv-voice (
  py -m venv .venv-voice || (echo Python not found. Run setup.bat first. & pause & exit /b 1)
)
.venv-voice\Scripts\python -m pip install --upgrade pip --quiet

where nvidia-smi >nul 2>nul
if %errorlevel%==0 (
  echo NVIDIA card found: installing the GPU version of PyTorch ^(big download, be patient^)...
  .venv-voice\Scripts\python -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
) else (
  echo No NVIDIA card: installing the CPU version of PyTorch...
  .venv-voice\Scripts\python -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
)
.venv-voice\Scripts\python -m pip install -r requirements-voice.txt
if errorlevel 1 (
  echo.
  echo Install hit an error. Copy the messages above and paste them to Claude.
  pause
  exit /b 1
)
echo.
echo Done. Next: record your sample ^(see voices\phill\README.md^), then run:
echo     .venv-voice\Scripts\python tools\narrate.py projects\avengers-doomsday --test
pause
