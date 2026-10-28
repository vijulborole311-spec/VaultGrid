"""Cloud Controller (NameNode): splits files into blocks, encrypts, replicates across DataNodes,
   monitors health, self-heals, serves a web dashboard.
   python namenode.py --datanodes http://192.168.1.11:6001 http://192.168.1.12:6001 ..."""
import os, json, time, uuid, argparse, threading, io, hmac
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
files = json.load(open(META)) if os.path.exists(META) else {}   # file_id -> metadata
alive = {n: False for n in args.datanodes}
events = []                                                      # recent activity log
app = Flask(__name__)
auth_username = os.environ.get("VAULTGRID_AUTH_USERNAME", "")
auth_password = os.environ.get("VAULTGRID_AUTH_PASSWORD", "")
auth_required = os.environ.get("VAULTGRID_AUTH_REQUIRED", "").lower() in {"1", "true", "yes"}
if auth_required and not (auth_username and auth_password):
    raise RuntimeError("Set VAULTGRID_AUTH_USERNAME and VAULTGRID_AUTH_PASSWORD when authentication is required.")
if bool(auth_username) != bool(auth_password):
    raise RuntimeError("Set both VAULTGRID_AUTH_USERNAME and VAULTGRID_AUTH_PASSWORD, or neither.")

if auth_username and auth_password:
    @app.before_request
    def require_authentication():
        credentials = request.authorization
        if credentials and credentials.username is not None and credentials.password is not None:
            username_ok = hmac.compare_digest(credentials.username.encode("utf-8"), auth_username.encode("utf-8"))
            password_ok = hmac.compare_digest(credentials.password.encode("utf-8"), auth_password.encode("utf-8"))
            if username_ok and password_ok:
                origin = request.headers.get("Origin")
                if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and urlsplit(origin).netloc != request.host:
                    return jsonify(error="Cross-origin request rejected"), 403
                return None
        response = jsonify(error="Authentication required")
        response.status_code = 401
        response.headers["WWW-Authenticate"] = 'Basic realm="VaultGrid", charset="UTF-8"'
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.after_request
    def disable_authenticated_response_caching(response):
        response.headers["Cache-Control"] = "no-store"
        return response

def log(msg):
    events.insert(0, f"{time.strftime('%H:%M:%S')}  {msg}"); del events[40:]

def save(): json.dump(files, open(META, "w"))

def live_nodes(): return [n for n, a in alive.items() if a]

def load_of(n): return sum(n in b["replicas"] for f in files.values() for b in f["blocks"])

def pick_nodes(k, exclude=(), extra=None):
    c = [n for n in live_nodes() if n not in exclude]
    return sorted(c, key=lambda n: load_of(n) + (extra or {}).get(n, 0))[:k]

def monitor():
    """Heartbeat + self-healing (re-replication of under-replicated blocks)."""
    while True:
        for n in args.datanodes:
            was = alive[n]
            try: alive[n] = requests.get(n + "/health", timeout=1).ok
            except Exception: alive[n] = False
            if was != alive[n]: log(f"DataNode {n} is now {'ONLINE' if alive[n] else 'OFFLINE'}")
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
    return jsonify(replication=args.replication, block_size=args.block_size, events=events,
        nodes=[dict(url=n, alive=alive[n], blocks=load_of(n)) for n in args.datanodes],
        files=[dict(id=k, name=v["name"], size=v["size"], blocks=[dict(id=b["id"],
            replicas=b["replicas"], healthy=len([r for r in b["replicas"] if alive.get(r)])) for b in v["blocks"]])
            for k, v in files.items()])

PAGE = open(os.path.join(os.path.dirname(__file__), "dashboard.html")).read()
@app.get("/")
def home(): return render_template_string(PAGE)

if __name__ == "__main__":
    threading.Thread(target=monitor, daemon=True).start()
    app.run(host="0.0.0.0", port=args.port, threaded=True)
else:
    threading.Thread(target=monitor, daemon=True).start()
