"""Word timing: transcribe the voice, line it up with script.md, build captions."""

import difflib
import hashlib
import json
import re
from pathlib import Path

from .media import EditorError


_NUM = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
        "sixteen seventeen eighteen nineteen twenty").split()
_ABBR = {"dr": "doctor", "mr": "mister", "mrs": "missus", "vs": "versus", "st": "saint"}


def norm(w):
    """Comparable form of a word: lowercase letters/digits; "4" == "four", "Dr." == "Doctor"."""
    n = re.sub(r"[^a-z0-9]", "", w.lower().replace("’", "'"))
    if n.isdigit() and int(n) <= 20:
        return _NUM[int(n)]
    m = re.fullmatch(r"(\d+)(st|nd|rd|th)", n)
    if m and int(m.group(1)) <= 20:
        return _NUM[int(m.group(1))]
    return _ABBR.get(n, n)


def script_words(paras):
    """Every spoken word of the script, in order, with its paragraph index. Keeps real spelling."""
    out = []
    for pi, p in enumerate(paras):
        for w in p["text"].split():
            if norm(w):
                out.append({"w": w, "n": norm(w), "para": pi})
    return out


# ------------------------------------------------------------------ transcription

def transcribe(audio, cfg, cache_dir, prompt=""):
    """Word-level transcript via faster-whisper (local, free). Cached by audio hash."""
    tc = cfg["transcribe"]
    h = hashlib.sha1(Path(audio).read_bytes()).hexdigest()[:12]
    cache = Path(cache_dir) / f"transcript_v2_{tc['model']}_{h}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise EditorError("The transcriber isn't installed. Run setup again (setup.bat / bash setup.sh).")
    try:
        import ctranslate2
        gpu = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        gpu = False
    print(f"  Transcribing with Whisper '{tc['model']}' on {'GPU' if gpu else 'CPU'} "
          f"(the first time, it downloads the model)...")
    try:
        model = WhisperModel(tc["model"], device="cuda" if gpu else "cpu",
                             compute_type="float16" if gpu else "int8")
    except Exception as e:
        raise EditorError(f"Couldn't load the Whisper model ({type(e).__name__}: {e}). "
                          f"Check your internet for the first-time download.")
    # decode with ffmpeg ourselves: avoids faster-whisper's PyAV version clashes
    import subprocess
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    if not samples.size:
        raise EditorError("Couldn't read the voiceover audio for transcription.")
    segments, info = model.transcribe(samples, language=tc.get("language", "en"), word_timestamps=True,
                                      initial_prompt=prompt[:800] or None, vad_filter=False,  # VAD hid false starts
                                      condition_on_previous_text=False)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"w": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)})
        print(f"    ...{seg.end / 60:.1f} min", end="\r")
    print()
    cache.write_text(json.dumps(words), encoding="utf-8")
    return words


# ------------------------------------------------------------------ alignment

def _fill_gaps(times, total):
    """Linear-interpolate words that weren't matched, between their matched neighbours."""
    n = len(times)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        left = times[i - 1][1] if i > 0 else 0.0
        right = times[j][0] if j < n else total
        step = max(right - left, 0) / (j - i)
        for k in range(i, j):
            s = left + step * (k - i)
            times[k] = (s, s + step)
        i = j
    # keep it in order
    last = 0.0
    for k in range(n):
        s, e = times[k]
        s = max(s, last)
        e = max(e, s + 0.05)
        times[k] = (s, e)
        last = s
    return times


def align(swords, transcript, total):
    """Give every script word a (start, end) from the transcript. Returns match ratio 0-1."""
    s_norm = [w["n"] for w in swords]
    t_norm = [norm(w["w"]) for w in transcript]
    sm = difflib.SequenceMatcher(None, s_norm, t_norm, autojunk=False)
    times = [None] * len(swords)
    matched = 0
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            t = transcript[b + k]
            times[a + k] = (t["start"], t["end"])
            matched += 1
    _fill_gaps(times, total)
    for w, (s, e) in zip(swords, times):
        w["start"], w["end"] = round(s, 3), round(e, 3)
    return matched / max(len(swords), 1)


def from_narration_timing(swords, paras, timing):
    """No transcriber needed: the cloned-voice tool recorded when each paragraph starts/ends.
    Spread words inside a paragraph by length (punctuation gets a little extra time)."""
    by_text = {}
    for t in timing["paragraphs"]:
        by_text.setdefault(t["text"], []).append(t)
    spans = []
    for p in paras:
        lst = by_text.get(p["text"])
        if not lst:
            raise EditorError("The narration doesn't match script.md anymore (the script changed). "
                              "Run tools/narrate.py again.")
        spans.append(lst.pop(0))
    for pi, span in enumerate(spans):
        ws = [w for w in swords if w["para"] == pi]
        weights = [len(w["n"]) + 2 + (3 if re.search(r"[.!?]$", w["w"]) else 2 if w["w"].endswith(",") else 0)
                   for w in ws]
        total_w = sum(weights) or 1
        t = span["start"]
        dur = span["end"] - span["start"]
        for w, wt in zip(ws, weights):
            d = dur * wt / total_w
            w["start"], w["end"] = round(t, 3), round(t + d, 3)
            t += d


# ------------------------------------------------------------------ captions

