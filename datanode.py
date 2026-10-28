"""DataNode: stores encrypted blocks on local disk. Run one per machine on the LAN.
   python datanode.py <port> [storage_dir]"""
import sys, os
from flask import Flask, request, jsonify, send_file, abort

port = int(sys.argv[1]) if len(sys.argv) > 1 else 6001
root = sys.argv[2] if len(sys.argv) > 2 else f"data/datanode_{port}"
os.makedirs(root, exist_ok=True)
app = Flask(__name__)

def path(bid): return os.path.join(root, bid.replace("/", "_") + ".blk")

@app.get("/health")
def health():
    return jsonify(ok=True, port=port, blocks=len(os.listdir(root)))

@app.put("/block/<bid>")
def put(bid):
    open(path(bid), "wb").write(request.get_data()); return jsonify(ok=True)

@app.get("/block/<bid>")
def get(bid):
    if not os.path.exists(path(bid)): abort(404)
    return send_file(path(bid))

@app.delete("/block/<bid>")
def delete(bid):
    if os.path.exists(path(bid)): os.remove(path(bid))
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port, threaded=True)
