"""ffmpeg helpers, finding the voice track, audio cleanup and music mixing."""

import json
import re
import shutil
import subprocess
from pathlib import Path

AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".webm"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


class EditorError(Exception):
    """A problem the owner can fix. The message is shown as-is, in plain English."""


def need_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise EditorError(f"{tool} isn't installed. Run `python tools/check_machine.py`; it shows how to get it.")


def run(cmd, cwd=None, what="ffmpeg"):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise EditorError(f"{what} failed:\n{r.stderr[-1500:]}")
    return r


def ffmpeg(*args, cwd=None):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], cwd=cwd)


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], what="ffprobe")
    return float(json.loads(r.stdout)["format"]["duration"])


def files_in(folder, exts):
    folder = Path(folder)
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts
                  and not p.name.startswith("."))


# ------------------------------------------------------------------ voice

def find_voice(proj):
    """Owner's recording(s) in voiceover/ win; otherwise the cloned-voice narration."""
    recs = files_in(proj / "voiceover", AUDIO_EXTS)
    if recs:
        return {"kind": "recorded", "files": recs}
    narr = proj / "build" / "narration" / "narration.wav"
    if narr.exists():
        timing = proj / "build" / "narration" / "timing.json"
        t = json.loads(timing.read_text(encoding="utf-8")) if timing.exists() else None
        return {"kind": "narration", "files": [narr], "timing": t}
    raise EditorError(
        f"No voiceover found. Put your recording in {proj / 'voiceover'} "
        f"(or make the AI narration with tools/narrate.py).")


def loudnorm(src, dst, target, extra_filters=""):
    """Two-pass loudness normalisation to `target` LUFS (accurate, no pumping)."""
    pre = (extra_filters + ",") if extra_filters else ""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-y", "-i", str(src), "-af",
                        f"{pre}loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        raise EditorError("Couldn't measure the voice loudness:\n" + r.stderr[-800:])
    s = json.loads(m.group(0))
    ffmpeg("-i", src, "-af",
           f"{pre}loudnorm=I={target}:TP=-1.5:LRA=11:measured_I={s['input_i']}:measured_TP={s['input_tp']}:"
           f"measured_LRA={s['input_lra']}:measured_thresh={s['input_thresh']}:offset={s['target_offset']}:"
           f"linear=true", "-ar", "48000", "-ac", "1", dst)


def prepare_voice(src_info, build, cfg):
    """Returns path of the cleaned voice (48 kHz mono WAV) and notes for the report."""
    a = cfg["audio"]
    notes = []
    joined = build / "voice_joined.wav"
    files = src_info["files"]
    if len(files) == 1:
        ffmpeg("-i", files[0], "-ac", "1", "-ar", "48000", joined)
    else:  # several takes: join them in name order
        lst = build / "voice_list.txt"
        tmp = []
        for i, f in enumerate(files):
            t = build / f"voice_part{i:02d}.wav"
            ffmpeg("-i", f, "-ac", "1", "-ar", "48000", t)
            tmp.append(t)
        lst.write_text("".join(f"file '{t.name}'\n" for t in tmp), encoding="utf-8")
        ffmpeg("-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", joined.name, cwd=build)
        notes.append(f"Joined {len(files)} voice files in name order: " + ", ".join(f.name for f in files))

    filters = []
    if src_info["kind"] == "recorded":
        filters.append("highpass=f=75")
        if a.get("denoise", True):
            filters.append(f"afftdn=nr={a.get('denoise_strength', 12)}:nf=-35:tn=1")
        if a.get("compress", True):
            filters.append("acompressor=threshold=-21dB:ratio=2.5:attack=8:release=120:makeup=1.5")
        if a.get("trim_silence", True):
            trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15")
            filters += [trim, "areverse", trim, "areverse"]
    else:
        notes.append("AI narration: skipped denoise/compression/trim (it's already clean), only set loudness.")
    clean = build / "voice_clean.wav"
    loudnorm(joined, clean, a.get("loudness", -14), ",".join(filters))
    return clean, notes


def find_music(root, cfg):
    m = str(cfg["music"].get("file", "auto"))
    if m.lower() == "none":
        return None
    folder = root / "assets" / "music"
    if m.lower() == "auto":
        tracks = files_in(folder, AUDIO_EXTS)
        return tracks[0] if tracks else None
    p = folder / m
    if not p.exists():
        raise EditorError(f"config.yaml asks for music '{m}', but it isn't in {folder}.")
    return p


def mix(voice, music, out, total, cfg):
    """Voice + optional ducked music, padded to `total` seconds, final limiter."""
    mc = cfg["music"]
    if music is None:
        ffmpeg("-i", voice, "-af", f"apad=whole_dur={total:.3f},alimiter=limit=0.89", "-ar", "48000", "-ac", "2", out)
        return
    vol = mc.get("volume_db", -20)
    fi, fo = mc.get("fade_in", 1.5), mc.get("fade_out", 4)
    music_chain = (f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={vol}dB,"
                   f"atrim=0:{total:.3f},afade=t=in:d={fi},afade=t=out:st={max(0, total - fo):.3f}:d={fo}[m];")
    voice_chain = f"[0:a]apad=whole_dur={total:.3f},aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v][sc];"
    if mc.get("duck", True):
        duck = "[m][sc]sidechaincompress=threshold=0.015:ratio=6:attack=25:release=450:makeup=1[md];"
        mixin = "[v][md]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[out]"
    else:
        duck = "[sc]anullsink;"
        mixin = "[v][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[out]"
    ffmpeg("-i", voice, "-stream_loop", "-1", "-i", music, "-filter_complex",
           music_chain + voice_chain + duck + mixin, "-map", "[out]", "-t", f"{total:.3f}", "-ar", "48000", out)


def apply_cuts(src, dst, cuts):
    """Remove the (start, end) ranges from the audio, with tiny fades so cuts don't click."""
    if not cuts:
        return
    keep, t = [], 0.0
    for a, b in cuts:
        if a > t:
            keep.append((t, a))
        t = b
    keep.append((t, None))
    parts, labels = [], []
    for i, (a, b) in enumerate(keep):
        trim = f"atrim=start={a:.3f}" + (f":end={b:.3f}" if b is not None else "")
        dur = (b - a) if b is not None else None
        fade = "afade=t=in:d=0.015"
        if dur:
            fade += f",afade=t=out:st={max(dur - 0.015, 0):.3f}:d=0.015"
        parts.append(f"[0:a]{trim},asetpts=PTS-STARTPTS,{fade}[p{i}]")
        labels.append(f"[p{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    ffmpeg("-i", src, "-filter_complex", graph, "-map", "[out]", dst)
