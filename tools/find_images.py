"""
Image Finder: collect every image on your shot list in a few clicks.

Run:   python tools/find_images.py projects/<video-folder>

A page opens in your web browser. For each shot it:
  1. searches the web for you (free, no account) and shows a grid of candidates,
  2. saves the one you click straight into images/ with the right number (001.jpg ...),
  3. jumps to the next shot you still need.

Other ways to add an image to the selected shot:
  - copy an image anywhere (right-click > Copy image) and press Ctrl+V / Cmd+V on the page
  - drag an image file (or an image from another browser tab) onto the page
  - paste an image link into the "link" box

AUTOMATIC FIRST PASS (saves you most of the clicking):
   python tools/find_images.py projects/<video-folder> --auto
It picks the best big, wide result for every shot that's still empty, saves it,
then opens the page so you can review. Auto picks show a yellow dot. Click a better
picture to swap one, or press "Reject" (the auto pick moves to build/rejected_auto/).

Safety: it never overwrites or deletes anything. If a shot already has an image,
a new one is saved alongside it as 001-2.jpg (the editor can use both).
Press Ctrl+C in this window to stop.
"""

import argparse
import io
import json
import re
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from script_check import parse_script, WORDS_PER_MINUTE  # noqa: E402

try:
    from PIL import Image
except ImportError:
    Image = None

MIN_GOOD_WIDTH = 1280  # below this, an image looks soft at 1080p
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


# ---------------------------------------------------------------- shots

def load_shots(proj):
    _, paras = parse_script((proj / "script.md").read_text(encoding="utf-8"))
    shots, elapsed = [], 0.0
    for p in paras:
        dur = p["words"] / WORDS_PER_MINUTE * 60
        n = max(len(p["cues"]), 1)
        for k, c in enumerate(p["cues"]):
            shots.append({"shot": c["shot"], "kind": c["kind"], "desc": c["desc"],
                          "time": round(elapsed + dur * k / n),
                          "line": p["text"][:160] + ("…" if len(p["text"]) > 160 else "")})
        elapsed += dur
    return shots


def existing_files(proj, shot):
    out = []
    for folder in ("images", "clips"):
        d = proj / folder
        if d.exists():
            out += [f"{folder}/{f.name}" for f in sorted(d.iterdir())
                    if f.is_file() and re.match(rf"^{shot}(\D|$)", f.name)]
    return out


def default_query(desc):
    """Turn a shot description into a search query."""
    q = re.sub(r"\b(close-up|full|dramatic|side by side|split image)\b", "", desc, flags=re.I)
    q = re.sub(r"[,]+", " ", q)
    return re.sub(r"\s+", " ", q).strip()


# ---------------------------------------------------------------- search

def search_images(query, wide, page_size=30):
    try:
        from ddgs import DDGS
    except ImportError:
        return {"error": "Search add-on missing. Run setup again (setup.bat / bash setup.sh)."}
    kwargs = {"max_results": page_size, "size": "Large"}
    if wide:
        kwargs["layout"] = "Wide"
    try:
        results = DDGS().images(query, **kwargs)
    except Exception as e:  # rate limits, network trouble
        return {"error": f"Search didn't work this time ({type(e).__name__}). Wait a few seconds and "
                         f"try again, or use the Google / Bing buttons and paste the image."}
    items = []
    for r in results:
        if not r.get("image"):
            continue
        def num(v):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0
        items.append({"image": r["image"], "thumb": r.get("thumbnail") or r["image"],
                      "w": num(r.get("width")), "h": num(r.get("height")),
                      "title": r.get("title", ""), "page": r.get("url", "")})
    return {"results": items}


# ---------------------------------------------------------------- saving

def sniff_ext(data):
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] in (b"GIF8",):
        return ".gif"
    if data[:2] == b"BM":
        return ".bmp"
    return None


def check_image(data, min_width=None):
    """Return (ext, width, info) for a real image, or {"error": ...}."""
    ext = sniff_ext(data)
    if not ext:
        return {"error": "That wasn't a normal image file (JPG, PNG, WEBP). Try another one."}
    width, info = None, ""
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as im:
                width, height = im.size
                info = f"{width}x{height}"
        except Exception:
            return {"error": "That image file is broken. Try another one."}
    if min_width and width and width < min_width:
        return {"error": f"too small ({info})"}
    return ext, width, info


