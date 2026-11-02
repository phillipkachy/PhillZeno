# PhillZeno — How I Make a Video

Plain-English guide. This fills in as each tool gets built.

## One-time setup

1. Make sure you have **Python 3.10+**, **ffmpeg**, and **git**. Not sure? Run the checker (step 2). It tells you exactly what's missing and the command to install it.
2. Open a terminal in the `phillzeno` folder and run:
   - **Mac / Linux:** `bash setup.sh`
   - **Windows:** double-click `setup.bat` (or type `setup.bat` in PowerShell)

   This checks your computer and installs the free Python packages into a private folder (`.venv`). It doesn't touch the rest of your system.
3. Every time you come back to work, "activate" that folder first:
   - **Mac / Linux:** `source .venv/bin/activate`
   - **Windows:** `.venv\Scripts\activate`

## Where things go

| Folder | What goes in it |
|---|---|
| `inbox/` | Dump anything raw here. |
| `projects/<video-name>/voiceover/` | Your recorded voiceover. |
| `projects/<video-name>/images/` | Your images, named by segment (a `shotlist.md` will tell you what's needed). |
| `projects/<video-name>/clips/` | Optional video clips. |
| `projects/<video-name>/output/` | Finished video, captions, report. You only ever *take* from here. |
| `assets/music/` | Free/royalty-free music. |
| `assets/fonts/`, `assets/branding/` | Your fonts, logo, intro/outro. |

**Your originals are never edited or deleted.** The tools only write into `build/` and `output/`.

**Back up your media.** Videos, audio and images aren't saved in git (too big). Keep a copy on an external drive or a cloud folder.

## Making a video
_(Coming in later phases: script helper, one-command auto-editor, packaging, Shorts.)_
