"""Cloud Controller (NameNode): splits files into blocks, encrypts, replicates across DataNodes,
   monitors health, self-heals, serves a web dashboard.
   python namenode.py --datanodes http://192.168.1.11:6001 http://192.168.1.12:6001 ..."""
import os, json, time, uuid, argparse, threading, io
from urllib.parse import urlsplit
import requests
from flask import Flask, request, jsonify, send_file, render_template_string, abort
import crypto_utils as cu

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=5000)
ap.add_argument("--datanodes", nargs="+", default=[f"http://127.0.0.1:{p}" for p in (6001, 6002, 6003)])
ap.add_argument("--block-size", type=int, default=64 * 1024, help="bytes per block")
ap.add_argument("--replication", type=int, default=2)
args, _ = ap.parse_known_args()

META = "data/namenode_meta.json"
os.makedirs("data", exist_ok=True)
lock = threading.Lock()
health_lock = threading.Lock()
files = json.load(open(META)) if os.path.exists(META) else {}   # file_id -> metadata
alive = {n: False for n in args.datanodes}
events = []                                                      # recent activity log
app = Flask(__name__)

@app.before_request
def reject_cross_origin_mutations():
    origin = request.headers.get("Origin")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and urlsplit(origin).netloc != request.host:
        return jsonify(error="Cross-origin request rejected"), 403

@app.after_request
def disable_response_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response

def log(msg):
    events.insert(0, f"{time.strftime('%H:%M:%S')}  {msg}"); del events[40:]

def save(): json.dump(files, open(META, "w"))

def live_nodes():
    with health_lock:
        return [node for node, is_alive in alive.items() if is_alive]

def refresh_node_health():
    for node in args.datanodes:
        try:
            is_alive = requests.get(node + "/health", timeout=1).ok
        except requests.RequestException:
            is_alive = False
        with health_lock:
            was_alive = alive[node]
            alive[node] = is_alive
        if was_alive != is_alive:
            log(f"DataNode {node} is now {'ONLINE' if is_alive else 'OFFLINE'}")

def load_of(n): return sum(n in b["replicas"] for f in files.values() for b in f["blocks"])

def pick_nodes(k, exclude=(), extra=None):
    c = [n for n in live_nodes() if n not in exclude]
    return sorted(c, key=lambda n: load_of(n) + (extra or {}).get(n, 0))[:k]

def monitor():
    """Heartbeat + self-healing (re-replication of under-replicated blocks)."""
    while True:
        refresh_node_health()
        with lock:
            for f in files.values():
                for b in f["blocks"]:
                    good = [r for r in b["replicas"] if alive.get(r)]
                    if 0 < len(good) < args.replication:
                        for t in pick_nodes(args.replication - len(good), exclude=b["replicas"]):
                            try:
                                data = requests.get(f"{good[0]}/block/{b['id']}", timeout=3).content
                                if cu.sha256(data) != b["sha256"]: continue
                                requests.put(f"{t}/block/{b['id']}", data=data, timeout=3)
                                b["replicas"].append(t)
                                log(f"SELF-HEAL: re-replicated block {b['id']} -> {t}")
                            except Exception: pass
            save()
        time.sleep(2)

@app.post("/api/upload")
def upload():
    f, pw = request.files.get("file"), request.form.get("password", "")
    if not f or not pw: return jsonify(error="file and password required"), 400
    refresh_node_health()
    if len(live_nodes()) < 1: return jsonify(error="no DataNodes online"), 503
    raw = f.read(); salt = os.urandom(16); key = cu.derive_key(pw, salt)
    fid, blocks, pending = uuid.uuid4().hex[:8], [], {}
    for i in range(0, max(len(raw), 1), args.block_size):
        bid = f"{fid}_b{i // args.block_size}"
        enc = cu.encrypt_block(key, bid, raw[i:i + args.block_size])
        targets = pick_nodes(args.replication, extra=pending)
        for t in targets: pending[t] = pending.get(t, 0) + 1
        for t in targets: requests.put(f"{t}/block/{bid}", data=enc, timeout=5)
        blocks.append(dict(id=bid, enc_len=len(enc), sha256=cu.sha256(enc), replicas=targets))
    with lock:
        files[fid] = dict(name=f.filename, size=len(raw), salt=salt.hex(), created=time.time(), blocks=blocks)
        save()
    log(f"UPLOAD '{f.filename}' -> {len(blocks)} blocks x{args.replication} replicas, AES-256-GCM encrypted")
    return jsonify(id=fid, blocks=len(blocks))

def fetch_block(b):
    for r in b["replicas"]:
        if not alive.get(r): continue
        try:
            d = requests.get(f"{r}/block/{b['id']}", timeout=3).content
            if cu.sha256(d) == b["sha256"]: return d
            log(f"INTEGRITY FAIL block {b['id']} on {r}, trying next replica")
        except Exception: pass
    return None

