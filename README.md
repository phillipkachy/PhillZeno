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

_(Coming next: one-command auto-editor, packaging, Shorts.)_