def save_image(proj, shot, data, min_width=None):
    checked = check_image(data, min_width)
    if isinstance(checked, dict):
        return checked
    ext, width, info = checked
    images = proj / "images"
    images.mkdir(exist_ok=True)
    name = f"{shot}{ext}"
    n = 1
    while any((images / f"{Path(name).stem}{e}").exists() for e in IMAGE_EXTS):  # never overwrite
        n += 1
        name = f"{shot}-{n}{ext}"
    (images / name).write_bytes(data)
    warn = ""
    if width and width < MIN_GOOD_WIDTH:
        warn = f"Small image ({info}). It'll look a bit soft. Fine for now, swap later if you find a bigger one."
    return {"saved": f"images/{name}", "size": info, "warn": warn}


def fetch_url(url, referer=""):
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("not a web link")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": referer or url,
                                               "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read(40 * 1024 * 1024)


# ---------------------------------------------------------------- auto first pass

# Sites that are mostly fan art, stock photos with watermarks, or merch photos.
SKIP_DOMAINS = ("deviantart", "artstation", "pinterest", "pinimg", "alamy", "shutterstock", "gettyimages",
                "istockphoto", "dreamstime", "123rf", "depositphotos", "redbubble", "etsy", "ebay",
                "amazon", "teepublic", "zazzle", "aliexpress", "tumblr", "instagram", "facebook",
                "tiktok", "reddit", "x.com", "twitter", "funko", "hasbro", "walmart", "target.com")
SKIP_WORDS = ("fan art", "fanart", "fan-art", "redesign", "cosplay", "funko", "lego", "action figure",
              "toy", "figure", "t-shirt", "shirt", "poster print", "sticker", "drawing", "sketch",
              "commission", "ai generated", "ai art", "midjourney", "custom")


def sources_path(proj):
    return proj / "build" / "image_sources.json"


