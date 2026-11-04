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
3. **Don't download copyrighted media on our own** (comic scans, movie clips, trailers, fan art). Web search is fine for *facts*, with sources cited. **Exception, owner-approved 2026-11-03:** stills for the shot list are fetched by `tools/find_images.py --auto` *on the owner's machine*, then the owner reviews every pick. Never fetch video clips or trailers. Never pick fan art on purpose.
4. **Never delete or overwrite originals.** `inbox/`, `voiceover/`, `images/`, `clips/` are read-only to tools. All output goes to `build/` and `output/`.
5. **Everything runs on the owner's computer.**
6. **Ask before installing anything big** (over ~1 GB, e.g. voice models). State the size and purpose.
7. Simple and working beats clever. A rough version that renders beats a perfect one that doesn't.
8. Commercial use matters: the channel is (or will be) monetized, so check model **licenses** allow commercial use.

## Workflow rules
- **GitHub (fixed 2026-11-04):** repo `phillipkachy/PhillZeno`. The Claude GitHub App is installed with access to all repos. `main` is the default branch. Claude works on its `claude/...` branch and pushes after every change. To update `main`, open a pull request the owner merges (no direct pushes to main without asking).
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

## Script format (parsed by tools)
- `## SECTION` headings (HOOK, SETUP, SEGMENT n: name, PAYOFF, OUTRO, SOURCES). Not spoken.
- Paragraph text, then one or more `[IMAGE: desc]` / `[CLIP: desc]` lines. Cues are numbered 001, 002… in order; the owner saves files as `images/001*.jpg`, `clips/014*.mp4`.
- `<!-- -->` comments and the SOURCES/NOTES/FACT CHECK sections are ignored.
- `tools/script_check.py` has `parse_script()`. Reuse it in the auto-editor.
- A shot can have several files: `001.jpg`, `001-2.jpg`… The auto-editor should cycle through all of them within that shot's time.

## Image sourcing (owner decision, 2026-11-02)
Collecting images by hand was the owner's biggest time sink, so they asked Claude to get them. Claude's cloud container can't reach image sites, and the files need to end up on the owner's PC anyway. Solution: `tools/find_images.py`, a local browser page. It runs free DuckDuckGo image search (the `ddgs` package) for each shot's `[IMAGE]` description, and the owner clicks to save.
- **`--auto` (owner asked for it 2026-11-03):** an automatic first pass. For each empty shot it scores the results (prefers ≥1280 px, roughly 16:9, higher rank; skips fan-art, stock and merch domains and title words like "fan art", "cosplay", "toy") and saves the best one that downloads and is ≥800 px wide. Then the page opens in review mode: yellow dot = auto pick, with Keep / Reject / click-to-swap. Reject or swap moves the auto file to `build/rejected_auto/`; tool-made files only, never the owner's own picks. Every pick's source URL is logged in `build/image_sources.json`, which is useful for credits and for the report.
- The real search can't be tested from the cloud container (image sites are blocked there). The logic was tested with mocked search results. Search terms edited in the page are saved to `build/image_queries.json`. Never overwrites: a second pick saves as `NNN-2.ext`. Advise: prefer official stills and real comic panels, avoid watermarked fan art.
- Pace assumption: 150 words/min (`--wpm` to override).
- Research goes in `projects/<slug>/research.md` with CONFIRMED / REPORTED / THEORY / RUMOR labels.

