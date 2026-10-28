import os, sys, unittest
import io
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import namenode


class PublicAccessTests(unittest.TestCase):
    def setUp(self):
        self.client = namenode.app.test_client()

    def test_dashboard_is_public(self):
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"VaultGrid", response.data)

    def test_status_api_is_public(self):
        with patch.object(namenode.requests, "get", return_value=type("Health", (), {"ok": True})()):
            response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(all(node["alive"] for node in response.get_json()["nodes"]))

    def test_file_api_is_public(self):
        with patch.object(namenode, "save"):
            response = self.client.delete("/api/files/not-a-real-file")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})

    def test_upload_uses_live_data_nodes_without_authentication(self):
        healthy = type("Health", (), {"ok": True})()
        with patch.object(namenode.requests, "get", return_value=healthy), \
             patch.object(namenode.requests, "put") as put_block, \
             patch.object(namenode, "save"), \
             patch.dict(namenode.files, {}, clear=True):
            response = self.client.post(
                "/api/upload",
                data={"file": (io.BytesIO(b"public test"), "test.txt"), "password": "test-password"},
                content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["blocks"], 1)
        self.assertEqual(put_block.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
