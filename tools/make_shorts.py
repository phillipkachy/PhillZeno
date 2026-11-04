"""
Shorts: cut 3-5 vertical Shorts out of your finished video.

First make the long video (make_video.py, preview or final). Then:
  python tools/make_shorts.py projects/avengers-doomsday            pick moments + render them
  python tools/make_shorts.py projects/avengers-doomsday --pick     only pick moments (writes shorts.yaml), no render
  python tools/make_shorts.py projects/avengers-doomsday --preview  quick low-res versions

How moments are chosen:
  - If projects/<name>/shorts.yaml exists, it's used exactly. Claude writes it, or you edit it.
  - Otherwise the tool scores every 20-55 second stretch of the script (strong opening line, no
    "and/so/but" start, names and numbers, a short punchy last line) and writes its picks to
    shorts.yaml so you can tweak them.

Output: output/shorts/short_1.mp4 ... (1080x1920, captions burned in) and output/shorts/shorts.md
(title + description for each). Nothing of yours is changed.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from make_video import load_config  # noqa: E402
from pzlib import media, render, words as W  # noqa: E402
from pzlib.media import EditorError  # noqa: E402

MIN_S, MAX_S = 20.0, 55.0
CONNECTORS = {"and", "but", "so", "then", "now", "because", "or", "also", "that", "this", "it", "which",
              "they", "he", "she", "plus", "meanwhile", "okay", "well"}
SHORT_MOVES = ["pan_right", "zoom_in", "pan_left", "zoom_out"]


def sentences(words, paras_sections):
    out, cur = [], []
    for w in words:
        cur.append(w)
        if re.search(r"[.!?][\"'”’)]*$", w["w"]):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"text": " ".join(x["w"] for x in s), "start": s[0]["start"], "end": s[-1]["end"],
             "para": s[0]["para"], "end_para": s[-1]["para"], "words": s,
             "section": paras_sections.get(s[0]["para"], "")} for s in out]


def score(window, sents):
    first, last = window[0], window[-1]
    fw = re.sub(r"[^a-z']", "", first["text"].split()[0].lower())
    sc = 0.0
    sc += -3 if fw in CONNECTORS else 2
    if "?" in first["text"]:
        sc += 1.5
    if len(first["text"].split()) <= 12:
        sc += 1
    body = " ".join(s["text"] for s in window)
    sc += min(len(re.findall(r"\b(?:[A-Z][a-z]+|\d+)\b", body)) * 0.08, 2)
    if len(last["text"].split()) <= 8:
        sc += 1.5
    if last["text"].rstrip().endswith("?"):
        sc -= 0.5
    nxt = sents.index(last) + 1
    if nxt >= len(sents) or sents[nxt]["para"] != last["para"]:
        sc += 1  # ends where a paragraph ends
    sec = first["section"].upper()
    if sec.startswith(("HOOK", "PAYOFF")):
        sc += 1
    if sec.startswith("OUTRO"):
        sc -= 6
    if sec.startswith("SETUP"):
        sc -= 1
    dur = last["end"] - first["start"]
    if 28 <= dur <= 50:
        sc += 1
    return sc


def auto_pick(sents, n):
    cands = []
    for i in range(len(sents)):
        for j in range(i, len(sents)):
            dur = sents[j]["end"] - sents[i]["start"]
            if dur > MAX_S:
                break
            if dur >= MIN_S:
                cands.append((score(sents[i:j + 1], sents), i, j))
    cands.sort(reverse=True)
    picks = []
    for sc, i, j in cands:
        if all(j < a or i > b for _, a, b in picks):
            picks.append((sc, i, j))
        if len(picks) == n:
            break
    return sorted(picks, key=lambda x: x[1])


def find_sentence(sents, text, from_end=False):
    """Index of the sentence a 'from' line starts in (or a 'to' line ends in). Lines may span sentences."""
    key = W.norm(text)
    norms = [W.norm(x["text"]) for x in sents]
    for i in range(len(sents)):
        if from_end:
            joined = "".join(norms[max(0, i - 4):i + 1])
            if joined.endswith(key):
                return i
        else:
            joined = "".join(norms[i:i + 5])
            if joined.startswith(key):
                return i
    return None


def main():
    ap = argparse.ArgumentParser(description="Make vertical Shorts from the finished video")
    ap.add_argument("project")
    ap.add_argument("--count", type=int, default=4, help="how many Shorts to pick automatically (3-5)")
    ap.add_argument("--pick", action="store_true", help="only pick moments, don't render")
    ap.add_argument("--preview", action="store_true", help="quick low-resolution render")
    args = ap.parse_args()
    proj = Path(args.project)
    build = proj / "build"
    for need in ("timeline.json", "words.json", "voice_clean.wav"):
        if not (build / need).exists():
            raise EditorError("Make the long video first (it builds the timing the Shorts reuse):\n"
                              f"  python tools/make_video.py {proj} --preview")
    media.need_ffmpeg()
    cfg = load_config(proj)
    words = json.loads((build / "words.json").read_text(encoding="utf-8"))
    timeline = json.loads((build / "timeline.json").read_text(encoding="utf-8"))
    from script_check import parse_script
    _, paras = parse_script((proj / "script.md").read_text(encoding="utf-8"))
    paras = [p for p in paras if p["text"]]
    sents = sentences(words, {i: p["section"] or "" for i, p in enumerate(paras)})

    # ---- choose the moments
    yfile = proj / "shorts.yaml"
    if yfile.exists():
        plan = yaml.safe_load(yfile.read_text(encoding="utf-8")) or {}
        picks = []
        for k, sh in enumerate(plan.get("shorts", []), 1):
            i, j = find_sentence(sents, sh["from"]), find_sentence(sents, sh["to"], from_end=True)
            if i is None or j is None or j < i:
                raise EditorError(f"shorts.yaml, Short {k}: couldn't find the 'from'/'to' lines in the script. "
                                  f"Copy the words exactly from script.md.")
            picks.append((sh, i, j))
        source = "shorts.yaml"
    else:
        picks = []
        for sc, i, j in auto_pick(sents, max(1, min(args.count, 5))):
            first = sents[i]["text"]
            picks.append(({"from": " ".join(first.split()[:6]),
                           "to": " ".join(sents[j]["text"].split()[-5:]),
                           "banner": " ".join(re.sub(r"[^\w' ]", "", first).split()[:4]),
                           "title": first[:90],
                           "description": "Full breakdown on my channel."}, i, j))
        yfile.write_text("# Picked automatically. Edit freely, then re-run make_shorts.py.\n"
                         "# from/to = the first words of the opening line / last words of the closing line.\n"
                         "# banner = big text pinned at the top (3-5 words).\n" +
                         yaml.safe_dump({"shorts": [p[0] for p in picks]}, sort_keys=False, allow_unicode=True),
                         encoding="utf-8")
        source = "automatic picks (saved to shorts.yaml)"
    print(f"{len(picks)} Shorts from {source}:")
    for k, (sh, i, j) in enumerate(picks, 1):
        dur = sents[j]["end"] - sents[i]["start"]
        flag = "" if MIN_S <= dur <= 60 else "  ⚠️ outside 20-60 s"
        print(f"  {k}. {sents[i]['start'] / 60:4.1f} min, {dur:4.1f}s  \"{sents[i]['text'][:60]}\"{flag}")
    if args.pick:
        print(f"\nEdit {yfile} if you like, then run without --pick to render.")
        return

    # ---- render each
    sc = cfg.get("shorts", {})
    if args.preview:
        w, h, fps, preset, crf = 540, 960, 15, "ultrafast", 28
    else:
        w, h, fps, preset, crf = 1080, 1920, cfg["video"]["fps"], cfg["video"]["preset_final"], cfg["video"]["crf"]
    outdir = proj / "output" / "shorts"
    outdir.mkdir(parents=True, exist_ok=True)
    work = build / "shorts"
    work.mkdir(exist_ok=True)
    music = media.find_music(ROOT, cfg)
    md = ["# Shorts", "", "Upload each as a Short. Title and description are ready to paste.", ""]
    for k, (sh, i, j) in enumerate(picks, 1):
        s0 = max(sents[i]["start"] - 0.1, 0)
        s1 = sents[j]["end"] + 0.5
        dur = s1 - s0
        voice = work / f"voice_{k}.wav"
        media.ffmpeg("-ss", f"{s0:.3f}", "-t", f"{dur:.3f}", "-i", build / "voice_clean.wav", voice)
        mixed = work / f"mix_{k}.wav"
        media.mix(voice, music, mixed, dur, cfg)
        # pictures: the long video's timeline inside this window, shifted to start at 0
        segs, mv = [], 0
        for seg in timeline["segments"]:
            a, b = max(seg["start"], s0), min(seg["end"], s1)
            if b - a < 0.05:
                continue
            if seg["kind"] == "clip":
                segs.append(render.Clip(seg["path"], a - s0, b - s0, offset=a - seg["start"]))
            else:
                segs.append(render.Still(seg["path"], a - s0, b - s0, SHORT_MOVES[mv % len(SHORT_MOVES)],
                                         tuple(seg.get("focus") or (0.5, 0.5))))
                mv += 1
        if not segs:
            raise EditorError(f"Short {k}: no pictures found in that part of the video.")
        segs[0].start = 0.0
        swords = [dict(x, start=round(x["start"] - s0, 3), end=round(x["end"] - s0, 3))
                  for x in words if s0 <= x["start"] < s1]
        subs = work / f"captions_{k}.ass"
        W.write_ass(swords, subs, cfg, w, h, max_words=sc.get("caption_words", 3),
                    margin_v=int(h * sc.get("caption_height", 0.30)),
                    banner=sh.get("banner"), banner_end=dur,
                    size=int(sc.get("caption_size", 115) * w / 1080),
                    banner_size=int(sc.get("banner_size", 95) * w / 1080))
        out = outdir / f"short_{k}{'_preview' if args.preview else ''}.mp4"
        print(f"Rendering Short {k} ({dur:.0f}s)...")
        render.encode(segs, mixed, out, dur, cfg, w, h, fps, preset, crf, subs=subs, workdir=work,
                      label=f"short {k}")
        tags = " ".join("#" + t for t in (sc.get("hashtags") or ["Shorts"]))
        md += [f"## Short {k}: `{out.name}` ({dur:.0f}s)", "", f"**Title:** {sh.get('title', '')}", "",
               "**Description:**", "", "```", f"{sh.get('description', '').strip()}\n\n{tags}", "```", "",
               f"_Starts with:_ \"{sents[i]['text']}\"", ""]
    (outdir / "shorts.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nDone. Shorts in {outdir}  (titles + descriptions: {outdir / 'shorts.md'})")


if __name__ == "__main__":
    try:
        main()
    except EditorError as e:
        print("\n❌ " + str(e))
        sys.exit(1)
