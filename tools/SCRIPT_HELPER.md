# Script Helper (Format A: commentary videos)

You don't need to write code for this. It's a conversation with Claude plus one checker command.

## Step 1: Start a new project folder
Each video lives in `projects/<video-name>/` (for example `projects/avengers-doomsday/`).
*(A one-command project creator comes in Phase 6. For now, ask Claude to make the folder.)*

## Step 2: Ask Claude for the script
Open Claude Code in the `phillzeno` folder and paste this, filling in the topic:

> Write a PhillZeno Format A script about **<TOPIC>** into `projects/<video-name>/script.md`, following `tools/SCRIPT_HELPER.md`.
> First look up the latest facts on the web and give me 3–5 angle options. Wait for me to pick one before writing.

Claude follows the rules below every time.

## The rules Claude follows
1. **Research first.** Search the web for the current state of the topic (release dates, cast, trailers, comic issues). Write the facts and their sources into `projects/<video-name>/research.md`. Single-source or insider claims are labeled **RUMOR**.
2. **Offer 3–5 angles** and wait for a pick.
3. **Use the template** in `templates/script_template.md`, in this order:
   - **HOOK**: the first ~15 seconds (35–40 words). A specific, curiosity-driven question or claim. Never "Hey guys, welcome back."
   - **SETUP**: why it matters now, and what the video will answer.
   - **3–5 SEGMENTS**: each one ends with a reason to keep watching.
   - **PAYOFF**: answers the hook.
   - **OUTRO**: short, with **one** call to action.
4. **Length:** 1,400–1,500 spoken words, which is about 10 minutes.
5. **Visual cues:** one or more `[IMAGE: description]` lines under every paragraph. Aim for roughly one image per 4–8 seconds, which is about one per 12–20 words. Use `[CLIP: description]` where a video clip fits better.
6. **Voice:** read `templates/PHILL_VOICE.md` first (Phill's voice profile, built from his own videos). write it the way Phill talks. Casual, hyped, fan-to-fan, with short punchy sentences that are easy to read aloud. Use contractions, avoid tongue-twisters, and keep sentences under about 20 words.
7. **Fact check:** every factual claim goes in `## SOURCES` with a link. Rumors are labeled as rumors **in the script itself** too ("rumor has it…", "reportedly…").
8. **No copyrighted downloads.** Image cues describe what Phill should find. Claude never fetches the images.

## Step 3: Check it
```
python tools/script_check.py projects/<video-name>
```
This prints the word count, estimated runtime, hook length, any paragraphs missing an image, and banned openers. It also writes **`shotlist.md`**: your numbered list of images to collect.

## Step 4: Collect images, then record
- Run the **Image Finder**: `python tools/find_images.py projects/<video-name> --auto` (picks everything automatically, then you review), or leave off `--auto` to pick one at a time.
  A page opens in your browser. It searches each shot for you, and you **click the picture you like** to save it with the right number. It then jumps to the next shot. You can also copy any image and press Ctrl+V, or drag one in.
- Or do it by hand: save each image into `images/` named with its shot number (`001.jpg`, `002.png`, `003-doom-throne.jpg`). Anything after the number is ignored. `001-2.jpg` means a second image for shot 001.
- Record the voiceover by reading `script.md`, skipping the headings and the `[IMAGE]` lines. Save the recording in `voiceover/`.
