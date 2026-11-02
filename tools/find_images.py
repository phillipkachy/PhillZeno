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
        items.append({"image": r["image"], "thumb": r.get("thumbnail") or r["image"],
                      "w": r.get("width"), "h": r.get("height"),
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


def save_image(proj, shot, data):
    ext = sniff_ext(data)
    if not ext:
        return {"error": "That wasn't a normal image file (JPG, PNG, WEBP). Try another one."}
    info = ""
    width = None
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as im:
                width, height = im.size
                info = f"{width}x{height}"
        except Exception:
            return {"error": "That image file is broken. Try another one."}
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
            with self.lock:
                return self.send_json(save_image(self.proj, shot, data))
        if u.path == "/api/upload":
            with self.lock:
                return self.send_json(save_image(self.proj, shot, body))
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
    args = ap.parse_args()
    proj = Path(args.project)
    if not (proj / "script.md").exists():
        sys.exit(f"Can't find {proj / 'script.md'}. Check the folder name.")
    if Image is None:
        print("Note: Pillow isn't installed, so image sizes won't be checked. Run setup again to fix.")
    Handler.proj = proj
    Handler.queries_file = proj / "build" / "image_queries.json"
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
  <label style="margin-top:8px"><input type="checkbox" id="onlyMissing"> show only missing</label></header>
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
      <button id="next">Next missing ▶</button>
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
  renderList(); const first=shots.findIndex(s=>!s.files.length); select(first<0?0:first);
}
function renderList(){
  const done=shots.filter(s=>s.files.length).length;
  $("bar").style.width=(100*done/shots.length)+"%";
  $("count").textContent=done+" of "+shots.length+" shots have an image";
  const only=$("onlyMissing").checked;
  $("list").innerHTML="";
  shots.forEach((s,i)=>{ if(only&&s.files.length&&i!==cur)return;
    const d=document.createElement("div");
    d.className="row"+(s.files.length?" done":"")+(i===cur?" sel":"");
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
  h.append(" (adding another keeps both)");}
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
  const s=shots[cur]; s.files.push(d.saved);
  msg("Saved "+d.saved+(d.size?" ("+d.size+")":"")+(d.warn?" · "+d.warn:""),d.warn?"warn":"ok");
  showHave(); renderList(); setTimeout(nextMissing,d.warn?1600:700); return true;
}
async function saveUrl(it,card){
  if(card)card.classList.add("busy"); msg("Saving…");
  const r=await fetch("/api/save_url?shot="+shots[cur].shot,{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({url:it.image,thumb:it.thumb,page:it.page})});
  const ok=await done(await r.json()); if(card&&!ok)card.classList.remove("busy");
}
async function upload(blob){
  msg("Saving…");
  const r=await fetch("/api/upload?shot="+shots[cur].shot,{method:"POST",body:blob});
  done(await r.json());
}
function nextMissing(){
  for(let k=1;k<=shots.length;k++){const j=(cur+k)%shots.length; if(!shots[j].files.length){select(j);return;}}
  msg("Every shot has an image. You're done! 🎉","ok");
}
$("go").onclick=search; $("q").onkeydown=e=>{if(e.key==="Enter")search()};
$("wide").onchange=search; $("next").onclick=nextMissing; $("onlyMissing").onchange=renderList;
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