def load_sources(proj):
    try:
        return json.loads(sources_path(proj).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_sources(proj, src):
    sources_path(proj).parent.mkdir(exist_ok=True)
    sources_path(proj).write_text(json.dumps(src, indent=1), encoding="utf-8")


def record_source(proj, shot, saved, url, page, title, auto):
    src = load_sources(proj)
    src.setdefault(shot, [])
    src[shot] = [e for e in src[shot] if (proj / e["file"]).exists()]
    src[shot].append({"file": saved, "url": url, "page": page, "title": title, "auto": auto})
    save_sources(proj, src)


def auto_files(proj, shot):
    """Files in images/ that the auto pass saved (and the owner hasn't kept by choice)."""
    return [e["file"] for e in load_sources(proj).get(shot, [])
            if e.get("auto") and (proj / e["file"]).exists()]


def retire_auto(proj, shot):
    """Move auto picks for a shot out of images/ (into build/rejected_auto/). Never deletes."""
    moved = []
    dest = proj / "build" / "rejected_auto"
    for rel in auto_files(proj, shot):
        dest.mkdir(parents=True, exist_ok=True)
        f = proj / rel
        target = dest / f.name
        n = 1
        while target.exists():
            n += 1
            target = dest / f"{f.stem}_{n}{f.suffix}"
        f.rename(target)
        moved.append(rel)
    if moved:
        src = load_sources(proj)
        src[shot] = [e for e in src.get(shot, []) if e["file"] not in moved]
        save_sources(proj, src)
    return moved


def score_candidate(item, rank):
    """Higher is better. Prefers big, wide, non-fan-art images near the top of the results."""
    text = (item.get("page", "") + " " + item.get("image", "")).lower()
    title = item.get("title", "").lower()
    if any(d in text for d in SKIP_DOMAINS):
        return None
    if any(w in title for w in SKIP_WORDS):
        return None
    w, h = item.get("w") or 0, item.get("h") or 0
    score = -rank * 0.15
    if w >= 1920:
        score += 3
    elif w >= 1280:
        score += 2
    elif w >= 900:
        score += 0.5
    else:
        score -= 3
    if h:
        aspect = w / h
        if 1.3 <= aspect <= 2.1:
            score += 2
        elif aspect < 1:
            score -= 1
    if "wallpaper" in title:
        score -= 0.5  # wallpapers are often fan edits
    return score


def auto_fill(proj, queries_file):
    shots = load_shots(proj)
    try:
        saved_q = json.loads(queries_file.read_text(encoding="utf-8"))
    except Exception:
        saved_q = {}
    todo = [s for s in shots if not existing_files(proj, s["shot"])
            and not re.search(r"phillzeno|end card|your logo|my logo", s["desc"], re.I)]  # owner's branding
    print(f"Automatic first pass: {len(todo)} of {len(shots)} shots need an image.")
    print("This takes a few seconds per shot. Leave it running.\n")
    got, failed = 0, []
    for i, s in enumerate(todo, 1):
        q = saved_q.get(s["shot"]) or default_query(s["desc"])
        res = {}
        for wait in (0, 6, 15, 30):  # back off if the search engine says "slow down"
            if wait:
                time.sleep(wait)
            res = search_images(q, wide=True)
            if "error" not in res and not res.get("results"):
                res = search_images(q, wide=False)  # nothing wide? allow any shape
            if "error" not in res:
                break
        cands = []
        for rank, it in enumerate(res.get("results", [])):
            sc = score_candidate(it, rank)
            if sc is not None:
                cands.append((sc, it))
        cands.sort(key=lambda x: -x[0])
        saved = None
        for _, it in cands[:6]:
            try:
                data = fetch_url(it["image"], it.get("page", ""))
            except Exception:
                continue
            r = save_image(proj, s["shot"], data, min_width=800)
            if "saved" in r:
                record_source(proj, s["shot"], r["saved"], it["image"], it.get("page", ""),
                              it.get("title", ""), auto=True)
                saved = r
                break
        tag = f"[{i}/{len(todo)}] {s['shot']}"
        if saved:
            got += 1
            print(f"{tag}  saved {saved['saved']} ({saved['size']})  {s['desc'][:50]}")
        else:
            why = res.get("error", "no usable result")
            failed.append(s["shot"])
            print(f"{tag}  SKIPPED ({why[:60]})  {s['desc'][:50]}")
        time.sleep(1.5)  # be polite to the search engine
    print(f"\nDone: {got} saved automatically, {len(failed)} still need you"
          + (f" ({', '.join(failed)})." if failed else "."))
    print("Now review them on the page: yellow dots are auto picks.\n")


# ---------------------------------------------------------------- web server

class Handler(BaseHTTPRequestHandler):
    proj: Path = None
    queries_file: Path = None
    lock = threading.Lock()

    def log_message(self, *a):  # keep the terminal quiet
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_queries(self):
        try:
            return json.loads(self.queries_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif u.path == "/api/shots":
            saved_q = self.read_queries()
            shots = load_shots(self.proj)
            for s in shots:
                s["files"] = existing_files(self.proj, s["shot"])
                s["query"] = saved_q.get(s["shot"]) or default_query(s["desc"])
                s["auto"] = bool(auto_files(self.proj, s["shot"]))
            self.send_json({"project": self.proj.name, "shots": shots})
        elif u.path == "/api/search":
            q = qs.get("q", [""])[0]
            wide = qs.get("wide", ["1"])[0] == "1"
            shot = qs.get("shot", [""])[0]
            if shot:
                with self.lock:
                    saved_q = self.read_queries()
                    saved_q[shot] = q
                    self.queries_file.parent.mkdir(exist_ok=True)
                    self.queries_file.write_text(json.dumps(saved_q, indent=1), encoding="utf-8")
            self.send_json(search_images(q, wide))
        elif u.path.startswith("/file/"):
            rel = urllib.parse.unquote(u.path[len("/file/"):])
            f = (self.proj / rel).resolve()
            if self.proj.resolve() not in f.parents or not f.is_file():
                return self.send_json({"error": "not found"}, 404)
            data = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/" + f.suffix.lstrip(".").replace("jpg", "jpeg"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_json({"error": "not found"}, 404)

    def store(self, shot, data, url, page, title):
        """Save a picked image. A manual pick on an auto-picked shot swaps the auto pick out."""
        with self.lock:
            checked = check_image(data)  # validate before swapping anything out
            if isinstance(checked, dict):
                return checked
            moved = retire_auto(self.proj, shot)
            r = save_image(self.proj, shot, data)
            record_source(self.proj, shot, r["saved"], url, page, title, auto=False)
            r["swapped"] = bool(moved)
            r["files"] = existing_files(self.proj, shot)
            return r

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        shot = qs.get("shot", [""])[0]
        if not re.fullmatch(r"\d{3}", shot):
            return self.send_json({"error": "bad shot number"}, 400)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if u.path == "/api/save_url":
            payload = json.loads(body or b"{}")
            try:
                data = fetch_url(payload.get("url", ""), payload.get("page", ""))
            except Exception:
                thumb = payload.get("thumb")
                if not thumb:
                    return self.send_json({"error": "That site blocked the download. Pick another, "
                                                    "or open it, right-click > Copy image, then Ctrl+V here."})
                try:
                    data = fetch_url(thumb)  # fall back to the search preview (smaller)
                except Exception:
                    return self.send_json({"error": "That site blocked the download. Pick another one."})
            return self.send_json(self.store(shot, data, payload.get("url", ""), payload.get("page", ""),
                                             payload.get("title", "")))
        if u.path == "/api/upload":
            return self.send_json(self.store(shot, body, "", "", "pasted or dropped"))
        if u.path == "/api/keep":
            with self.lock:
                src = load_sources(self.proj)
                for e in src.get(shot, []):
                    e["auto"] = False  # owner approved it: treat like their own pick
                save_sources(self.proj, src)
            return self.send_json({"ok": True})
        if u.path == "/api/reject":
            with self.lock:
                moved = retire_auto(self.proj, shot)
            return self.send_json({"moved": moved, "files": existing_files(self.proj, shot)})
        self.send_json({"error": "not found"}, 404)


def free_port(start=8765):
    for port in range(start, start + 50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return 0


def main():
    ap = argparse.ArgumentParser(description="Find and save images for a shot list")
    ap.add_argument("project", help="project folder, e.g. projects/avengers-doomsday")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser automatically")
    ap.add_argument("--auto", action="store_true", help="automatically pick an image for every empty shot first")
    ap.add_argument("--auto-only", action="store_true", help="do the automatic pass, then stop (no page)")
    args = ap.parse_args()
    proj = Path(args.project)
    if not (proj / "script.md").exists():
        sys.exit(f"Can't find {proj / 'script.md'}. Check the folder name.")
    if Image is None:
        print("Note: Pillow isn't installed, so image sizes won't be checked. Run setup again to fix.")
    Handler.proj = proj
    Handler.queries_file = proj / "build" / "image_queries.json"
    if args.auto or args.auto_only:
        auto_fill(proj, Handler.queries_file)
        if args.auto_only:
            return
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Image Finder is running for '{proj.name}'.")
    print(f"Open {url} if it didn't open by itself.  Press Ctrl+C here to stop.")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Your images are in", proj / "images")


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Image Finder</title>
<style>
:root{--bg:#111318;--panel:#1a1d24;--line:#2b2f3a;--text:#e9ebf0;--muted:#9aa1b2;--accent:#e23b3b;--ok:#38b26b;--warn:#e0a526}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;display:flex;height:100vh;overflow:hidden}
#side{width:330px;border-right:1px solid var(--line);display:flex;flex-direction:column}
#side header{padding:14px 16px;border-bottom:1px solid var(--line)}
#side h1{font-size:17px;margin:0 0 6px}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--ok);width:0}
#count{color:var(--muted);font-size:13px;margin-top:6px}
#list{overflow:auto;flex:1}
.row{display:flex;gap:10px;padding:8px 14px;border-bottom:1px solid var(--line);cursor:pointer;align-items:center}
.row:hover{background:var(--panel)}
.row.sel{background:#2a1c1f;border-left:3px solid var(--accent);padding-left:11px}
.num{font-weight:700;min-width:34px}
.dot{width:10px;height:10px;border-radius:50%;background:var(--line);flex:none}
.done .dot{background:var(--ok)}
.auto .dot{background:var(--warn)}
select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:4px;padding:2px 4px}
.desc{font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#main{flex:1;display:flex;flex-direction:column;overflow:hidden}
#top{padding:14px 18px;border-bottom:1px solid var(--line)}
#title{font-size:20px;font-weight:700;margin:0}
#line{color:var(--muted);font-size:13px;margin:4px 0 10px;font-style:italic}
.ctl{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
input[type=text]{flex:1;min-width:220px;background:var(--panel);border:1px solid var(--line);color:var(--text);padding:9px 10px;border-radius:6px;font-size:15px}
button,a.btn{background:var(--panel);color:var(--text);border:1px solid var(--line);padding:8px 12px;border-radius:6px;cursor:pointer;font-size:14px;text-decoration:none}
button.primary{background:var(--accent);border-color:var(--accent);font-weight:600}
button:hover,a.btn:hover{filter:brightness(1.2)}
label{color:var(--muted);font-size:13px;display:flex;gap:4px;align-items:center}
#have{display:flex;gap:8px;margin-top:10px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:13px}
#have img{height:60px;border-radius:4px;border:2px solid var(--ok)}
#msg{margin-top:8px;font-size:14px;min-height:20px}
#msg.ok{color:var(--ok)}#msg.err{color:var(--accent)}#msg.warn{color:var(--warn)}
#grid{flex:1;overflow:auto;padding:14px 18px;display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;align-content:start}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden;cursor:pointer;position:relative}
.card:hover{border-color:var(--accent)}
.card img{width:100%;height:150px;object-fit:cover;display:block;background:#000}
.card .meta{padding:6px 8px;font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card .wh{position:absolute;top:6px;right:6px;background:rgba(0,0,0,.75);padding:2px 6px;border-radius:4px;font-size:11px}
.card .wh.big{color:var(--ok)}
.card.busy{opacity:.4;pointer-events:none}
#drop{position:fixed;inset:0;background:rgba(226,59,59,.18);border:4px dashed var(--accent);display:none;align-items:center;justify-content:center;font-size:28px;font-weight:700;z-index:9}
.tip{color:var(--muted);font-size:12px;padding:10px 16px;border-top:1px solid var(--line)}
kbd{background:var(--panel);border:1px solid var(--line);border-radius:3px;padding:0 4px;font-size:11px}
@media (max-width:760px){body{flex-direction:column;height:auto;overflow:auto}#side{width:auto;max-height:40vh}#grid{overflow:visible}}
</style></head><body>
<div id="side">
  <header><h1 id="proj">Image Finder</h1><div class="bar"><i id="bar"></i></div><div id="count"></div>
  <label style="margin-top:8px">Show <select id="mode"><option value="all">all shots</option><option value="missing">only missing</option><option value="auto">auto picks to review</option></select></label></header>
  <div id="list"></div>
  <div class="tip">Click a picture to save it. Or copy any image and press <kbd>Ctrl</kbd>+<kbd>V</kbd>, or drag one in.
  <br>Prefer official stills and real comic panels. Skip watermarked fan art.</div>
</div>
<div id="main">
  <div id="top">
    <p id="title">Loading…</p><p id="line"></p>
    <div class="ctl">
      <input type="text" id="q" placeholder="search words">
      <button class="primary" id="go">Search</button>
      <label><input type="checkbox" id="wide" checked> wide only</label>
      <a class="btn" id="gImg" target="_blank">Google ↗</a>
      <a class="btn" id="bImg" target="_blank">Bing ↗</a>
      <button id="next">Next ▶</button>
    </div>
    <div class="ctl" style="margin-top:8px">
      <input type="text" id="link" placeholder="…or paste an image link here and press Enter">
    </div>
    <div id="have"></div>
    <div id="msg"></div>
  </div>
  <div id="grid"></div>
</div>
<div id="drop">Drop to save</div>
<script>
let shots=[], cur=0;
const $=id=>document.getElementById(id);
function fmt(t){return Math.floor(t/60)+":"+String(t%60).padStart(2,"0")}
function msg(t,c){const m=$("msg");m.textContent=t;m.className=c||""}
async function load(){
  const r=await fetch("/api/shots");const d=await r.json();shots=d.shots;
  $("proj").textContent="Images: "+d.project;
    if(shots.some(s=>s.auto)&&!shots.some(s=>!s.files.length))$("mode").value="auto";
  renderList(); let first=shots.findIndex(s=>!s.files.length); if(first<0)first=shots.findIndex(s=>s.auto); select(first<0?0:first);
}
function renderList(){
  const done=shots.filter(s=>s.files.length).length, autoN=shots.filter(s=>s.auto).length;
  $("bar").style.width=(100*done/shots.length)+"%";
  $("count").textContent=done+" of "+shots.length+" shots have an image"+(autoN?" · "+autoN+" auto picks to review":"");
  const mode=$("mode").value;
  $("list").innerHTML="";
  shots.forEach((s,i)=>{ if(i!==cur&&((mode==="missing"&&s.files.length)||(mode==="auto"&&!s.auto)))return;
    const d=document.createElement("div");
    d.className="row"+(s.auto?" auto":s.files.length?" done":"")+(i===cur?" sel":"");
    d.innerHTML=`<span class="dot"></span><span class="num">${s.shot}</span><span class="desc"></span>`;
    d.querySelector(".desc").textContent=(s.kind==="CLIP"?"🎬 ":"")+s.desc;
    d.onclick=()=>select(i); $("list").appendChild(d);
  });
  const sel=$("list").querySelector(".sel"); if(sel)sel.scrollIntoView({block:"nearest"});
}
function select(i){
  cur=i;const s=shots[i];
  $("title").textContent=`#${s.shot} · ${fmt(s.time)} · ${s.desc}`;
  $("line").textContent=s.line?"“"+s.line+"”":"";
  $("q").value=s.query; updateLinks(); showHave(); renderList(); msg(s.kind==="CLIP"
    ? "This is a CLIP shot. Put your own video file in clips/ named "+s.shot+".mp4, or save an image here instead.":"");
  search();
}
function updateLinks(){const q=encodeURIComponent($("q").value);
  $("gImg").href="https://www.google.com/search?tbm=isch&tbs=isz:l&q="+q;
  $("bImg").href="https://www.bing.com/images/search?qft=+filterui:imagesize-large&q="+q;}
function showHave(){const s=shots[cur];const h=$("have");h.innerHTML="";
  if(!s.files.length)return; h.append("Saved: ");
  s.files.forEach(f=>{ if(/\.(jpe?g|png|webp|gif|bmp)$/i.test(f)){const im=document.createElement("img");im.src="/file/"+encodeURIComponent(f);im.title=f;h.appendChild(im);} else h.append(f+" ");});
  if(s.auto){h.append(" AUTO pick. Click a better one to swap it, or ");
    const b=document.createElement("button");b.textContent="✗ Reject";b.onclick=reject;h.appendChild(b);
    const k=document.createElement("button");k.textContent="✓ Keep";k.onclick=async()=>{await fetch("/api/keep?shot="+s.shot,{method:"POST"});s.auto=false;renderList();showHave();next();};h.appendChild(k);}
  else h.append(" (adding another keeps both)");}
async function reject(){const s=shots[cur];
  const r=await fetch("/api/reject?shot="+s.shot,{method:"POST"});const d=await r.json();
  s.files=d.files;s.auto=false;msg("Auto pick removed (moved to build/rejected_auto/). Pick a better one below.","warn");
  showHave();renderList();}
let searchId=0;
async function search(){
  const id=++searchId;const s=shots[cur];const q=$("q").value.trim();s.query=q;updateLinks();
  $("grid").innerHTML="<p style='color:var(--muted)'>Searching…</p>";
  const r=await fetch(`/api/search?shot=${s.shot}&wide=${$("wide").checked?1:0}&q=`+encodeURIComponent(q));
  const d=await r.json(); if(id!==searchId)return;
  $("grid").innerHTML="";
  if(d.error){$("grid").innerHTML="<p></p>";$("grid").firstChild.textContent=d.error;return;}
  if(!d.results.length){$("grid").innerHTML="<p style='color:var(--muted)'>Nothing found. Try fewer or different words.</p>";return;}
  d.results.forEach(it=>{
    const c=document.createElement("div");c.className="card";
    const big=it.w>=1280;
    c.innerHTML=`<img loading="lazy" referrerpolicy="no-referrer"><span class="wh ${big?"big":""}">${it.w||"?"}×${it.h||"?"}</span><div class="meta"></div>`;
    c.querySelector("img").src=it.thumb; c.querySelector(".meta").textContent=it.title||it.page;
    c.querySelector("img").onerror=()=>c.remove();
    c.onclick=()=>saveUrl(it,c); $("grid").appendChild(c);
  });
}
async function done(d){
  if(d.error){msg(d.error,"err");return false;}
  const s=shots[cur]; s.files=d.files||s.files.concat([d.saved]); s.auto=false;
  msg((d.swapped?"Swapped in ":"Saved ")+d.saved+(d.size?" ("+d.size+")":"")+(d.warn?" · "+d.warn:""),d.warn?"warn":"ok");
  showHave(); renderList(); setTimeout(next,d.warn?1600:700); return true;
}
async function saveUrl(it,card){
  if(card)card.classList.add("busy"); msg("Saving…");
  const r=await fetch("/api/save_url?shot="+shots[cur].shot,{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({url:it.image,thumb:it.thumb,page:it.page,title:it.title||""})});
  const ok=await done(await r.json()); if(card&&!ok)card.classList.remove("busy");
}
async function upload(blob){
  msg("Saving…");
  const r=await fetch("/api/upload?shot="+shots[cur].shot,{method:"POST",body:blob});
  done(await r.json());
}
function next(){
  const want=$("mode").value==="auto"?(s=>s.auto):(s=>!s.files.length);
  for(let k=1;k<=shots.length;k++){const j=(cur+k)%shots.length; if(want(shots[j])){select(j);return;}}
  if($("mode").value!=="auto"&&shots.some(s=>s.auto)){$("mode").value="auto";renderList();return next();}
  msg("Every shot has an image. You're done! 🎉","ok");
}
$("go").onclick=search; $("q").onkeydown=e=>{if(e.key==="Enter")search()};
$("wide").onchange=search; $("next").onclick=next; $("mode").onchange=()=>{renderList();next();};
$("link").onkeydown=e=>{if(e.key==="Enter"&&$("link").value.trim()){saveUrl({image:$("link").value.trim()});$("link").value="";}};
document.addEventListener("paste",e=>{
  if(e.target.tagName==="INPUT"&&e.target.id!=="link")return;
  for(const item of e.clipboardData.items){ if(item.type.startsWith("image/")){e.preventDefault();upload(item.getAsFile());return;} }
  const t=e.clipboardData.getData("text"); if(/^https?:\/\//.test(t)&&e.target.id!=="link"){e.preventDefault();saveUrl({image:t.trim()});}
});
let dragN=0;
document.addEventListener("dragenter",e=>{e.preventDefault();dragN++;$("drop").style.display="flex"});
document.addEventListener("dragleave",e=>{dragN--;if(dragN<=0){$("drop").style.display="none";dragN=0}});
document.addEventListener("dragover",e=>e.preventDefault());
document.addEventListener("drop",e=>{e.preventDefault();dragN=0;$("drop").style.display="none";
  const f=[...e.dataTransfer.files].find(f=>f.type.startsWith("image/")); if(f){upload(f);return;}
  const html=e.dataTransfer.getData("text/html"); const m=html&&html.match(/<img[^>]+src="([^"]+)"/i);
  const u=(m&&m[1])||e.dataTransfer.getData("text/uri-list")||e.dataTransfer.getData("text");
  if(u&&/^https?:/.test(u))saveUrl({image:u.trim()}); else msg("Couldn't read that. Try right-click > Copy image, then Ctrl+V.","err");
});
load();
</script></body></html>
"""

if __name__ == "__main__":
    main()
