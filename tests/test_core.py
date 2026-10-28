import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crypto_utils as cu

class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.salt = os.urandom(16); self.key = cu.derive_key("secret", self.salt)

    def test_roundtrip(self):
        d = os.urandom(5000)
        self.assertEqual(cu.decrypt_block(self.key, "f_b0", cu.encrypt_block(self.key, "f_b0", d)), d)

    def test_ciphertext_differs_from_plaintext(self):
        d = b"A" * 1000
        self.assertNotIn(d[:50], cu.encrypt_block(self.key, "f_b0", d))

    def test_same_block_encrypts_differently_each_time(self):
        d = b"hello"
        self.assertNotEqual(cu.encrypt_block(self.key, "b", d), cu.encrypt_block(self.key, "b", d))

    def test_wrong_password_rejected(self):
        blob = cu.encrypt_block(self.key, "b", b"data")
        with self.assertRaises(Exception):
            cu.decrypt_block(cu.derive_key("wrong", self.salt), "b", blob)

    def test_tampered_block_detected(self):
        blob = bytearray(cu.encrypt_block(self.key, "b", b"data" * 10)); blob[20] ^= 1
        with self.assertRaises(Exception): cu.decrypt_block(self.key, "b", bytes(blob))

    def test_blocks_cannot_be_swapped(self):
        blob = cu.encrypt_block(self.key, "f_b0", b"data")
        with self.assertRaises(Exception): cu.decrypt_block(self.key, "f_b1", blob)

    def test_container_pack_unpack(self):
        blobs = [cu.encrypt_block(self.key, f"f_b{i}", os.urandom(100)) for i in range(3)]
        hdr = dict(name="x.bin", size=300, salt=self.salt.hex(),
                   blocks=[dict(id=f"f_b{i}", enc_len=len(b)) for i, b in enumerate(blobs)])
        h, out = cu.unpack(cu.pack(hdr, blobs))
        self.assertEqual(h["name"], "x.bin"); self.assertEqual([b for _, b in out], blobs)

    def test_sha256_changes_on_corruption(self):
        self.assertNotEqual(cu.sha256(b"abc"), cu.sha256(b"abd"))

if __name__ == "__main__": unittest.main(verbosity=2)
