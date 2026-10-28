"""CLI client.  python client.py upload FILE PASSWORD | download ID OUT | decrypt FILE.mhc PASSWORD [OUT]"""
import sys, requests, crypto_utils as cu
URL = "http://127.0.0.1:5000"
cmd = sys.argv[1]
if cmd == "upload":
    r = requests.post(URL + "/api/upload", files={"file": open(sys.argv[2], "rb")}, data={"password": sys.argv[3]})
    print(r.json())
elif cmd == "download":
    r = requests.get(f"{URL}/api/download/{sys.argv[2]}"); open(sys.argv[3], "wb").write(r.content); print("saved encrypted:", sys.argv[3])
elif cmd == "decrypt":
    header, blobs = cu.unpack(open(sys.argv[2], "rb").read())
    key = cu.derive_key(sys.argv[3], bytes.fromhex(header["salt"]))
    out = sys.argv[4] if len(sys.argv) > 4 else "decrypted_" + header["name"]
    open(out, "wb").write(b"".join(cu.decrypt_block(key, bid, b) for bid, b in blobs)); print("decrypted ->", out)
