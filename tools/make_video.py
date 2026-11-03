"""
PhillZeno auto-editor: voiceover + your images  ->  finished YouTube video.

Run:
  python tools/make_video.py projects/avengers-doomsday --preview     quick low-res check (do this first)
  python tools/make_video.py projects/avengers-doomsday               full 1080p final render
Extras:
  --fast         final size but quicker encoding (bigger file), good for testing
  --burn         burn captions into the picture
  --seconds 60   only the first 60 seconds (great for a quick test)

Reads (never changes): script.md, voiceover/ (or build/narration/ from narrate.py), images/, clips/,
                       assets/music/, config.yaml
Writes: output/<name>.mp4 (or <name>_preview.mp4), output/<name>.srt, output/report.md, build/...
"""

import argparse
import copy
import json
import math
import re
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from script_check import parse_script  # noqa: E402
from pzlib import media, words as W, render  # noqa: E402
from pzlib.media import EditorError  # noqa: E402

DEFAULTS = {
    "video": {"width": 1920, "height": 1080, "fps": 30, "preset_final": "medium", "preset_test": "veryfast",
              "crf": 18, "max_bitrate": "12M"},
    "preview": {"width": 640, "height": 360, "fps": 15},
    "images": {"min_seconds": 4, "max_seconds": 8, "target_seconds": 6, "fill": "smart",
               "blur_background_if_aspect_below": 1.45, "blur_background_if_aspect_above": 2.3},
    "ken_burns": {"zoom": 0.12, "moves": ["zoom_in", "pan_right", "zoom_out", "pan_left"], "ease": 0.35,
                  "transition": "cut", "fade_seconds": 0.25},
    "audio": {"denoise": True, "denoise_strength": 12, "compress": True, "trim_silence": True,
              "loudness": -14, "tail_seconds": 1.0},
    "music": {"file": "auto", "volume_db": -20, "duck": True, "fade_in": 1.5, "fade_out": 4},
    "transcribe": {"model": "small", "language": "en"},
    "captions": {"srt": True, "burn": False, "max_chars": 42, "burn_words": 5, "font": "Arial Black",
                 "size": 66, "color": "FFFFFF", "outline_color": "000000", "outline": 5, "bottom_margin": 90},
}
FOCUS = [(0.5, 0.45), (0.33, 0.42), (0.67, 0.42), (0.5, 0.6), (0.4, 0.35), (0.6, 0.55)]
CUT_LEAD = 0.12  # change picture a hair before the words, like a human editor


def merge(a, b):
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(proj):
    cfg = DEFAULTS
    for p in (ROOT / "config.yaml", proj / "config.yaml"):
        if p.exists():
            try:
                cfg = merge(cfg, yaml.safe_load(p.read_text(encoding="utf-8")) or {})
            except yaml.YAMLError as e:
                raise EditorError(f"{p} has a typo (check spaces/colons):\n{e}")
    return cfg


