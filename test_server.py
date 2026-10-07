import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import server


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_path = Path(self.temp_dir.name) / "users.json"
        self.server = server.create_server(data_path=self.data_path, host="127.0.0.1", port=0)
        self.thread = self.server.thread
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp_dir.cleanup()

    def post_json(self, path, payload, session_id=None):
        headers = {"Content-Type": "application/json"}
        if session_id:
            headers["X-Session-ID"] = session_id
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        return urlopen(request)

    def test_ten_active_users_allow_booking(self):
        for user_number in range(10):
            self.post_json("/api/visit", {}, session_id=f"user-{user_number}")

        response = self.post_json("/api/booking", {}, session_id="user-0")
        self.assertEqual(response.status, 200)

    def test_more_than_ten_users_show_busy(self):
        max_users = server.MAX_ACTIVE_USERS
        for _ in range(max_users):
            self.post_json("/api/visit", {}, session_id=f"user-{_}")

        with self.assertRaises(HTTPError) as visit_error:
            self.post_json("/api/visit", {}, session_id=f"user-{max_users}")
        self.assertEqual(visit_error.exception.code, 503)

        with self.assertRaises(HTTPError) as error:
            self.post_json("/api/booking", {}, session_id=f"user-{max_users}")

        self.assertEqual(error.exception.code, 503)

    def test_eleventh_visit_receives_busy_response(self):
        max_users = server.MAX_ACTIVE_USERS
        for _ in range(max_users):
            self.post_json("/api/visit", {}, session_id=f"user-{_}")

        with self.assertRaises(HTTPError) as error:
            self.post_json("/api/visit", {}, session_id=f"user-{max_users}")

        self.assertEqual(error.exception.code, 503)
        self.assertTrue(json.loads(error.exception.read())["busy"])

    def test_heartbeat_reuses_existing_session(self):
        self.post_json("/api/visit", {}, session_id="same-user")
        response = self.post_json("/api/visit", {}, session_id="same-user")

        self.assertEqual(json.loads(response.read())["activeUsers"], 1)

    def test_health_endpoint_has_required_response(self):
        response = urlopen(f"{self.base_url}/health")

        self.assertEqual(json.loads(response.read()), {"status": "healthy"})

        api_response = urlopen(f"{self.base_url}/api/health")
        self.assertIn("activeUsers", json.loads(api_response.read()))

    def test_dashboard_reports_simulated_vms_and_scaling(self):
        for user_number in range(server.VM_CAPACITY):
            self.post_json("/api/visit", {}, session_id=f"load-{user_number}")

        response = urlopen(f"{self.base_url}/api/admin/dashboard")
        dashboard = json.loads(response.read())

        self.assertGreaterEqual(dashboard["vmCount"], 2)
        self.assertIn("cpu", dashboard["vms"][0])
        self.assertIn("memory", dashboard["vms"][0])
        self.assertIn("capacity", dashboard)
        self.assertTrue(dashboard["scalingEvents"])

    def test_cors_preflight_allows_configured_origin(self):
        request = Request(
            f"{self.base_url}/api/visit",
            method="OPTIONS",
            headers={
                "Origin": "http://localhost:8000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-session-id",
            },
        )

        response = urlopen(request)

        self.assertEqual(response.status, 204)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:8000")
        self.assertIn("X-Session-ID", response.headers["Access-Control-Allow-Headers"])


if __name__ == "__main__":
    unittest.main()
