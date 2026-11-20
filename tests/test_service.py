import json
import sys
import threading
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

import app  # noqa: E402


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.valid = {
            "device_id": "unit-test",
            "capacitance_pf": None,
            "capacitance_raw": 1800,
            "optical_raw": 950,
            "temperature_c": 145.5,
            "tpm_estimate": None,
            "category": "UNKNOWN",
            "source": "hardware",
        }

    def test_accepts_uncalibrated_reading(self):
        reading = app.validate_payload(self.valid)
        self.assertIsNone(reading["tpm_estimate"])
        self.assertEqual(reading["category"], "UNKNOWN")
        self.assertTrue(reading["timestamp"])

    def test_rejects_out_of_range_adc(self):
        payload = dict(self.valid, optical_raw=4096)
        with self.assertRaisesRegex(ValueError, "0–4095"):
            app.validate_payload(payload)

    def test_rejects_unknown_category(self):
        payload = dict(self.valid, category="SAFE")
        with self.assertRaisesRegex(ValueError, "category"):
            app.validate_payload(payload)

    def test_persists_and_fetches_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.sqlite"
            app.initialize_db(db)
            first = app.validate_payload(dict(self.valid, category="GREEN", tpm_estimate=12.4))
            first_id, first_prev = app.insert_reading(first, db)
            second = app.validate_payload(dict(self.valid, category="YELLOW", tpm_estimate=21.2))
            second_id, second_prev = app.insert_reading(second, db)
            rows = app.fetch_readings(limit=10, db_path=db)
            self.assertEqual(first_prev, None)
            self.assertEqual(second_prev, "GREEN")
            self.assertGreater(second_id, first_id)
            self.assertEqual(rows[0]["category"], "YELLOW")
            self.assertEqual(len(rows), 2)


class HttpRouteTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.static = self.root / "static"
        self.static.mkdir()
        (self.static / "index.html").write_text("<html>dashboard</html>", encoding="utf-8")
        (self.static / "manifest.webmanifest").write_text('{"name":"TPM Meter"}', encoding="utf-8")
        (self.static / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
        (self.static / "icons").mkdir()
        (self.static / "icons" / "icon-192.png").write_bytes(b"png-192")
        (self.static / "icons" / "icon-512.png").write_bytes(b"png-512")
        (self.root / "private.txt").write_text("must not be served", encoding="utf-8")
        self.static_patcher = patch.object(app, "STATIC", self.static)
        self.static_patcher.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.static_patcher.stop()
        self.tempdir.cleanup()

    def get(self, path):
        return urlopen(self.base_url + path, timeout=3)

    def test_dashboard_route_has_html_content_type_and_revalidation_policy(self):
        with self.get("/") as response:
            self.assertEqual(response.status, 200)
            self.assertTrue(response.headers["Content-Type"].startswith("text/html"))
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

    def test_manifest_icon_and_root_service_worker_routes(self):
        with self.get("/manifest.webmanifest") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/manifest+json; charset=utf-8")
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
        for icon in ("icon-192.png", "icon-512.png"):
            with self.subTest(icon=icon), self.get(f"/static/icons/{icon}") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Content-Type"], "image/png")
                self.assertEqual(response.headers["Cache-Control"], "public, max-age=86400")
        with self.get("/sw.js") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/javascript; charset=utf-8")
            self.assertEqual(response.headers["Cache-Control"], "no-cache")
            self.assertEqual(response.headers["Service-Worker-Allowed"], "/")

    def test_api_responses_are_never_cached(self):
        with patch.object(app, "fetch_readings", return_value=[{"device_id": "private-device"}]):
            for path in ("/api/health", "/api/readings"):
                with self.subTest(path=path), self.get(path) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertTrue(response.headers["Content-Type"].startswith("application/json"))

    def test_static_path_traversal_is_rejected(self):
        with self.assertRaises(HTTPError) as result:
            self.get("/static/%2e%2e/private.txt")
        self.assertEqual(result.exception.code, 404)
        self.assertEqual(result.exception.headers["Cache-Control"], "no-store")

    def test_unknown_route_returns_not_found(self):
        with self.assertRaises(HTTPError) as result:
            self.get("/not-a-route")
        self.assertEqual(result.exception.code, 404)
        self.assertEqual(result.exception.headers["Cache-Control"], "no-store")


class AppAssetsTests(unittest.TestCase):
    def test_manifest_references_existing_png_icons_cached_by_service_worker(self):
        static = ROOT / "service" / "static"
        manifest = json.loads((static / "manifest.webmanifest").read_text(encoding="utf-8"))
        service_worker = (static / "sw.js").read_text(encoding="utf-8")
        sizes = set()
        for icon in manifest["icons"]:
            src = icon["src"]
            self.assertTrue(src.startswith("/static/icons/"))
            path = static / src.removeprefix("/static/")
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn(f"'{src}'", service_worker)
            sizes.add(icon["sizes"])
        self.assertTrue({"192x192", "512x512"}.issubset(sizes))


if __name__ == "__main__":
    unittest.main()