def fmt(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def shot_files(proj, shot):
    def pick(folder, exts):
        fs = [f for f in media.files_in(proj / folder, exts) if re.match(rf"^{shot}(\D|$)", f.name)]
        return sorted(fs, key=lambda f: (f.stem != shot, f.name))  # 001.jpg before 001-2.jpg
    return pick("images", media.IMAGE_EXTS), pick("clips", media.VIDEO_EXTS)


# ------------------------------------------------------------------ timeline

def build_timeline(proj, paras, swords, total, cfg, report):
    ic = cfg["images"]
    moves = cfg["ken_burns"].get("moves") or ["zoom_in"]
    # 1. when each paragraph starts
    first_word = {}
    for w in swords:
        first_word.setdefault(w["para"], w["start"])
    bounds = []
    for i in range(len(paras)):
        s = 0.0 if i == 0 else max(first_word.get(i, bounds[-1]) - CUT_LEAD, bounds[-1] + 0.3)
        bounds.append(min(s, total))
    bounds.append(total)

    # 2. split each paragraph's time between its cues (a paragraph with no cue extends the previous shot)
    shots = []
    for i, p in enumerate(paras):
        s, e = bounds[i], bounds[i + 1]
        if not p["cues"]:
            if shots:
                shots[-1]["end"] = e
            continue
        n = len(p["cues"])
        for k, c in enumerate(p["cues"]):
            shots.append({**c, "start": s + (e - s) * k / n, "end": s + (e - s) * (k + 1) / n})
    if shots:
        shots[0]["start"] = 0.0
        shots[-1]["end"] = total

    # 3. turn shots into picture segments
    all_imgs = [f for f in media.files_in(proj / "images", media.IMAGE_EXTS)]
    if not all_imgs and not media.files_in(proj / "clips", media.VIDEO_EXTS):
        raise EditorError(f"No images found in {proj / 'images'}. Collect them first: "
                          f"python tools/find_images.py {proj} --auto")
    segs, mv = [], 0
    last_img = None
    for sh in shots:
        imgs, clips = shot_files(proj, sh["shot"])
        sh["files"] = [f.name for f in clips or imgs]
        dur = sh["end"] - sh["start"]
        if sh["kind"] == "CLIP" and clips:
            segs.append(render.Clip(clips[0], sh["start"], sh["end"]))
            continue
        if sh["kind"] == "CLIP":
            report["clip_as_image" if imgs else "missing"].append(sh)
        if not imgs:
            if sh not in report["missing"]:
                report["missing"].append(sh)
            fallback = last_img or next((f for f in all_imgs), None)
            if fallback is None:
                continue
            imgs = [fallback]
            sh["fallback"] = fallback.name
        per = dur / len(imgs)
        for f in imgs:
            n = math.ceil(per / ic["target_seconds"]) if per > ic["max_seconds"] else 1
            if n > 1 and len(imgs) == 1:
                report["long_holds"].append({**sh, "secs": per})
            t = sh["start"] + per * imgs.index(f)
            for k in range(n):
                segs.append(render.Still(f, t + per * k / n, t + per * (k + 1) / n,
                                         moves[mv % len(moves)], FOCUS[(mv + k) % len(FOCUS)] if n > 1 else FOCUS[0]))
                mv += 1
            last_img = f
    segs.sort(key=lambda s: s.start)
    report["shots"] = shots

    # 4. image checks
    from PIL import Image
    used = set()
    for s in segs:
        if s.kind == "image":
            used.add(s.path)
    for f in sorted(used):
        try:
            with Image.open(f) as im:
                if im.width < 1280:
                    report["small"].append((f.name, f"{im.width}x{im.height}"))
                if im.width / im.height < 1.2:
                    report["portrait"].append(f.name)
        except Exception:
            raise EditorError(f"Can't open image {f}. Is it a real picture? Replace or remove it.")
    shot_ids = {sh["shot"] for sh in shots}
    report["unused"] = [f.name for f in all_imgs if f.name[:3] not in shot_ids or not f.name[:3].isdigit()]
    return segs


# ------------------------------------------------------------------ report

def write_report(path, r):
    L = [f"# Edit report: {r['name']}", "", f"_Made {time.strftime('%Y-%m-%d %H:%M')} · mode: {r['mode']}_", "",
         "## Summary", "",
         f"- **Runtime:** {fmt(r['total'])}",
         f"- **Voice:** {r['voice']}",
         f"- **Timing:** {r['timing']}",
         f"- **Music:** {r['music'] or 'none (add a track to assets/music/ for background music)'}",
         f"- **Shots:** {len(r['shots'])} · picture changes: {r['segments']}"
         f" · average {r['total'] / max(r['segments'], 1):.1f}s per picture",
         f"- **Captions:** {r['captions']}",
         f"- **Render time:** {r['render_secs'] / 60:.1f} min", ""]
    if r["warnings"]:
        L += ["## ⚠️ Warnings", ""] + [f"- {w}" for w in r["warnings"]] + [""]
    if r["notes"]:
        L += ["## Notes", ""] + [f"- {n}" for n in r["notes"]] + [""]
    L += ["## Missing images", ""]
    if r["missing"]:
        L += ["These shots had no picture, so the previous picture was reused with a different move. "
              "Add the file to `images/` named with the shot number and re-run.", "",
              "| Shot | Time | What it needs | Shown instead |", "|---|---|---|---|"]
        L += [f"| {s['shot']} | {fmt(s['start'])} | {s['desc']} | {s.get('fallback', '-')} |" for s in r["missing"]]
    else:
        L.append("None. Every shot has a picture. ✅")
    L += ["", "## Pictures held too long", ""]
    if r["long_holds"]:
        L += [f"Held longer than {r['max_secs']}s. The editor added extra zooms/crops, but another picture "
              f"would keep it more lively (save it as e.g. `012-2.jpg`).", "",
              "| Shot | Time | Seconds | Picture |", "|---|---|---|---|"]
        L += [f"| {s['shot']} | {fmt(s['start'])} | {s['secs']:.0f} | {s['desc']} |" for s in r["long_holds"]]
    else:
        L.append("None. ✅")
    if r["clip_as_image"]:
        L += ["", "## Clip shots shown as a still", "",
              "These were marked `[CLIP]` but there's no video file in `clips/`, so the image was used.", ""]
        L += [f"- {s['shot']} ({fmt(s['start'])}): {s['desc']}" for s in r["clip_as_image"]]
    if r["small"]:
        L += ["", "## Small pictures (may look soft at 1080p)", ""] + [f"- {n} ({sz})" for n, sz in r["small"]]
    if r["portrait"]:
        L += ["", "## Tall pictures (shown on a blurred background)", "", ", ".join(r["portrait"])]
    if r["unused"]:
        L += ["", "## Files in images/ that weren't used", "",
              "Their names don't start with a shot number from the script:", ""] + [f"- {n}" for n in r["unused"]]
    L += ["", "## Timeline", "", "| Shot | Start | End | Picture |", "|---|---|---|---|"]
    for s in r["shots"]:
        pic = ", ".join(s.get("files") or []) or f"MISSING (showing {s.get('fallback', '-')})"
        L.append(f"| {s['shot']} | {fmt(s['start'])} | {fmt(s['end'])} | {pic} |")
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Auto-edit a PhillZeno video")
    ap.add_argument("project")
    ap.add_argument("--preview", action="store_true", help="fast low-resolution check")
    ap.add_argument("--fast", action="store_true", help="full size, faster encode (testing)")
    ap.add_argument("--burn", action="store_true", help="burn captions into the video")
    ap.add_argument("--seconds", type=float, help="only render the first N seconds")
    ap.add_argument("--whisper", action="store_true", help="always transcribe (even for AI narration)")
    args = ap.parse_args()

    t_start = time.time()
    proj = Path(args.project)
    if not (proj / "script.md").exists():
        raise EditorError(f"Can't find {proj / 'script.md'}. Check the folder name.")
    media.need_ffmpeg()
    cfg = load_config(proj)
    build, outdir = proj / "build", proj / "output"
    build.mkdir(exist_ok=True)
    outdir.mkdir(exist_ok=True)
    name = proj.name
    mode = "preview" if args.preview else ("fast" if args.fast else "final")
    report = {"name": name, "mode": mode, "warnings": [], "notes": [], "missing": [], "long_holds": [], "small": [],
              "portrait": [], "clip_as_image": [], "unused": [], "max_secs": cfg["images"]["max_seconds"]}

    print(f"PhillZeno editor: {name} ({mode})")
    _, paras = parse_script((proj / "script.md").read_text(encoding="utf-8"))
    paras = [p for p in paras if p["text"]]

    # 1. voice
    print("1/5 Cleaning up the voice...")
    src = media.find_voice(proj)
    voice, notes = media.prepare_voice(src, build, cfg)
    report["notes"] += notes
    vdur = media.duration(voice)
    report["voice"] = (", ".join(f.name for f in src["files"]) + f" ({src['kind']}, {fmt(vdur)}, "
                       f"loudness {cfg['audio']['loudness']} LUFS)")

    # 2. word timing
    print("2/5 Working out when each line is said...")
    swords = W.script_words(paras)
    if src["kind"] == "narration" and src.get("timing") and not args.whisper:
        W.from_narration_timing(swords, paras, src["timing"])
        report["timing"] = "from the AI narration's own timing file (exact per paragraph)"
    else:
        names = sorted({w for p in paras for w in re.findall(r"\b[A-Z][a-zA-Z'-]{2,}\b", p["text"])})
        transcript = W.transcribe(voice, cfg, build, prompt=", ".join(names))
        if not transcript:
            raise EditorError("Whisper heard no words in the voiceover. Is the file silent?")
        ratio = W.align(swords, transcript, vdur)
        report["timing"] = f"Whisper transcript lined up with script.md: {ratio:.0%} of script words matched"
        if ratio < 0.6:
            report["warnings"].append(
                f"Only {ratio:.0%} of the script matched what was said. If you went off-script a lot, "
                f"picture timing may drift. Make script.md match what you actually said and re-run.")
        (build / "aligned_words.json").write_text(json.dumps(swords), encoding="utf-8")
    total = vdur + cfg["audio"]["tail_seconds"]
    if not args.seconds:  # section start times, for chapters (tools/package.py)
        sections = []
        for pi, p in enumerate(paras):
            if not sections or sections[-1]["section"] != p["section"]:
                first = next((w["start"] for w in swords if w["para"] == pi), None)
                if first is not None:
                    sections.append({"section": p["section"], "start": 0.0 if not sections else round(first, 2)})
        (build / "section_times.json").write_text(json.dumps({"total": round(total, 2), "sections": sections},
                                                             indent=1), encoding="utf-8")
    if args.seconds:
        total = min(total, args.seconds)
        swords = [w for w in swords if w["start"] < total]
    report["total"] = total

    # 3. timeline
    print("3/5 Placing your images...")
    segs = build_timeline(proj, paras, swords, total, cfg, report)
    segs = [s for s in segs if s.start < total]
    report["segments"] = len(segs)
    if report["missing"]:
        print(f"    {len(report['missing'])} shots have no image yet (listed in the report).")

    # 4. audio mix + captions
    print("4/5 Mixing music and making captions...")
    music = media.find_music(ROOT, cfg)
    report["music"] = music.name if music else None
    mixed = build / "audio_mix.wav"
    media.mix(voice, music, mixed, total, cfg)
    srt = outdir / f"{name}.srt"
    n_caps = W.write_srt(swords, srt, cfg["captions"].get("max_chars", 42))
    report["captions"] = f"{n_caps} captions → {srt.name}"
    subs = None
    if args.burn or cfg["captions"].get("burn"):
        subs = build / "captions.ass"
        report["captions"] += " · burned into the video"

    # 5. render
    if args.preview:
        pc = cfg["preview"]
        w, h, fps, preset, crf = pc["width"], pc["height"], pc["fps"], "ultrafast", 28
        out = outdir / f"{name}_preview.mp4"
    else:
        vc = cfg["video"]
        w, h, fps = vc["width"], vc["height"], vc["fps"]
        preset = vc["preset_test"] if args.fast else vc["preset_final"]
        crf = vc["crf"]
        out = outdir / f"{name}.mp4"
    if subs:
        W.write_ass(swords, subs, cfg, w, h)
    print(f"5/5 Rendering {w}x{h} @ {fps}fps ({preset})...")
    t_render = time.time()
    render.encode(segs, mixed, out, total, cfg, w, h, fps, preset, crf, subs=subs, workdir=build, label=mode)
    report["render_secs"] = time.time() - t_render

    write_report(outdir / "report.md", report)
    print(f"\nDone in {(time.time() - t_start) / 60:.1f} min.")
    print(f"  Video:   {out}")
    print(f"  Report:  {outdir / 'report.md'}")
    if report["missing"]:
        print(f"  Heads up: {len(report['missing'])} shots are missing images (see report).")


if __name__ == "__main__":
    try:
        main()
    except EditorError as e:
        print("\n❌ " + str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopped.")
        sys.exit(1)
