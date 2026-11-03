"""
Add bold, outlined thumbnail text to YOUR image, the same look every time.

Run:
  python tools/thumbnail.py projects/avengers-doomsday my_doom_image.jpg "GOD EMPEROR DOOM"

Options:
  --side left|right|top|bottom   where the text goes (default: right)
  --color yellow|white|red|green or a hex code like FFD400   (default: yellow)
  --size 1.0                     make the text bigger (1.2) or smaller (0.8)

Font: the first .ttf/.otf in assets/fonts/ (put your channel font there), otherwise a bold system font.
Output: projects/<name>/output/thumbnail.jpg (1280x720, under 2 MB). Your image is never changed.
Saves a numbered copy if a thumbnail already exists, so you can compare versions.
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
W, H = 1280, 720
COLORS = {"yellow": "#FFD400", "white": "#FFFFFF", "red": "#FF2A2A", "green": "#39FF14", "orange": "#FF8A00"}
FALLBACK_FONTS = [
    "C:/Windows/Fonts/ariblk.ttf", "C:/Windows/Fonts/impact.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf", "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/Library/Fonts/Arial Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def find_font():
    own = sorted(p for p in (ROOT / "assets" / "fonts").glob("*") if p.suffix.lower() in (".ttf", ".otf"))
    if own:
        return str(own[0])
    for f in FALLBACK_FONTS:
        if Path(f).exists():
            return f
    sys.exit("No bold font found. Put a .ttf font file in assets/fonts/ (free ones: Google Fonts 'Anton' or 'Bebas Neue').")


def main():
    ap = argparse.ArgumentParser(description="Add thumbnail text to your image")
    ap.add_argument("project")
    ap.add_argument("image")
    ap.add_argument("text")
    ap.add_argument("--side", default="right", choices=["left", "right", "top", "bottom"])
    ap.add_argument("--color", default="yellow")
    ap.add_argument("--size", type=float, default=1.0)
    a = ap.parse_args()

    words = a.text.upper().split()
    if len(words) > 3:
        print("Heads up: more than 3 words is hard to read at phone size.")
    img_path = Path(a.image)
    if not img_path.exists():
        img_path = Path(a.project) / "images" / a.image
    if not img_path.exists():
        sys.exit(f"Can't find the image {a.image}.")
    im = ImageOps.fit(ImageOps.exif_transpose(Image.open(img_path)).convert("RGB"), (W, H), Image.LANCZOS)
    color = COLORS.get(a.color.lower(), "#" + a.color.lstrip("#"))

    # one word per line for left/right, all on one line for top/bottom
    lines = words if a.side in ("left", "right") else [" ".join(words)]
    box_w = W * (0.46 if a.side in ("left", "right") else 0.92)
    box_h = H * (0.86 if a.side in ("left", "right") else 0.34)
    font_path = find_font()
    size = 400
    while size > 20:
        font = ImageFont.truetype(font_path, int(size * a.size))
        d = ImageDraw.Draw(im)
        boxes = [d.textbbox((0, 0), ln, font=font, stroke_width=int(size * a.size * 0.09)) for ln in lines]
        tw = max(b[2] - b[0] for b in boxes)
        th = sum(b[3] - b[1] for b in boxes) + (len(lines) - 1) * size * 0.08
        if tw <= box_w and th <= box_h:
            break
        size -= 6
    stroke = int(size * a.size * 0.09)

    # darken behind the text a little so it pops on any picture
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    if a.side == "right":
        sd.rectangle([W * 0.5, 0, W, H], fill=110)
    elif a.side == "left":
        sd.rectangle([0, 0, W * 0.5, H], fill=110)
    elif a.side == "top":
        sd.rectangle([0, 0, W, H * 0.4], fill=110)
    else:
        sd.rectangle([0, H * 0.6, W, H], fill=110)
    from PIL import ImageFilter
    shade = shade.filter(ImageFilter.GaussianBlur(60))
    im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, shade)

    d = ImageDraw.Draw(im)
    cx = {"right": W * 0.74, "left": W * 0.26}.get(a.side, W / 2)
    y = (H - th) / 2 if a.side in ("left", "right") else (H * 0.05 if a.side == "top" else H * 0.95 - th)
    for ln, b in zip(lines, boxes):
        lh = b[3] - b[1]
        d.text((cx, y - b[1]), ln, font=font, fill=color, anchor="ma", stroke_width=stroke, stroke_fill="black")
        y += lh + size * 0.08

    out = Path(a.project) / "output"
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "thumbnail.jpg"
    n = 2
    while dest.exists():
        dest = out / f"thumbnail_{n}.jpg"
        n += 1
    q = 92
    im.save(dest, quality=q)
    while dest.stat().st_size > 2_000_000 and q > 60:
        q -= 8
        im.save(dest, quality=q)
    print(f"Thumbnail saved: {dest}  (font: {Path(font_path).name})")


if __name__ == "__main__":
    main()
