# PhillZeno — Project Memory

Read this first every session. It's the full brief plus where we are. Keep it updated after every phase.

## Who the owner is
- Runs the superhero YouTube channel **PhillZeno** (youtube.com/@PhillZeno). Restarting it and wants to publish ASAP.
- **Can't edit video.** Records own voiceovers, makes own thumbnails, supplies own images/clips. Everything from "raw voiceover + images" to "finished MP4" is automated by us.
- **Not a programmer.** Explain in plain English, give exact commands, and make every tool one simple command.
- Inspiration: Comic Lads (@comiclads) and Kaythegod talks (@Kaythegodtalks). Match their energy and pacing, not their branding.

## Hard rules (never break these)
1. **Budget is $0.** Free, open-source, local tools only. No paid APIs, subscriptions or credits (including ElevenLabs, even though a connector exists in this environment). If something can't be done free, say so plainly and give the cheapest option.
2. **Use the owner's images only.** Never generate placeholder graphics, title cards or AI art. Missing image means flag it in the report.
3. **Never download copyrighted media** (comic scans, movie clips, trailers, fan art). The owner supplies all media. Web search is fine for *facts*, with sources cited.
4. **Never delete or overwrite originals.** `inbox/`, `voiceover/`, `images/`, `clips/` are read-only to tools. All output goes to `build/` and `output/`.
5. **Everything runs on the owner's computer.**
6. **Ask before installing anything big** (over ~1 GB, e.g. voice models). State the size and purpose.
7. Simple and working beats clever. A rough version that renders beats a perfect one that doesn't.
8. Commercial use matters: the channel is (or will be) monetized, so check model **licenses** allow commercial use.

## Workflow rules
- Go phase by phase; stop at every CHECKPOINT and wait for the go-ahead.
- After each phase: 3–5 line summary (what works, exact command, what the owner does next).
- Fix failures ourselves first; only ask the owner for decisions or files.
- Note: Claude Code sessions may run in a **cloud container**, not the owner's machine. Hardware results from the container don't describe the owner's PC. The owner runs `tools/check_machine.py` locally and pastes the output.

## The two formats

### Format A — Commentary / breakdown (priority 1)
- ~10 min, owner's voiceover over owner's images/clips. ~1,400–1,500 words.
- First video: *Avengers: Doomsday* hype video.
- Script rules: 15-second curiosity hook (no "hey guys welcome back"); hook → setup → 3–5 segments each ending with a reason to keep watching → payoff → short outro with one CTA. `[IMAGE: description]` under each paragraph (becomes `shotlist.md`). Fact-check claims with sources at bottom; flag rumors. Casual, hyped, fan-to-fan, short sentences.
- Auto-editor (`tools/make_video.py`): audio cleanup (denoise, -14 LUFS, gentle compression, trim silence) → local Whisper word timestamps → align to script paragraphs → Ken Burns on stills, alternating, change every 4–8 s, 16:9 fill (blurred bg for portrait) → clips where assigned → SRT (+ optional burned captions, off for long-form, on for Shorts) → music with sidechain ducking → 1080p30 H.264 → `output/report.md`. Preview mode (fast, low-res). All knobs in `config.yaml`.

### Format B — Comic "audiobook" (priority 2, Comicstorian-style)
- Owner narrates; **AI voices every character's dialogue.**
- **Emotional voices are a hard requirement.** Excited Gambit sounds excited, angry Rogue sounds angry. Monotone = fail, must be flagged, not shipped. Each character keeps one consistent voice.
- Character profiles in `voices/` (Gambit: Cajun, smooth, playful. Rogue: Southern, tough but warm).
- Script format (`comic_script.md`):
  ```
  NARRATOR: The rain hadn't stopped in three days.
  GAMBIT [excited, teasing]: "You t'ink you can just walk away, chère?"
  ROGUE [angry, hurt]: "Watch me, Remy."
  [PANEL: page03_panel2.jpg]
  ```
- 2–3 takes per line, keep most expressive, review/re-roll step. Panels get Ken Burns timed to lines.
- First test: 1–2 min Gambit & Rogue scene.

## Folder layout
```
phillzeno/
  CLAUDE.md, README.md, requirements.txt, setup.sh, setup.bat
  inbox/                 raw drops (read-only)
  projects/<slug>/
    script.md
    voiceover/ images/ clips/   owner's originals (read-only)
    dialogue/            generated character lines (Format B)
    build/               intermediate files
    output/              final MP4, SRT, thumbnail, metadata, report.md
  tools/                 our scripts
  assets/music, sfx, fonts, branding
  voices/                character voice profiles
```
Big media is git-ignored (see `.gitignore`); code, configs, scripts and reports are tracked.

## How to run things
| What | Command (activate venv first: `source .venv/bin/activate` / `.venv\Scripts\activate`) |
|---|---|
| One-time setup | `bash setup.sh` (Mac/Linux) or `setup.bat` (Windows) |
| Check machine | `python tools/check_machine.py` |
| *(more tools added as phases complete)* | |

## Status
- [x] Phase 0 — project skeleton, machine checker, setup scripts, venv + requirements, git. **Waiting on owner's machine report.**
- [ ] Phase 1 — script helper + Doomsday script
- [ ] Phase 2 — auto-editor
- [ ] Phase 3 — packaging
- [ ] Phase 4 — Shorts
- [ ] Phase 5 — comic audiobook pipeline
- [ ] Phase 6 — README guide + new_project.py

## Owner's machine
_Unknown yet. Paste output of `tools/check_machine.py` here._

## Voice model shortlist (preliminary; full research in Phase 5)
Licenses must allow commercial use (monetized channel). Verify current status before recommending.
- **Chatterbox** (Resemble AI) — MIT. Voice cloning from a short sample + an "exaggeration" knob for emotion. Front-runner.
- **Kokoro** — Apache 2.0, tiny and fast on CPU, but preset voices and limited emotion. Fallback only.
- **Coqui XTTS-v2** — good cloning, but Coqui Public Model License is **non-commercial**. Likely ruled out.
- **F5-TTS** — code MIT but released weights are **CC-BY-NC**. Likely ruled out.
- **StyleTTS2** — MIT, older, harder to drive emotion per line.
