"""One-command demo on a single PC: starts 1 controller + 3 datanodes, uploads, kills a node, proves recovery."""
import subprocess, time, os, sys, hashlib, requests, shutil
shutil.rmtree("data", ignore_errors=True)
P = []
def start(*a): P.append(subprocess.Popen([sys.executable, *a], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
for p in (6001, 6002, 6003): start("datanode.py", str(p))
start("namenode.py"); time.sleep(4)
try:
    open("sample.bin", "wb").write(os.urandom(300_000))
    fid = requests.post("http://127.0.0.1:5000/api/upload", files={"file": open("sample.bin", "rb")}, data={"password": "secret"}).json()["id"]
    print("1. Uploaded: 300 KB -> split into blocks, AES-256-GCM encrypted, replicated x2")
    st = requests.get("http://127.0.0.1:5000/api/status").json()
    print("   Blocks per node:", {n["url"][-4:]: n["blocks"] for n in st["nodes"]})
    P[0].terminate(); print("2. KILLED DataNode 6001"); time.sleep(6)
    enc = requests.get(f"http://127.0.0.1:5000/api/download/{fid}"); open("out.mhc", "wb").write(enc.content)
    print("3. Encrypted download still works (served from surviving replicas):", enc.status_code)
    st = requests.get("http://127.0.0.1:5000/api/status").json()
    print("4. Self-healed block replicas:", sorted(set(len([r for r in b['replicas'] if r.endswith(('6002','6003'))]) for f in st['files'] for b in f['blocks'])))
    subprocess.run([sys.executable, "client.py", "decrypt", "out.mhc", "secret", "restored.bin"])
    h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    print("5. Restored file identical to original:", h("sample.bin") == h("restored.bin"))
    wrong = subprocess.run([sys.executable, "client.py", "decrypt", "out.mhc", "wrong"], capture_output=True)
    print("6. Wrong password rejected:", wrong.returncode != 0)
finally:
    for p in P: p.terminate()
