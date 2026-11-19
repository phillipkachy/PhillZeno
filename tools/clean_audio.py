"""
Clean up a voice recording: no script needed.

Run:   python tools/clean_audio.py inbox/my_recording.m4a
       python tools/clean_audio.py inbox/my_recording.m4a --cut 4:32.8-4:42.2 --cut 1:10-1:12

What it does (your original file is never changed):
  1. cuts any ranges you name with --cut (retakes, coughs, "let me start over")
  2. shortens long pauses (over audio.max_pause in config.yaml, default 1 s) using a local transcript
  3. removes background hiss/hum, gentle compression, trims silence at the start and end
  4. sets loudness to YouTube's -14 LUFS
Writes next to the original's name in inbox/cleaned/: <name>_clean.wav (best quality, for the editor)
and <name>_clean.m4a (small, for listening on your phone), plus <name>_clean.txt (what was changed).
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from make_video import load_config  # noqa: E402
from pzlib import media, words as W  # noqa: E402
from pzlib.media import EditorError  # noqa: E402


def parse_time(t):
    parts = [float(x) for x in t.split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def main():
    ap = argparse.ArgumentParser(description="Clean up a voice recording")
    ap.add_argument("file")
    ap.add_argument("--cut", action="append", default=[], help="time range to remove, e.g. 4:32.8-4:42.2")
    ap.add_argument("--keep-pauses", action="store_true", help="don't shorten long pauses")
    ap.add_argument("--out", help="output folder (default: inbox/cleaned)")
    args = ap.parse_args()
    src = Path(args.file)
    if not src.exists():
        raise EditorError(f"Can't find {src}.")
    media.need_ffmpeg()
    cfg = load_config(ROOT)
    out = Path(args.out) if args.out else ROOT / "inbox" / "cleaned"
    out.mkdir(parents=True, exist_ok=True)
    work = out / ".work"
    work.mkdir(exist_ok=True)
    stem = src.stem
    notes = []

    wav = work / f"{stem}_48k.wav"
    media.ffmpeg("-i", src, "-ac", "1", "-ar", "48000", wav)
    before = media.duration(wav)

    cuts = []
    for c in args.cut:
        m = re.fullmatch(r"\s*([\d:.]+)\s*-\s*([\d:.]+)\s*", c)
        if not m:
            raise EditorError(f"--cut {c}: use start-end, like 4:32.8-4:42.2")
        a, b = parse_time(m.group(1)), parse_time(m.group(2))
        if b <= a:
            raise EditorError(f"--cut {c}: the end must be after the start")
        cuts.append((a, b))
        notes.append(f"Cut {c} (you asked)")

    max_pause = cfg["audio"].get("max_pause") or 0
    if max_pause and not args.keep_pauses:
        print("Transcribing to find long pauses (local Whisper)...")
        transcript = W.transcribe(wav, cfg, work)
        kept = [w for w in transcript if not any(a <= (w["start"] + w["end"]) / 2 <= b for a, b in cuts)]
        for x, y in zip(kept, kept[1:]):
            gap = y["start"] - x["end"]
            inside = any(a < y["start"] and b > x["end"] for a, b in cuts)  # pause touches a cut: skip
            if gap > max_pause and not inside:
                cuts.append((x["end"] + 0.225, y["start"] - 0.225))
                notes.append(f"Shortened a {gap:.1f}s pause at {int(x['end'] // 60)}:{x['end'] % 60:04.1f}")
    cuts.sort()
    merged = []
    for c in cuts:
        if merged and c[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], c[1]))
        else:
            merged.append(c)
    edited = wav
    if merged:
        edited = work / f"{stem}_cut.wav"
        media.apply_cuts(wav, edited, merged)

    a = cfg["audio"]
    filters = ["highpass=f=75"]
    if a.get("denoise", True):
        filters.append(f"afftdn=nr={a.get('denoise_strength', 12)}:nf=-35:tn=1")
    if a.get("compress", True):
        filters.append("acompressor=threshold=-21dB:ratio=2.5:attack=8:release=120:makeup=1.5")
    if a.get("trim_silence", True):
        trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15"
        filters += [trim, "areverse", trim, "areverse"]
    final_wav = out / f"{stem}_clean.wav"
    media.loudnorm(edited, final_wav, a.get("loudness", -14), ",".join(filters))
    final_m4a = out / f"{stem}_clean.m4a"
    media.ffmpeg("-i", final_wav, "-c:a", "aac", "-b:a", "192k", final_m4a)
    after = media.duration(final_wav)

    report = [f"Cleaned: {src.name}",
              f"Length: {int(before // 60)}:{before % 60:04.1f} -> {int(after // 60)}:{after % 60:04.1f} "
              f"({before - after:.1f}s removed)",
              f"Loudness: {a.get('loudness', -14)} LUFS (YouTube standard)",
              "Changes:"] + [f"  - {n}" for n in notes or ["(no cuts)"]]
    (out / f"{stem}_clean.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"\nListen:  {final_m4a}\nFor the editor:  {final_wav}")


if __name__ == "__main__":
    try:
        main()
    except EditorError as e:
        print("\n❌ " + str(e))
        sys.exit(1)