def _groups(words, max_chars=None, max_words=None, max_secs=4.0):
    groups, cur = [], []
    for w in words:
        if cur:
            text = " ".join(x["w"] for x in cur + [w])
            too_long = (max_chars and len(text) > max_chars) or (max_words and len(cur) >= max_words)
            if too_long or w["start"] - cur[0]["start"] > max_secs:
                groups.append(cur)
                cur = []
        cur.append(w)
        if re.search(r"[.!?]$", w["w"]) and (max_words or len(" ".join(x["w"] for x in cur)) >= 12):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    cues = []
    for i, g in enumerate(groups):
        start = g[0]["start"]
        end = g[-1]["end"]
        nxt = groups[i + 1][0]["start"] if i + 1 < len(groups) else end + 1
        end = min(max(end, start + 0.8), nxt - 0.02)
        cues.append((start, max(end, start + 0.3), " ".join(x["w"] for x in g)))
    return cues


def _srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(words, path, max_chars=42):
    cues = _groups(words, max_chars=max_chars)
    lines = []
    for i, (s, e, text) in enumerate(cues, 1):
        lines += [str(i), f"{_srt_time(s)} --> {_srt_time(e)}", text, ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return len(cues)


def _ass_time(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(words, path, cfg, width, height, max_words=None, uppercase=True, margin_v=None, banner=None,
              banner_end=None, size=None, banner_size=None):
    c = cfg["captions"]
    scale = height / 1080
    if width < height:  # vertical (Shorts): bigger relative to width, higher up
        scale = width / 1080 * 1.15
    size = int(size or c.get("size", 66) * scale)
    banner_size = int(banner_size or size * 0.8)
    outline = max(1, int(c.get("outline", 5) * scale))
    margin = int(margin_v if margin_v is not None else c.get("bottom_margin", 90) * (height / 1080))
    col = "&H00" + _bgr(c.get("color", "FFFFFF"))
    ocol = "&H00" + _bgr(c.get("outline_color", "000000"))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{c.get('font', 'Arial Black')},{size},{col},{col},{ocol},&H64000000,-1,0,0,0,100,100,0,0,1,{outline},{max(1, outline // 2)},2,60,60,{margin},1
Style: Banner,{c.get('font', 'Arial Black')},{banner_size},&H0000D4FF,&H0000D4FF,{ocol},&H64000000,-1,0,0,0,100,100,0,0,1,{outline},{max(1, outline // 2)},8,50,50,{int(height * 0.1)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    rows = []
    if banner and banner_end:
        b = banner.upper().replace("{", "(").replace("}", ")")
        rows.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(banner_end)},Banner,,0,0,0,,{b}")
    for s, e, text in _groups(words, max_words=max_words or c.get("burn_words", 5), max_chars=34):
        text = text.upper() if uppercase else text
        text = text.replace("{", "(").replace("}", ")")
        rows.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Cap,,0,0,0,,{text}")
    Path(path).write_text(head + "\n".join(rows) + "\n", encoding="utf-8")


def _bgr(hexrgb):
    h = str(hexrgb).lstrip("#").upper().rjust(6, "0")
    return h[4:6] + h[2:4] + h[0:2]


# ------------------------------------------------------------------ retakes and long pauses

FILLERS = {"uh", "um", "uhm", "er", "erm", "ah", "hmm", "mm"}


def find_cuts(swords, transcript, total, max_pause=1.0, keep_pause=0.45, cut_retakes=True):
    """Spots false starts (words said, then restarted, that the script only has once), filler sounds,
    and long pauses. Returns (cuts, notes): cuts = list of (start, end) seconds to remove."""
    s_norm = [w["n"] for w in swords]
    t_norm = [norm(w["w"]) for w in transcript]
    sm = difflib.SequenceMatcher(None, s_norm, t_norm, autojunk=False)
    t_to_s = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            t_to_s[b + k] = a + k
    cuts, notes, drop = [], [], set()
    if cut_retakes:
        i, n = 0, len(transcript)
        while i < n:
            if i in t_to_s or not t_norm[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and (j + 1) not in t_to_s:
                j += 1
            run = [t_norm[k] for k in range(i, j + 1) if t_norm[k]]
            prev_s = max([t_to_s[k] for k in t_to_s if k < i], default=-1)
            window = set(s_norm[max(0, prev_s - 15):prev_s + 25])
            near = sum(1 for w in run if w in window) / max(len(run), 1)
            is_filler = all(w in FILLERS for w in run)
            if is_filler or (len(run) >= 2 and near >= 0.6):
                start = transcript[i]["start"]
                end = transcript[j + 1]["start"] - 0.06 if j + 1 < n else transcript[j]["end"]
                if end - start > 0.15:
                    cuts.append((start, end))
                    drop.update(range(i, j + 1))
                    notes.append(f"{_mmss(start)}: cut {'filler' if is_filler else 'retake'} "
                                 f"\"{' '.join(transcript[k]['w'] for k in range(i, j + 1))}\" ({end - start:.1f}s)")
            i = j + 1
    kept = [w for k, w in enumerate(transcript) if k not in drop]
    for a, b in zip(kept, kept[1:]):
        gap = b["start"] - a["end"]
        if gap > max_pause and not any(cs <= a["end"] + 0.01 and ce >= b["start"] - 0.1 for cs, ce in cuts):
            cuts.append((a["end"] + keep_pause / 2, b["start"] - keep_pause / 2))
            notes.append(f"{_mmss(a['end'])}: shortened a {gap:.1f}s pause")
    cuts.sort()
    merged = []
    for c in cuts:
        if merged and c[0] <= merged[-1][1] + 0.05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], c[1]))
        else:
            merged.append(c)
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a > 0.05], notes


def shift_words(transcript, cuts):
    """Drop words inside cuts and move later words earlier by the time removed before them."""
    out = []
    for w in transcript:
        if any(a <= (w["start"] + w["end"]) / 2 <= b for a, b in cuts):
            continue
        before = sum(b - a for a, b in cuts if b <= w["start"] + 0.001)
        out.append(dict(w, start=round(w["start"] - before, 3), end=round(w["end"] - before, 3)))
    return out


def _mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"
