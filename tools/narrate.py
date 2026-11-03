"""
Narrate a script in a clone of YOUR voice (Chatterbox, free, runs on your computer).

One-time: run setup_voice.bat (Windows) / bash setup_voice.sh (Mac), and record your
sample (see voices/phill/README.md).

Run with the voice add-on's Python:
  Windows:  .venv-voice\\Scripts\\python tools\\narrate.py projects\\avengers-doomsday --test
  Mac:      .venv-voice/bin/python tools/narrate.py projects/avengers-doomsday --test

  --test         only the HOOK and SETUP (about a minute). Do this first.
  (no flag)      the whole script
  --redo 12,15   make a new take of paragraphs 12 and 15 (numbers are in build/narration/paragraphs.md)
  --engine turbo use the faster engine (no emotion dial)

Output (nothing of yours is ever changed):
  build/narration/narration.wav    the full read, used by the video editor
  build/narration/narration.mp3    the same, for listening
  build/narration/paragraphs.md    every paragraph with its number and timing
  build/narration/timing.json      exact start/end of each paragraph (the editor uses it)

Finished pieces are remembered, so if it stops halfway, just run it again and it continues.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from script_check import parse_script  # noqa: E402

SR = 24000
MAX_CHUNK_CHARS = 220          # long text in one go makes the model ramble or cut off
FAKE = os.environ.get("PHILLZENO_FAKE_TTS") == "1"   # for testing without the model


# ------------------------------------------------------------------ helpers

def die(msg):
    print("\n" + msg)
    sys.exit(1)


def ffmpeg(*args):
    if not shutil.which("ffmpeg"):
        die("ffmpeg isn't installed. Run: python tools/check_machine.py  (it shows how to get it)")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        die("ffmpeg had a problem:\n" + r.stderr[-800:])


def load_yaml(path, default=None):
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return default if default is not None else {}


def section_settings(profile, section):
    s = {k: profile.get(k) for k in ("exaggeration", "cfg_weight", "sample")}
    sec = (section or "").upper()
    best = ""
    for key, over in (profile.get("sections") or {}).items():
        if sec.startswith(str(key).upper()) and len(str(key)) > len(best):
            best = str(key)
            s.update(over or {})
    return s


def apply_pronunciations(text, pron):
    for word, say in pron.items():
        text = re.sub(rf"(?<![\w-]){re.escape(str(word))}(?![\w-])", str(say), text)
    return text


def chunk_text(text):
    """Split into sentence groups of at most MAX_CHUNK_CHARS."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if len(s) > MAX_CHUNK_CHARS:  # very long sentence: split on commas
            parts = re.split(r"(?<=[,;:])\s+", s)
        else:
            parts = [s]
        for part in parts:
            if cur and len(cur) + 1 + len(part) > MAX_CHUNK_CHARS:
                chunks.append(cur)
                cur = part
            else:
                cur = f"{cur} {part}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def prepare_reference(voice_dir, sample_name):
    """Clean copy of the owner's sample: mono 24 kHz, leading silence trimmed, max 20 s."""
    matches = [p for p in voice_dir.glob(sample_name + ".*")
               if p.suffix.lower() in (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".webm", ".mp4")
               and not p.name.startswith("reference")]
    if not matches:
        die(f"No voice sample found: put your recording in {voice_dir} named {sample_name}.m4a "
            f"(or .mp3 / .wav). See {voice_dir / 'README.md'}.")
    src = matches[0]
    ref = voice_dir / f"reference_{sample_name}.wav"
    if not ref.exists() or ref.stat().st_mtime < src.stat().st_mtime:
        print(f"Preparing your sample ({src.name})...")
        ffmpeg("-i", str(src), "-t", "60",
               "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                      "highpass=f=70,loudnorm=I=-20:TP=-2,atrim=0:20",
               "-ac", "1", "-ar", str(SR), str(ref))
    dur = sf.info(str(ref)).duration
    if dur < 6:
        die(f"Your sample is only {dur:.1f} seconds after trimming. Record 15-20 seconds (see README).")
    return ref


