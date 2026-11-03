"""Turn a list of timed segments (stills with Ken Burns moves, or video clips) into an MP4."""

import math
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .media import EditorError


def _ease(p, amount):
    p = min(max(p, 0.0), 1.0)
    return (1 - amount) * p + amount * (0.5 - 0.5 * math.cos(math.pi * p))


def prepare_canvas(path, cw, ch, cfg):
    """Fill a cw x ch canvas with the picture: crop-to-fill if it's close to the frame shape,
    otherwise the whole picture over a blurred, darkened copy of itself."""
    ic = cfg["images"]
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    if im.mode != "RGB":
        bg = Image.new("RGB", im.size, (0, 0, 0))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[-1])
        im = bg
    aspect = im.width / im.height
    frame_aspect = cw / ch
    lo = ic.get("blur_background_if_aspect_below", 1.45) * (frame_aspect / (16 / 9))
    hi = ic.get("blur_background_if_aspect_above", 2.3) * (frame_aspect / (16 / 9))
    if frame_aspect < 1:  # vertical video: the rule flips
        lo, hi = frame_aspect * 0.8, frame_aspect * 1.3
    blur = ic.get("fill", "smart") == "blur" or (ic.get("fill", "smart") == "smart" and not lo <= aspect <= hi)
    if not blur:
        return ImageOps.fit(im, (cw, ch), Image.LANCZOS, centering=(0.5, 0.4)), False
    small = ImageOps.fit(im, (max(cw // 8, 2), max(ch // 8, 2)), Image.BILINEAR)
    bg = small.filter(ImageFilter.GaussianBlur(6)).resize((cw, ch), Image.BILINEAR)
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    fg = ImageOps.contain(im, (int(cw * 0.96), int(ch * 0.96)), Image.LANCZOS)
    bg.paste(fg, ((cw - fg.width) // 2, (ch - fg.height) // 2))
    return bg, True


class Still:
    def __init__(self, path, start, end, move, focus=(0.5, 0.5)):
        self.path, self.start, self.end, self.move, self.focus = Path(path), start, end, move, focus
        self.canvas = None
        self.kind = "image"

    def open(self, w, h, cfg):
        z = 1 + cfg["ken_burns"].get("zoom", 0.12)
        self.cw, self.ch = round(w * z), round(h * z)
        self.canvas, self.blurred = prepare_canvas(self.path, self.cw, self.ch, cfg)
        self.z, self.w, self.h = z, w, h
        self.ease = cfg["ken_burns"].get("ease", 0.35)

    def box(self, p):
        p = _ease(p, self.ease)
        cw, ch, w, h, z = self.cw, self.ch, self.w, self.h, self.z
        m = self.move
        if m in ("zoom_in", "zoom_out"):
            f = 1 - (1 - 1 / z) * (p if m == "zoom_in" else 1 - p)
            vw, vh = cw * f, ch * f
            cx = min(max(self.focus[0] * cw, vw / 2), cw - vw / 2)
            cy = min(max(self.focus[1] * ch, vh / 2), ch - vh / 2)
            return (cx - vw / 2, cy - vh / 2, cx + vw / 2, cy + vh / 2)
        sx, sy = cw - w, ch - h
        x0, y0 = sx / 2, sy / 2
        if m == "pan_right":
            x0 = sx * p
        elif m == "pan_left":
            x0 = sx * (1 - p)
        elif m == "pan_down":
            y0 = sy * p
        elif m == "pan_up":
            y0 = sy * (1 - p)
        return (x0, y0, x0 + w, y0 + h)

    def frame(self, t):
        p = (t - self.start) / max(self.end - self.start, 1e-6)
        return self.canvas.resize((self.w, self.h), Image.BILINEAR, box=self.box(p))

    def close(self):
        self.canvas = None


class Clip:
    def __init__(self, path, start, end):
        self.path, self.start, self.end = Path(path), start, end
        self.kind = "clip"
        self.proc = None

    def open(self, w, h, cfg, fps):
        self.w, self.h = w, h
        self.proc = subprocess.Popen(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-i", str(self.path),
             "-t", f"{self.end - self.start + 1:.3f}", "-an",
             "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=rgb24",
             "-f", "rawvideo", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.last = Image.new("RGB", (w, h))

    def frame(self, t):
        n = self.w * self.h * 3
        data = self.proc.stdout.read(n)
        if len(data) == n:
            self.last = Image.frombytes("RGB", (self.w, self.h), data)
        return self.last

    def close(self):
        if self.proc:
            self.proc.kill()
            self.proc.wait()
            self.proc = None


def encode(segments, audio, out, total, cfg, w, h, fps, preset, crf, subs=None, workdir=None, label="video"):
    """Pipe every frame into ffmpeg (x264) together with the finished audio."""
    vc = cfg["video"]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
           "-i", str(Path(audio).resolve())]
    if subs:
        fonts = Path(__file__).resolve().parents[2] / "assets" / "fonts"
        # relative paths + cwd avoid Windows drive-letter escaping problems in the filter
        cmd += ["-vf", f"subtitles={Path(subs).name}:fontsdir={_rel(fonts, workdir)}"]
    cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-maxrate", vc.get("max_bitrate", "12M"), "-bufsize", "24M", "-pix_fmt", "yuv420p",
            "-g", str(fps * 2), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", "-shortest", str(Path(out).resolve())]
    log = open(Path(workdir or ".") / "ffmpeg_encode.log", "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log, cwd=workdir)

    kb = cfg["ken_burns"]
    fade_n = int(kb.get("fade_seconds", 0.25) * fps) if kb.get("transition", "cut") == "fade" else 0
    n_frames = int(round(total * fps))
    seg_i, prev = 0, None
    cur = segments[0]
    _open(cur, w, h, cfg, fps)
    started = time.time()
    try:
        for f in range(n_frames):
            t = f / fps
            while seg_i + 1 < len(segments) and t >= segments[seg_i + 1].start:
                if prev is not None:
                    prev.close()
                prev = cur
                seg_i += 1
                cur = segments[seg_i]
                _open(cur, w, h, cfg, fps)
            img = cur.frame(t)
            if fade_n and prev is not None and prev.kind == "image" and cur.kind == "image":
                k = int(round((t - cur.start) * fps))
                if 0 <= k < fade_n:
                    img = Image.blend(prev.frame(t), img, (k + 1) / (fade_n + 1))
            proc.stdin.write(img.tobytes())
            if f % (fps * 10) == 0 and f:
                rate = f / (time.time() - started)
                left = (n_frames - f) / max(rate, 0.01)
                print(f"  {label}: {t / 60:4.1f} of {total / 60:.1f} min rendered  "
                      f"(~{left / 60:.0f} min left)", end="\r")
        proc.stdin.close()
    except BrokenPipeError:
        pass
    finally:
        for s in (prev, cur):
            if s is not None:
                s.close()
    code = proc.wait()
    log.close()
    print(" " * 70, end="\r")
    if code != 0:
        tail = Path(log.name).read_text(encoding="utf-8", errors="replace")[-1500:]
        raise EditorError("The video encoder (ffmpeg) failed:\n" + tail)


def _open(seg, w, h, cfg, fps):
    if seg.kind == "clip":
        seg.open(w, h, cfg, fps)
    else:
        seg.open(w, h, cfg)


def _rel(path, base):
    import os
    try:
        return os.path.relpath(path, base or ".").replace("\\", "/")
    except ValueError:  # different drive on Windows
        return str(path).replace("\\", "/").replace(":", "\\:")