@app.route("/api/download/<fid>", methods=["GET", "POST"])
def download(fid):
    meta = files.get(fid) or abort(404)
    blobs = []
    for b in meta["blocks"]:
        d = fetch_block(b)
        if d is None: return jsonify(error=f"block {b['id']} unavailable"), 503
        blobs.append(d)
    pw = request.form.get("password") if request.method == "POST" else request.args.get("password")
    if pw:   # optional: server-side decrypt
        key = cu.derive_key(pw, bytes.fromhex(meta["salt"]))
        try: plain = b"".join(cu.decrypt_block(key, b["id"], d) for b, d in zip(meta["blocks"], blobs))
        except Exception: return jsonify(error="wrong password"), 403
        return send_file(io.BytesIO(plain), download_name=meta["name"], as_attachment=True)
    header = dict(name=meta["name"], size=meta["size"], salt=meta["salt"],
                  blocks=[dict(id=b["id"], enc_len=b["enc_len"]) for b in meta["blocks"]])
    log(f"DOWNLOAD '{meta['name']}' in ENCRYPTED form")
    return send_file(io.BytesIO(cu.pack(header, blobs)), download_name=meta["name"] + ".mhc", as_attachment=True)

@app.delete("/api/files/<fid>")
def delete(fid):
    with lock:
        meta = files.pop(fid, None); save()
    for b in (meta or {}).get("blocks", []):
        for r in b["replicas"]:
            try: requests.delete(f"{r}/block/{b['id']}", timeout=2)
            except Exception: pass
    return jsonify(ok=True)

@app.get("/api/status")
def status():
    refresh_node_health()
    return jsonify(replication=args.replication, block_size=args.block_size, events=events,
        nodes=[dict(url=n, alive=alive[n], blocks=load_of(n)) for n in args.datanodes],
        files=[dict(id=k, name=v["name"], size=v["size"], blocks=[dict(id=b["id"],
            replicas=b["replicas"], healthy=len([r for r in b["replicas"] if alive.get(r)])) for b in v["blocks"]])
            for k, v in files.items()])

PAGE = open(os.path.join(os.path.dirname(__file__), "dashboard.html")).read()
LANDING_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<title>VaultGrid — Encrypted, replicated, self-healing storage</title>
<style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color-scheme:dark;--bg:#0b1115;--card:#121b21;--fg:#e8f0f1;--muted:#91a4aa;--line:#26363d;--accent:#69e0c0}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 75% 0,rgba(72,187,158,.15),transparent 42%),var(--bg);color:var(--fg);display:grid;place-items:center;padding:24px}
main{width:min(720px,100%);border:1px solid var(--line);border-radius:24px;background:linear-gradient(145deg,#152129,var(--card));padding:clamp(26px,7vw,58px);box-shadow:0 24px 80px #0005}
.brand{display:flex;align-items:center;gap:12px;color:var(--accent);font-weight:750;letter-spacing:-.04em;font-size:17px}
.mark{width:42px;height:42px;border-radius:14px;background:linear-gradient(145deg,var(--accent),#3b9cbb);display:grid;place-items:center;color:#0c1a19}
.mark svg{width:25px;height:25px}h1{font-size:clamp(34px,8vw,56px);line-height:1.04;letter-spacing:-.055em;margin:36px 0 16px}
.tagline{color:var(--accent);font-size:clamp(16px,3vw,20px);font-weight:600}.description{max-width:570px;color:var(--muted);font-size:15px;line-height:1.75;margin:16px 0 28px}
.features{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:32px}.feature{border:1px solid var(--line);border-radius:999px;padding:7px 11px;color:var(--muted);font-size:12px}
.actions{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.button{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:0 18px;border-radius:11px;background:var(--accent);color:#08211c;text-decoration:none;font-weight:700}
.button:hover{filter:brightness(.93)}.note{font-size:12px;color:var(--muted)}footer{margin-top:42px;border-top:1px solid var(--line);padding-top:18px;color:var(--muted);font-size:11px}
a:focus-visible{outline:3px solid var(--accent);outline-offset:4px}
@media(prefers-color-scheme:light){:root{color-scheme:light;--bg:#f3f7f6;--card:#fff;--fg:#17272a;--muted:#607477;--line:#dce8e5;--accent:#087f68}main{background:linear-gradient(145deg,#fff,#edf7f4)}.mark{color:#08211c}}
</style>
</head>
<body>
<main>
  <div class="brand"><span class="mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 2.8 20 7v10l-8 4.2L4 17V7l8-4.2Z"/><path d="M8 9 12 7l4 2v5l-4 2-4-2V9Z"/><path d="m8.3 9.2 3.7 2 3.7-2M12 11.2V16"/></svg></span>VaultGrid</div>
  <h1>Storage you can trust.</h1>
  <div class="tagline">Encrypted, replicated, self-healing storage</div>
  <p class="description">VaultGrid splits files into encrypted blocks and distributes replicas across Data Nodes, with health monitoring and automatic recovery for under-replicated data.</p>
  <div class="features"><span class="feature">AES-256-GCM encryption</span><span class="feature">Replicated block storage</span><span class="feature">Node health monitoring</span></div>
  <div class="actions"><a class="button" href="/app">Open VaultGrid dashboard</a><span class="note">Dashboard access requires sign-in.</span></div>
  <footer>VaultGrid · Encrypted, replicated, self-healing storage</footer>
</main>
</body>
</html>"""

@app.get("/")
def home(): return render_template_string(LANDING_PAGE)

@app.get("/app")
def dashboard(): return render_template_string(PAGE)

if __name__ == "__main__":
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=args.port, threaded=True)
else:
    threading.Thread(target=monitor, daemon=True).start()