## Folder layout
```
phillzeno/
  CLAUDE.md, README.md, requirements.txt, setup.sh, setup.bat
  templates/             script template
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
| Check a script + build shot list | `python tools/script_check.py projects/<slug>` |
| Find & save images (browser page) | `python tools/find_images.py projects/<slug>` |
| Auto-pick all images, then review | `python tools/find_images.py projects/<slug> --auto` |
| Install voice-clone add-on (asks first, ~4–7 GB) | `setup_voice.bat` / `bash setup_voice.sh` |
| Narrate script in owner's cloned voice | `.venv-voice/bin/python tools/narrate.py projects/<slug> [--test] [--redo 3,12] [--engine turbo]` |
| Auto-edit: quick preview | `python tools/make_video.py projects/<slug> --preview` |
| Auto-edit: final 1080p | `python tools/make_video.py projects/<slug>` (`--fast`, `--burn`, `--seconds N`, `--whisper`) |
| Upload pack (titles, description+chapters, tags) | `python tools/package.py projects/<slug>` (needs `packaging.yaml`) |
| Thumbnail text on owner's image | `python tools/thumbnail.py projects/<slug> <image> "TEXT" [--side --color --size]` |
| *(more tools added as phases complete)* | |

## Status
- [x] Phase 0 — project skeleton, machine checker, setup scripts, venv + requirements, git. **Waiting on owner's machine report.**
- [x] Phase 1 — script helper built (`tools/SCRIPT_HELPER.md` rules, `templates/script_template.md`, `tools/script_check.py`). Doomsday research in `projects/avengers-doomsday/research.md`. Angle picked: #2 "The comic that explains Doomsday" (Hickman: New Avengers, Time Runs Out, Secret Wars 2015). Script drafted in `projects/avengers-doomsday/script.md` (1,404 words, ~9:22, 93 shots). **Script APPROVED by owner 2026-11-03.** The owner asked Claude to try the voiceover: an AI test read was made with Kokoro (Apache 2.0, ~340 MB, CPU, voice `am_michael`, speed 1.1) in `projects/avengers-doomsday/build/ai_test_voice/` (full read, 8:38, plus hook samples in 5 voices). The Kokoro install lives only in the cloud scratchpad, not in the project. It's a test/fallback, not a replacement for the owner's own voice unless they decide so.
- [~] Phase 2 — auto-editor BUILT and tested in the cloud container with stand-in media (Kokoro AI voice, numbered test frames, a test clip, a test tone). **Waiting for CHECKPOINT 2: owner's real test (1 min of voice + a few images) once they're back at their PC.** Design notes:
  - `tools/make_video.py` orchestrates; `tools/pzlib/` has `media.py` (ffmpeg, voice find/cleanup, two-pass loudnorm, music + sidechain ducking), `words.py` (faster-whisper transcription cached in build/, difflib alignment of script words to transcript, narration-timing fallback, SRT/ASS captions), `render.py` (PIL Ken Burns: crop-box per frame on a canvas (1+zoom)× frame size, blurred-bg for off-aspect images, clips decoded via ffmpeg pipe, optional crossfade, frames piped as raw RGB into one libx264 encode).
  - Voice source: `voiceover/*` (several files joined in name order), else `build/narration/narration.wav` with `timing.json` (no Whisper needed).
  - Timeline: each paragraph spans from its first word (minus 0.12 s) to the next paragraph's. Its cues split that time equally. Files per shot `NNN*.ext` split the shot's time. Holds over `max_seconds` get subdivided into extra moves/focus points and flagged. Missing shots reuse the previous image and are flagged.
  - Tested: preview of the full 8:39 in ~1 min. 60 s at 1080p `--fast` ~1.4 min (4-core container). Loudness -14.3 LUFS. Alignment exact on a mangled fake transcript (85% match). Clip, blurred-bg, burned captions and fade all checked visually.
  - NOT yet tested for real: the Whisper model itself (blocked in the container) and Windows paths.
- [x] Phase 3 — packaging. Claude writes `projects/<slug>/packaging.yaml` in-session (titles scored with the yt-package title linter: ≤60 chars, has a number/name, thumbnail text ≤3 words and doesn't repeat the title). `tools/package.py` assembles and validates: chapters from `build/section_times.json` (written by make_video on full renders), else estimated from the script. YouTube rules: 0:00 first, ≥3 chapters, ≥10 s each. Description ≤5000 chars, no angle brackets, hashtags ≤15, tags ≤500 chars. Source links are pulled from script.md. Output: `output/upload.md` + description/tags/pinned_comment txt. `tools/thumbnail.py`: owner's image → 1280x720 with outlined text (font from assets/fonts or a system bold font), never overwrites. Doomsday `packaging.yaml` is written (best pairing: "The 2015 Comic That Explains Avengers: Doomsday" + "GOD EMPEROR DOOM").
- [ ] Phase 4 — Shorts
- [ ] Phase 5 — comic audiobook pipeline
- [ ] Phase 6 — README guide + new_project.py

## Phill's on-camera voice
`templates/PHILL_VOICE.md` is a voice profile built from his own videos (Damian Wayne, Nightwing). Use it for every script and all packaging copy. Key points: fan-to-friend, honest about bias, numbered "reason number X" structure for opinion videos. His usual outro is "If you watched all the way through, I really appreciate it. Give it a like, subscribe…". Lane: DCU/MCU speculation plus evergreen debates. His past videos ran 4–11 min, and the channels he models run 12–20.

## Owner's machine
_Unknown yet. Paste output of `tools/check_machine.py` here._

## Owner's cloned narration voice (decided 2026-11-03)
The owner wants narration in a **clone of their own voice**.
- Engine: **Chatterbox** (`chatterbox-tts==0.1.7`, MIT). `standard` has `exaggeration`/`cfg_weight` emotion control; `turbo` is faster but ignores them. Outputs carry Resemble's inaudible Perth AI watermark. Keep it.
- Lives in a **separate venv `.venv-voice`** (pins torch 2.6, transformers 5.2) so it can't break the main tools. Installed by `setup_voice.bat/.sh`, which states the size and asks y/N. It picks CUDA (cu124) or CPU torch wheels.
- Model weights come from Hugging Face on first run (~3 GB standard, ~2 GB turbo). HF is **blocked in the cloud container**, so real generation has only ever run on the owner's PC. The pipeline was tested with `PHILLZENO_FAKE_TTS=1` (beeps).
- Owner's sample: `voices/phill/sample.*` (original, never modified). Cleaned copy: `voices/phill/reference_sample.wav`. Chatterbox uses only the **first ~10 s**, so the sample's energy is the voice's energy.
- Settings: `voices/phill/profile.yaml` (per-section overrides, speed, pauses). Pronunciation respellings: `voices/pronunciations.yaml` (spoken audio only).
- Output: `build/narration/narration.wav` (+ mp3), `timing.json` (exact paragraph start/end; the auto-editor can use this instead of Whisper alignment), `paragraphs.md` (numbers for `--redo`). Chunks cached by hash in `build/narration/chunks/`, so it resumes after a crash, and `--redo N` changes the seed for a new take.
- The auto-editor should take `voiceover/*` if present, else `build/narration/narration.wav`.
- YouTube: tick "altered or synthetic content" when uploading AI-voiced videos, to be safe.

## Voice model shortlist (preliminary; full research in Phase 5)
Licenses must allow commercial use (monetized channel). Verify current status before recommending.
- **Chatterbox** (Resemble AI) — MIT. Voice cloning from a short sample + an "exaggeration" knob for emotion. Front-runner.
- **Kokoro** — Apache 2.0, tiny and fast on CPU, but preset voices and limited emotion. Fallback only.
- **Coqui XTTS-v2** — good cloning, but Coqui Public Model License is **non-commercial**. Likely ruled out.
- **F5-TTS** — code MIT but released weights are **CC-BY-NC**. Likely ruled out.
- **StyleTTS2** — MIT, older, harder to drive emotion per line.
