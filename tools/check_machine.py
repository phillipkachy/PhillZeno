"""
PhillZeno machine check.

Run it with:   python tools/check_machine.py      (Windows: py tools\\check_machine.py)

It only READS information about your computer. It installs nothing and changes nothing.
It uses plain Python (no extra packages), so it works before any setup.
"""

import os
import platform
import shutil
import subprocess
import sys


def run(cmd):
    """Run a command and return its output, or None if it isn't available."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip()
    except Exception:
        return None


def ram_gb():
    system = platform.system()
    try:
        if system == "Linux":
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal"):
                        return int(line.split()[1]) / 1024 / 1024
        elif system == "Darwin":
            return int(run(["sysctl", "-n", "hw.memsize"])) / 1024**3
        elif system == "Windows":
            import ctypes

            class MEMSTAT(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            m = MEMSTAT()
            m.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1024**3
    except Exception:
        pass
    return None


def cpu_name():
    system = platform.system()
    if system == "Darwin":
        return run(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor()
    if system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    return platform.processor() or platform.machine()


def gpu_info():
    """Return (kind, description, vram_gb)."""
    if shutil.which("nvidia-smi"):
        out = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        if out and "failed" not in out.lower():
            first = out.splitlines()[0]
            name, _, mem = first.partition(",")
            try:
                vram = float(mem) / 1024
            except ValueError:
                vram = None
            return "nvidia", name.strip(), vram
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        chip = run(["sysctl", "-n", "machdep.cpu.brand_string"]) or "Apple Silicon"
        return "apple", chip, None  # Apple shares RAM with the GPU
    if platform.system() == "Windows":
        out = run(["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance Win32_VideoController).Name"])
        if out:
            return "other", out.replace("\n", ", "), None
    return "none", "No NVIDIA GPU or Apple Silicon found", None


def tool_version(name, args):
    path = shutil.which(name)
    if not path:
        return None
    out = run([name] + args)
    return out.splitlines()[0] if out else "found"


def main():
    system = platform.system()
    print("=" * 60)
    print(" PhillZeno machine check")
    print("=" * 60)

    os_name = {"Darwin": "macOS " + platform.mac_ver()[0]}.get(system, f"{system} {platform.release()}")
    print(f"Operating system : {os_name} ({platform.machine()})")
    print(f"CPU              : {cpu_name()}  ({os.cpu_count()} threads)")
    ram = ram_gb()
    print(f"RAM              : {ram:.1f} GB" if ram else "RAM              : unknown")
    free = shutil.disk_usage(os.path.abspath(".")).free / 1024**3
    print(f"Free disk (here) : {free:.1f} GB")
    kind, gname, vram = gpu_info()
    vram_txt = f", {vram:.1f} GB VRAM" if vram else ""
    print(f"GPU              : {gname}{vram_txt}")
    print()

    py_ok = sys.version_info >= (3, 10)
    print(f"Python           : {platform.python_version()}  {'OK' if py_ok else 'TOO OLD - need 3.10+'}")
    ff = tool_version("ffmpeg", ["-version"])
    print(f"ffmpeg           : {ff or 'MISSING'}")
    gt = tool_version("git", ["--version"])
    print(f"git              : {gt or 'MISSING'}")
    print()

    # ---- What's missing and how to get it ----
    missing = []
    if not py_ok:
        missing.append("python")
    if not ff:
        missing.append("ffmpeg")
    if not gt:
        missing.append("git")

    if missing:
        print("MISSING - how to install (all free):")
        if system == "Windows":
            hints = {
                "python": "winget install Python.Python.3.11",
                "ffmpeg": "winget install Gyan.FFmpeg",
                "git": "winget install Git.Git",
            }
            note = "Run these in PowerShell, then CLOSE and reopen the window."
        elif system == "Darwin":
            hints = {
                "python": "brew install python@3.11",
                "ffmpeg": "brew install ffmpeg",
                "git": "xcode-select --install",
            }
            note = "No 'brew'? Install it first from https://brew.sh (free)."
        else:
            hints = {
                "python": "sudo apt install python3 python3-venv python3-pip",
                "ffmpeg": "sudo apt install ffmpeg",
                "git": "sudo apt install git",
            }
            note = ""
        for m in missing:
            print(f"  {m:7}: {hints[m]}")
        if note:
            print(f"  ({note})")
        print()
    else:
        print("All required tools are installed.")
        print()

    # ---- Recommendations ----
    print("WHAT THIS MEANS FOR AI VOICES (Format B) AND TRANSCRIPTION")
    ram = ram or 0
    if kind == "nvidia" and (vram or 0) >= 6:
        print("  Tier: STRONG. NVIDIA GPU with enough VRAM.")
        print("  - Expressive voice models (e.g. Chatterbox) run fast: seconds per line.")
        print("  - Whisper transcription: 'medium' or 'large-v3' model.")
    elif kind == "nvidia":
        print("  Tier: OK. NVIDIA GPU but low VRAM (<6 GB).")
        print("  - Expressive models should fit; keep one model loaded at a time.")
        print("  - Whisper: 'small' or 'medium'.")
    elif kind == "apple":
        print("  Tier: OK. Apple Silicon (GPU via 'MPS').")
        print("  - Expressive models work, slower than NVIDIA (roughly 5-20 s per line).")
        print("  - Whisper: 'small' or 'medium'.")
    else:
        print("  Tier: CPU ONLY.")
        if ram >= 15:  # a "16 GB" machine reports ~15.7
            print("  - Expressive models will run, but slowly (maybe 30-90 s per line).")
            print("    A 2-minute comic scene is still doable; batch it and walk away.")
        else:
            print("  - Under 16 GB RAM: expressive models will struggle. We'd use a")
            print("    lighter model or a free cloud GPU (Google Colab free tier).")
        print("  - Whisper: 'small' (good balance) or 'base' (faster).")
    if free < 15:
        print(f"  WARNING: only {free:.0f} GB free. Voice models + renders need ~15 GB.")
    print()
    print("Copy everything above and paste it back to Claude.")


if __name__ == "__main__":
    main()
