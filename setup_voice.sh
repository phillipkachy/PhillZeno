#!/usr/bin/env bash
# PhillZeno voice cloning add-on (Mac / Linux). Optional and BIG. Run once:  bash setup_voice.sh
# Installs Chatterbox (MIT license) into its own folder, .venv-voice, so the main tools stay safe.
set -e
cd "$(dirname "$0")"
PY=python3; command -v $PY >/dev/null 2>&1 || PY=python

cat <<'EOF'

 ===================== VOICE CLONING ADD-ON =====================
  What:  Chatterbox, a free voice model by Resemble AI (MIT license, commercial use OK)
  Why:   narrate your scripts in a clone of YOUR voice
  Disk:  about 1 GB now (Mac / no NVIDIA card) or about 3.5 GB (NVIDIA card),
         plus about 3 GB for the voice model, downloaded the first time you narrate.
         Turbo mode adds about 2 GB more if you ever use it.
  Remove it any time by deleting the .venv-voice folder.
 ================================================================

EOF
read -r -p "Install it? Type y and press Enter: " OK
if [ "$OK" != "y" ] && [ "$OK" != "Y" ]; then echo "Cancelled. Nothing was installed."; exit 0; fi

[ -d .venv-voice ] || $PY -m venv .venv-voice
V=.venv-voice/bin/python
$V -m pip install --upgrade pip --quiet
if [ "$(uname)" = "Darwin" ]; then
  echo "Mac: installing PyTorch (uses Apple Silicon GPU automatically)..."
  $V -m pip install torch==2.6.0 torchaudio==2.6.0
elif command -v nvidia-smi >/dev/null 2>&1; then
  echo "NVIDIA card found: installing the GPU version of PyTorch (big download)..."
  $V -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu124
else
  echo "No NVIDIA card: installing the CPU version of PyTorch..."
  $V -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cpu
fi
$V -m pip install -r requirements-voice.txt
echo
echo "Done. Next: record your sample (see voices/phill/README.md), then run:"
echo "    .venv-voice/bin/python tools/narrate.py projects/avengers-doomsday --test"
