"""
Check a Format A script and build its shot list.

Run:   python tools/script_check.py projects/<video-folder>

Reads   projects/<video-folder>/script.md
Writes  projects/<video-folder>/shotlist.md   (your numbered image list)

Nothing else is touched. The parse_script() function is also used by the auto-editor later.
"""

import argparse
import re
import sys
from pathlib import Path

WORDS_PER_MINUTE = 150      # natural, energetic narration pace
HOOK_SECONDS_TARGET = 15
TARGET_WORDS = (1400, 1500)
MAX_WORDS_PER_IMAGE = 22    # about 8-9 seconds at 150 wpm
BANNED_OPENERS = ["hey guys", "welcome back", "what's up guys", "whats up guys", "hello everyone"]
IGNORED_SECTIONS = {"SOURCES", "FACT CHECK", "NOTES"}

CUE_RE = re.compile(r"^\[(IMAGE|CLIP)\s*:\s*(.+?)\]\s*$", re.IGNORECASE)


def parse_script(text):
    """Turn script.md into a list of paragraphs.

    Each paragraph: {section, text, words, cues: [{kind, desc, shot}]}
    Shots are numbered 001, 002... across the whole script in order.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)  # drop notes
    title = None
    section = None
    paragraphs = []
    current = None
    shot_no = 0

    def close():
        nonlocal current
        if current and (current["text"] or current["cues"]):
            current["text"] = " ".join(current["text"]).strip()
            current["words"] = len(re.findall(r"[A-Za-z0-9'’]+", current["text"]))
            paragraphs.append(current)
        current = None

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].replace("TITLE:", "").strip()
            continue
        if line.startswith("## "):
            close()
            section = line[3:].strip()
            continue
        if section and section.upper().split(":")[0].strip() in IGNORED_SECTIONS:
            continue
        cue = CUE_RE.match(line)
        if cue:
            if current is None:  # cue with no text above it: attach to previous paragraph
                if paragraphs:
                    current = paragraphs.pop()
                    current["text"] = [current["text"]]
                else:
                    current = {"section": section, "text": [], "cues": []}
            shot_no += 1
            current["cues"].append({"kind": cue.group(1).upper(), "desc": cue.group(2).strip(),
                                    "shot": f"{shot_no:03d}"})
            continue
        if not line:
            # blank line ends a paragraph only once it has its cues
            if current and current["cues"]:
                close()
            continue
        if current and current["cues"]:
            close()  # new text after cues starts a new paragraph
        if current is None:
            current = {"section": section, "text": [], "cues": []}
        current["text"].append(line)
    close()
    return title, paragraphs


def fmt_time(seconds):
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def main():
    ap = argparse.ArgumentParser(description="Check script.md and write shotlist.md")
    ap.add_argument("project", help="project folder, e.g. projects/avengers-doomsday")
    ap.add_argument("--wpm", type=int, default=WORDS_PER_MINUTE, help="your speaking pace")
    args = ap.parse_args()

    proj = Path(args.project)
    script = proj / "script.md"
    if not script.exists():
        sys.exit(f"Can't find {script}. Check the folder name.")

    title, paras = parse_script(script.read_text(encoding="utf-8"))
    wpm = args.wpm
    total_words = sum(p["words"] for p in paras)
    runtime = total_words / wpm * 60

    problems, warnings = [], []

    # Hook checks
    hook = [p for p in paras if (p["section"] or "").upper().startswith("HOOK")]
    hook_words = sum(p["words"] for p in hook)
    hook_secs = hook_words / wpm * 60
    if not hook:
        problems.append("No '## HOOK' section.")
    else:
        if hook_secs > HOOK_SECONDS_TARGET + 5:
            warnings.append(f"Hook is ~{hook_secs:.0f}s ({hook_words} words). Aim for ~15s (35-40 words).")
        first = hook[0]["text"].lower()
        for b in BANNED_OPENERS:
            if b in first:
                problems.append(f"Hook uses a banned opener: '{b}'.")

    # Structure
    sections = [p["section"] or "" for p in paras]
    seg_count = len({s for s in sections if s.upper().startswith("SEGMENT")})
    if not 3 <= seg_count <= 5:
        warnings.append(f"{seg_count} segments found. The format calls for 3-5.")
    for need in ("SETUP", "PAYOFF", "OUTRO"):
        if not any(s.upper().startswith(need) for s in sections):
            warnings.append(f"No '## {need}' section.")

    # Length
    if not TARGET_WORDS[0] <= total_words <= TARGET_WORDS[1]:
        warnings.append(f"{total_words} words. Target is {TARGET_WORDS[0]}-{TARGET_WORDS[1]} (~10 min).")

    # Images per paragraph
    for i, p in enumerate(paras, 1):
        snippet = p["text"][:50] + ("..." if len(p["text"]) > 50 else "")
        if p["words"] and not p["cues"]:
            problems.append(f"Paragraph {i} has no [IMAGE] cue: \"{snippet}\"")
        elif p["cues"] and p["words"] / len(p["cues"]) > MAX_WORDS_PER_IMAGE:
            secs = p["words"] / len(p["cues"]) / wpm * 60
            warnings.append(f"Paragraph {i} holds each image ~{secs:.0f}s. Consider adding an [IMAGE]: \"{snippet}\"")

    long_sentences = []
    for p in paras:
        for s in re.split(r"(?<=[.!?])\s+", p["text"]):
            if len(s.split()) > 25:
                long_sentences.append(s[:70] + "...")
    if long_sentences:
        warnings.append(f"{len(long_sentences)} sentence(s) over 25 words (hard to read aloud), e.g. \"{long_sentences[0]}\"")

    # ---- Print report ----
    shots = [c for p in paras for c in p["cues"]]
    print("=" * 60)
    print(f" Script check: {title or script}")
    print("=" * 60)
    print(f"Spoken words     : {total_words}")
    print(f"Est. runtime     : {fmt_time(runtime)}  (at {wpm} words/min)")
    print(f"Hook             : {hook_words} words, ~{hook_secs:.0f}s")
    print(f"Segments         : {seg_count}")
    print(f"Images / clips   : {len(shots)}  (one every ~{runtime / max(len(shots), 1):.1f}s)")
    print()
    if problems:
        print("MUST FIX:")
        for x in problems:
            print("  - " + x)
    if warnings:
        print("WORTH A LOOK:")
        for x in warnings:
            print("  - " + x)
    if not problems and not warnings:
        print("All checks passed.")

    # ---- Shot list ----
    out = [f"# Shot list: {title or proj.name}", "",
           "Save each image in `images/` starting with its number, e.g. `001.jpg` or `001-doom.png`.",
           "Clips go in `clips/` the same way, e.g. `014.mp4`.", "",
           "| # | Type | Starts around | What to find | Have it? |",
           "|---|---|---|---|---|"]
    elapsed = 0.0
    images_dir, clips_dir = proj / "images", proj / "clips"
    for p in paras:
        n = max(len(p["cues"]), 1)
        for k, c in enumerate(p["cues"]):
            t = elapsed + (p["words"] / wpm * 60) * k / n
            folder = clips_dir if c["kind"] == "CLIP" else images_dir
            have = "yes" if folder.exists() and any(folder.glob(c["shot"] + "*")) else ""
            desc = c["desc"].replace("|", "/")
            out.append(f"| {c['shot']} | {c['kind'].lower()} | {fmt_time(t)} | {desc} | {have} |")
        elapsed += p["words"] / wpm * 60
    (proj / "shotlist.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print()
    print(f"Shot list written: {proj / 'shotlist.md'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