def file_hash(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()[:10]


# ------------------------------------------------------------------ the model

class Voice:
    def __init__(self, engine):
        self.engine = engine
        self.model = None
        self.cond_key = None

    def load(self):
        if self.model or FAKE:
            return
        import torch
        if torch.cuda.is_available():
            device = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            device = "mps"
        else:
            device = "cpu"
        print(f"Loading the {self.engine} voice model on {device.upper()} "
              f"(the first time, it downloads ~{'3' if self.engine == 'standard' else '2'} GB)...")
        if device == "cpu":
            print("No graphics card in use, so this will be slow (minutes per paragraph). Let it run.")
        if self.engine == "turbo":
            from chatterbox.tts_turbo import ChatterboxTurboTTS
            self.model = ChatterboxTurboTTS.from_pretrained(device=device)
        else:
            from chatterbox.tts import ChatterboxTTS
            self.model = ChatterboxTTS.from_pretrained(device=device)
        self.sr = self.model.sr

    def say(self, text, ref, exaggeration, cfg_weight, seed):
        if FAKE:  # a beep per chunk, length ~ text, for testing the pipeline
            n = int(SR * max(0.6, len(text) * 0.06))
            t = np.arange(n) / SR
            return (0.1 * np.sin(2 * np.pi * (180 + seed % 7 * 20) * t)).astype(np.float32)
        import torch
        self.load()
        key = (str(ref), exaggeration)
        if key != self.cond_key:
            if self.engine == "turbo":
                self.model.prepare_conditionals(str(ref))
            else:
                self.model.prepare_conditionals(str(ref), exaggeration=exaggeration)
            self.cond_key = key
        torch.manual_seed(seed)
        if self.engine == "turbo":
            wav = self.model.generate(text)
        else:
            wav = self.model.generate(text, exaggeration=exaggeration, cfg_weight=cfg_weight)
        audio = wav.squeeze().detach().cpu().numpy().astype(np.float32)
        if self.model.sr != SR:
            import librosa
            audio = librosa.resample(audio, orig_sr=self.model.sr, target_sr=SR)
        return audio


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Narrate script.md in your cloned voice")
    ap.add_argument("project")
    ap.add_argument("--voice", default="phill", help="folder in voices/ (default: phill)")
    ap.add_argument("--test", action="store_true", help="only HOOK and SETUP")
    ap.add_argument("--redo", default="", help="paragraph numbers to re-take, e.g. 12,15")
    ap.add_argument("--engine", choices=["standard", "turbo"], help="override profile.yaml")
    args = ap.parse_args()

    proj = Path(args.project)
    if not (proj / "script.md").exists():
        die(f"Can't find {proj / 'script.md'}.")
    voice_dir = ROOT / "voices" / args.voice
    profile = load_yaml(voice_dir / "profile.yaml")
    if not profile:
        die(f"Missing {voice_dir / 'profile.yaml'}.")
    pron = load_yaml(ROOT / "voices" / "pronunciations.yaml")
    engine = args.engine or profile.get("engine", "standard")

    out = proj / "build" / "narration"
    chunks_dir = out / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    redo_file = out / "redo_counts.json"
    redo_counts = json.loads(redo_file.read_text()) if redo_file.exists() else {}
    redo = {int(x) for x in re.findall(r"\d+", args.redo)}
    for n in redo:
        redo_counts[str(n)] = redo_counts.get(str(n), 0) + 1
    redo_file.write_text(json.dumps(redo_counts))

    _, paras = parse_script((proj / "script.md").read_text(encoding="utf-8"))
    paras = [p for p in paras if p["text"]]
    for i, p in enumerate(paras, 1):
        p["num"] = i
    if args.test:
        paras = [p for p in paras if (p["section"] or "").upper().startswith(("HOOK", "SETUP"))]

    refs = {}
    jobs = []  # (para, chunk_index, text, settings, path, seed)
    for p in paras:
        st = section_settings(profile, p["section"])
        sample = st.get("sample") or "sample"
        if sample not in refs:
            refs[sample] = prepare_reference(voice_dir, sample)
        ref = refs[sample]
        ex = float(st.get("exaggeration") or 0.5)
        cfg = float(st.get("cfg_weight") if st.get("cfg_weight") is not None else 0.5)
        take = redo_counts.get(str(p["num"]), 0)
        spoken = apply_pronunciations(p["text"], pron)
        for k, text in enumerate(chunk_text(spoken)):
            seed = 1000 + p["num"] * 50 + k + take * 7919
            key = hashlib.sha1(f"{text}|{engine}|{ex}|{cfg}|{file_hash(ref)}|{seed}".encode()).hexdigest()[:10]
            jobs.append((p, k, text, (ref, ex, cfg), chunks_dir / f"p{p['num']:03d}_c{k}_{key}.wav", seed))

    todo = [j for j in jobs if not j[4].exists()]
    print(f"{len(paras)} paragraphs, {len(jobs)} pieces. {len(jobs) - len(todo)} already done, "
          f"{len(todo)} to generate with the {engine} engine.")
    voice = Voice(engine)
    t0 = time.time()
    for n, (p, k, text, (ref, ex, cfg), path, seed) in enumerate(todo, 1):
        audio = voice.say(text, ref, ex, cfg, seed)
        sf.write(str(path), audio, SR)
        done_time = time.time() - t0
        eta = done_time / n * (len(todo) - n)
        print(f"  [{n}/{len(todo)}] paragraph {p['num']}  ({len(audio) / SR:.1f}s of audio)"
              f"  ~{eta / 60:.0f} min left")

    # ---- stitch everything together, in order, with pauses
    pause = {k: float(profile.get(k, d)) for k, d in
             (("pause_sentence", 0.15), ("pause_paragraph", 0.35), ("pause_section", 0.7))}
    pieces, timing, cursor = [], [], 0.0
    prev_para, prev_section = None, None
    for p, k, text, _, path, _ in jobs:
        audio, _sr = sf.read(str(path), dtype="float32")
        if pieces:
            if p is prev_para:
                gap = pause["pause_sentence"]
            elif p["section"] != prev_section:
                gap = pause["pause_section"]
            else:
                gap = pause["pause_paragraph"]
            pieces.append(np.zeros(int(SR * gap), dtype=np.float32))
            cursor += gap
        if p is not prev_para:
            timing.append({"num": p["num"], "section": p["section"], "start": round(cursor, 3),
                           "text": p["text"]})
        pieces.append(audio)
        cursor += len(audio) / SR
        timing[-1]["end"] = round(cursor, 3)
        prev_para, prev_section = p, p["section"]

    raw = out / "narration_raw.wav"
    sf.write(str(raw), np.concatenate(pieces), SR)
    speed = float(profile.get("speed", 1.0))
    final = out / "narration.wav"
    if abs(speed - 1.0) > 0.001:
        ffmpeg("-i", str(raw), "-af", f"atempo={speed}", str(final))
        for t in timing:
            t["start"] = round(t["start"] / speed, 3)
            t["end"] = round(t["end"] / speed, 3)
    else:
        shutil.copyfile(raw, final)
    ffmpeg("-i", str(final), "-b:a", "160k", str(out / "narration.mp3"))
    (out / "timing.json").write_text(json.dumps({"test": args.test, "speed": speed, "engine": engine,
                                                 "paragraphs": timing}, indent=1), encoding="utf-8")

    def fmt(s):
        return f"{int(s // 60)}:{s % 60:04.1f}"
    lines = ["# Narration paragraphs", "",
             "Didn't like one? Re-take it with `--redo <number>` (several: `--redo 3,12,15`).", "",
             "| # | Starts | Section | Text |", "|---|---|---|---|"]
    for t in timing:
        lines.append(f"| {t['num']} | {fmt(t['start'])} | {t['section']} | {t['text'][:90].replace('|', '/')} |")
    (out / "paragraphs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    total = timing[-1]["end"] if timing else 0
    print(f"\nDone: {fmt(total)} of narration.")
    print(f"  Listen:  {out / 'narration.mp3'}")
    print(f"  Paragraph numbers for --redo:  {out / 'paragraphs.md'}")
    print("  Mispronounced a word? Add it to voices/pronunciations.yaml, then --redo that paragraph.")


if __name__ == "__main__":
    main()
