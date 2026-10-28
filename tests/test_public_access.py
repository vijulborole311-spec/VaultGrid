import os, sys, unittest
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
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertIn("nodes", response.get_json())

    def test_file_api_is_public(self):
        with patch.object(namenode, "save"):
            response = self.client.delete("/api/files/not-a-real-file")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
