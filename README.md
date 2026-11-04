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

### 1. Write the script
Follow **`tools/SCRIPT_HELPER.md`**. In short, ask Claude for a script on your topic, pick an angle, then check it:
```
python tools/script_check.py projects/<video-name>
```
That shows the word count and runtime, and writes **`shotlist.md`**, the numbered list of images you need to collect.

### 2. Collect the images
**Fastest: let it pick everything, then review.**
```
python tools/find_images.py projects/<video-name> --auto
```
It goes through every empty shot, picks the best big, wide picture it can find and saves it. That takes a few seconds per shot, so leave it running. Then the page opens in **review mode**. Each auto pick has a yellow dot:
- Looks good? Click **✓ Keep**.
- Wrong picture? **Click a better one** in the grid to swap it, or press **✗ Reject**.
- Shots it couldn't fill are listed in the terminal. Do those by hand on the same page.

**By hand, one at a time:**
```
python tools/find_images.py projects/<video-name>
```
A page opens in your browser with every shot from your shot list. It searches each one for you, and you **click the picture you want**. It's saved into `images/` with the right number, then the next shot loads. You can also copy any image from anywhere and press **Ctrl+V** (Mac: **Cmd+V**), or drag an image onto the page. The green bar shows how many you've done. Press Ctrl+C in the terminal when you're finished.

Tips: pick big images (the size badge turns green at 1280 wide and up). Prefer official movie stills and real comic panels. Skip watermarked fan art, since artists can file claims.

### 3. The voiceover: record it, or use your voice clone
**Option A: record it yourself.** Read `script.md` (skip the headings and `[IMAGE]` lines) and save the file in `voiceover/`.

**Option B: your AI voice clone.** Set it up once, and every script after that is narrated in your voice automatically.
1. Install the voice add-on (big: it asks before installing and shows the size):
   - Windows: double-click `setup_voice.bat`
   - Mac: `bash setup_voice.sh`
2. Record a 15–20 second sample in your hyped YouTube voice. Follow `voices/phill/README.md` and save it as `voices/phill/sample.m4a`.
3. Test it on the first minute:
   - Windows: `.venv-voice\Scripts\python tools\narrate.py projects\<video-name> --test`
   - Mac: `.venv-voice/bin/python tools/narrate.py projects/<video-name> --test`
4. Listen to `build/narration/narration.mp3`. Happy? Run the same command **without** `--test` for the whole script.
5. A line sounds off? Find its number in `build/narration/paragraphs.md`, then add `--redo 12` (or `--redo 3,12,15`) to the command. Only those lines are redone.
6. A word said wrong? Add it to `voices/pronunciations.yaml` (for example `Doomstadt: Doom-shtat`), then redo that paragraph.
7. Too calm or too much? Change `exaggeration` in `voices/phill/profile.yaml`: 0.5 is normal, 0.7 is hyped.

Without a graphics card this is slow, roughly 30–90 minutes for a 10-minute video. Start it and walk away. If it stops, run it again and it continues where it left off.

### 4. Make the video
Check the timing first with a quick low-quality **preview** (about 1–3 minutes):
```
python tools/make_video.py projects/<video-name> --preview
```
Open `output/<video-name>_preview.mp4` and `output/report.md`. The report lists missing pictures, pictures that stay on screen too long, and small or blurry ones. Fix what you want, then make the **final** 1080p video:
```
python tools/make_video.py projects/<video-name>
```
That takes a while on a normal computer (roughly 15–40 minutes for 10 minutes of video), so let it run. You get:
- `output/<video-name>.mp4`: upload this
- `output/<video-name>.srt`: upload as captions in YouTube Studio (Subtitles → Upload file)
- `output/report.md`: what to fix next time

Handy extras:
- `--seconds 60`: only the first minute (quick test)
- `--burn`: captions burned into the picture
- `--fast`: full size, quicker but a bigger file
- **Background music:** drop a free/royalty-free track in `assets/music/`. It's added quietly under your voice and dips while you talk.
- **Video clips:** put them in `clips/` named with the shot number (`021.mp4`).
- **Change the look** (zoom amount, picture timing, music volume, caption style) in `config.yaml`. Each setting is explained there.

### 5. Package it (titles, thumbnail, description, tags)
Ask Claude to write `packaging.yaml` for the video. It includes 5 titles, 3 thumbnail ideas, chapter names, the description, tags and a pinned comment. Then run:
```
python tools/package.py projects/<video-name>
```
Open **`output/upload.md`**. It has every YouTube Studio field in order, ready to copy, with chapter times taken from the real video. (Run it after the final render; before that, the times are estimates.)

**Thumbnail text (optional):** make your thumbnail picture, then add the text in the same bold style every time:
```
python tools/thumbnail.py projects/<video-name> my_picture.jpg "GOD EMPEROR DOOM"
```
Options: `--side left/right/top/bottom`, `--color yellow/white/red`, `--size 1.2`. Put your channel font (.ttf) in `assets/fonts/` and it's used automatically.

### 6. Shorts
After the long video is made (a preview is enough), cut Shorts from it:
```
python tools/make_shorts.py projects/<video-name>
```
You get 3–5 vertical videos in `output/shorts/` (1080x1920). Each has big captions, a headline pinned at the top, and wide pictures that slowly pan across the tall frame. `output/shorts/shorts.md` has the title and description for each.

Which moments become Shorts comes from **`shorts.yaml`**. Ask Claude to write it (it picks moments that make sense without the full video), or let the tool pick automatically. `--pick` only shows the choices without rendering, and `--preview` makes quick small versions. Change caption size and position in the `shorts:` part of `config.yaml`.

_(Coming next: comic audiobook videos with AI character voices.)_
