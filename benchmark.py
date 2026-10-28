"""Experiment: effect of block size on upload/download time and block count (2 MB file, 3 DataNodes, x2 replication)."""
import subprocess, sys, time, os, shutil, json, requests
SIZE = 2 * 1024 * 1024
def run():
    shutil.rmtree("data", ignore_errors=True); P = []
    start = lambda *a: P.append(subprocess.Popen([sys.executable, *a], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    for p in (6001, 6002, 6003): start("datanode.py", str(p))
    rows, payload = [], os.urandom(SIZE)
    try:
        for bs in (16, 64, 256, 1024):
            nn = subprocess.Popen([sys.executable, "namenode.py", "--block-size", str(bs * 1024)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3.5)
            t = time.time(); r = requests.post("http://127.0.0.1:5000/api/upload", files={"file": ("bench.bin", payload)}, data={"password": "pw"}); up = time.time() - t
            fid, nb = r.json()["id"], r.json()["blocks"]
            t = time.time(); d = requests.get(f"http://127.0.0.1:5000/api/download/{fid}"); down = time.time() - t
            rows.append(dict(block_kb=bs, blocks=nb, replicas=nb * 2, upload_s=round(up, 2), download_s=round(down, 2), enc_mb=round(len(d.content) / 1048576, 3)))
            print(rows[-1]); nn.terminate(); nn.wait(); os.remove("data/namenode_meta.json"); time.sleep(0.5)
    finally:
        for p in P: p.terminate()
    json.dump(rows, open("/home/claude/bench.json", "w"))
run()
