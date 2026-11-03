"""
Packaging: everything you paste into YouTube Studio, checked against YouTube's rules.

Run:   python tools/package.py projects/<video-folder>

Reads   packaging.yaml   (titles, thumbnail ideas, description text, tags... Claude writes this with you)
        build/section_times.json  (real chapter times, written by make_video.py)
Writes  output/upload.md        <- open this: every field in YouTube Studio order, ready to copy
        output/description.txt  output/tags.txt  output/pinned_comment.txt

Run it again any time after the final render: the chapter times update to the real video.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from script_check import parse_script, WORDS_PER_MINUTE  # noqa: E402

DESC_LIMIT = 5000
TAGS_LIMIT = 500
STOP = {"the", "a", "an", "of", "to", "in", "is", "and", "for", "this", "that", "it", "on", "why", "how"}


def fmt(t):
    t = int(t)
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def section_times(proj):
    """Real section start times if the video has been made, otherwise an estimate from the script."""
    st = proj / "build" / "section_times.json"
    if st.exists():
        d = json.loads(st.read_text(encoding="utf-8"))
        return d["sections"], d["total"], True
    _, paras = parse_script((proj / "script.md").read_text(encoding="utf-8"))
    out, t = [], 0.0
    for p in paras:
        if p["text"] and (not out or out[-1]["section"] != p["section"]):
            out.append({"section": p["section"], "start": round(t, 1)})
        t += p["words"] / WORDS_PER_MINUTE * 60
    return out, t, False


def build_chapters(sections, total, names, problems):
    """YouTube rules: first at 0:00, at least 3, each at least 10 s, in order."""
    chapters = []
    for s in sections:
        key = next((k for k in names if s["section"].upper().startswith(str(k).upper())), None)
        if key is None:
            continue  # sections without a chapter name roll into the previous chapter
        if chapters and s["start"] - chapters[-1]["start"] < 10:
            chapters[-1]["title"] = names[key]  # too short: merge
            continue
        chapters.append({"start": s["start"], "title": names[key]})
    if chapters:
        chapters[0]["start"] = 0
    if chapters and total - chapters[-1]["start"] < 10:
        chapters.pop()
    if len(chapters) < 3:
        problems.append("Fewer than 3 chapters, so YouTube won't show them. Add chapter names in packaging.yaml.")
    return chapters


def words(s):
    return {w for w in re.findall(r"[a-z0-9']+", s.lower()) if w not in STOP}


def main():
    ap = argparse.ArgumentParser(description="Build the YouTube upload pack")
    ap.add_argument("project")
    args = ap.parse_args()
    proj = Path(args.project)
    pk_file = proj / "packaging.yaml"
    if not pk_file.exists():
        sys.exit(f"No {pk_file} yet. Ask Claude: \"write packaging.yaml for {proj}\".")
    try:
        pk = yaml.safe_load(pk_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        sys.exit(f"{pk_file} has a typo (check quotes, colons and spaces):\n{e}")
    out = proj / "output"
    out.mkdir(exist_ok=True)
    problems, notes = [], []

    # ---- titles + thumbnails
    titles = pk.get("titles", [])
    best = next((t for t in titles if t.get("best")), titles[0] if titles else None)
    thumbs = pk.get("thumbnails", [])
    for t in titles:
        n = len(t["text"])
        if n > 60:
            problems.append(f"Title is {n} characters (over 60, gets cut off): {t['text']}")
    for th in thumbs:
        if len(th["text"].split()) > 3:
            problems.append(f"Thumbnail text over 3 words: {th['text']}")
        pair = next((t for t in titles if t["text"] == th.get("pairs_with")), best)
        if pair:
            overlap = words(th["text"]) & words(pair["text"])
            if overlap:
                notes.append(f"Thumbnail \"{th['text']}\" repeats \"{', '.join(sorted(overlap))}\" from its title.")

    # ---- chapters
    sections, total, real = section_times(proj)
    chapters = build_chapters(sections, total, pk.get("chapters", {}), problems)
    if not real:
        notes.append("Chapter times are ESTIMATES from the script. Re-run this after the final render "
                     "(make_video.py) to get the real times.")

    # ---- description
    d = pk.get("description", {})
    tags = [t.strip() for t in pk.get("tags", []) if t.strip()]
    hashtags = ["#" + h.lstrip("#").replace(" ", "") for h in pk.get("hashtags", [])]
    parts = [d.get("hook", "").strip(), "", d.get("summary", "").strip(), ""]
    if chapters:
        parts += ["Chapters:"] + [f"{fmt(c['start'])} {c['title']}" for c in chapters] + [""]
    if d.get("extra"):
        parts += [d["extra"].strip(), ""]
    if pk.get("include_sources", True):
        srcs = re.findall(r"\]\((https?://\S+?)\)(?=[\s,;]|$)", (proj / "script.md").read_text(encoding="utf-8"),
                          flags=re.M)
        seen = []
        for u in srcs:
            if u not in seen:
                seen.append(u)
        if seen:
            parts += ["Sources:"] + seen + [""]
    if hashtags:
        parts.append(" ".join(hashtags))
    desc = "\n".join(parts).strip() + "\n"
    desc = re.sub(r"[<>]", "", desc)  # YouTube rejects angle brackets
    if len(desc) > DESC_LIMIT:
        problems.append(f"Description is {len(desc)} characters (YouTube max {DESC_LIMIT}). "
                        f"Set include_sources: false or shorten the summary.")
    if len(hashtags) > 15:
        problems.append("More than 15 hashtags: YouTube then ignores ALL of them. Keep 3-5.")
    tags_str = ", ".join(tags)
    if len(tags_str) > TAGS_LIMIT:
        problems.append(f"Tags are {len(tags_str)} characters (YouTube max {TAGS_LIMIT}). Remove a few.")
    if not 10 <= len(tags) <= 15:
        notes.append(f"{len(tags)} tags (aim for 10-15).")

    (out / "description.txt").write_text(desc, encoding="utf-8")
    (out / "tags.txt").write_text(tags_str + "\n", encoding="utf-8")
    (out / "pinned_comment.txt").write_text(pk.get("pinned_comment", "").strip() + "\n", encoding="utf-8")

    # ---- upload.md
    L = [f"# Upload pack: {proj.name}", ""]
    if problems:
        L += ["## ❌ Fix before uploading", ""] + [f"- {p}" for p in problems] + [""]
    if notes:
        L += ["## Notes", ""] + [f"- {n}" for n in notes] + [""]
    L += ["## 1. Title (pick one)", ""]
    for i, t in enumerate(titles, 1):
        star = " ⭐ **best with the thumbnail**" if t is best else ""
        L.append(f"{i}. `{t['text']}` ({len(t['text'])} chars){star}")
        if t.get("why"):
            L.append(f"   - {t['why']}")
    L += ["", "## 2. Thumbnail (you make it; `tools/thumbnail.py` can add the text)", ""]
    for i, th in enumerate(thumbs, 1):
        L += [f"**Concept {i}: \"{th['text']}\"**" + (f" (pairs with: *{th['pairs_with']}*)" if th.get("pairs_with") else ""),
              f"- Image: {th.get('image', '')}"]
        if th.get("notes"):
            L.append(f"- Tips: {th['notes']}")
        L.append("")
    L += ["## 3. Description (also in description.txt)", "", "```", desc.rstrip(), "```", "",
          "## 4. Tags (also in tags.txt)", "", "```", tags_str, "```", "",
          "## 5. Pinned comment (post it, then pin it)", "", "```", pk.get("pinned_comment", "").strip(), "```", "",
          "## 6. Upload checklist", "",
          "- [ ] Video: `output/" + proj.name + ".mp4`",
          "- [ ] Thumbnail: 1280x720 JPG/PNG under 2 MB",
          "- [ ] Captions: Subtitles → Add language → Upload file → `output/" + proj.name + ".srt` (with timing)",
          "- [ ] Chapters show on the progress bar after publishing (they come from the description)",
          "- [ ] Altered or synthetic content: tick **Yes** if the narration is your AI voice clone",
          "- [ ] Audience: Not made for kids", ""]
    (out / "upload.md").write_text("\n".join(L), encoding="utf-8")

    print(f"Upload pack written: {out / 'upload.md'}")
    print(f"  {len(titles)} titles, {len(thumbs)} thumbnail ideas, {len(chapters)} chapters "
          f"({'real times' if real else 'ESTIMATED times'}), {len(tags)} tags, description {len(desc)} chars")
    for p in problems:
        print("  ❌ " + p)
    for n in notes:
        print("  • " + n)


if __name__ == "__main__":
    main()
