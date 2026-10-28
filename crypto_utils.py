"""AES-256-GCM helpers. Key = PBKDF2(password, salt). Server never stores the password."""
import os, json, struct, hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

MAGIC = b"MHC1"

def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return kdf.derive(password.encode())

def encrypt_block(key: bytes, block_id: str, data: bytes) -> bytes:
    nonce = os.urandom(12)
    # block id is bound as associated data -> blocks can't be swapped/reordered
    return nonce + AESGCM(key).encrypt(nonce, data, block_id.encode())

def decrypt_block(key: bytes, block_id: str, blob: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:12], blob[12:], block_id.encode())

def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def pack(header: dict, blobs: list) -> bytes:
    h = json.dumps(header).encode()
    return MAGIC + struct.pack(">I", len(h)) + h + b"".join(blobs)

def unpack(raw: bytes):
    assert raw[:4] == MAGIC, "Not a VaultGrid encrypted file"
    (hl,) = struct.unpack(">I", raw[4:8])
    header = json.loads(raw[8:8 + hl])
    pos, blobs = 8 + hl, []
    for b in header["blocks"]:
        blobs.append((b["id"], raw[pos:pos + b["enc_len"]])); pos += b["enc_len"]
    return header, blobs
