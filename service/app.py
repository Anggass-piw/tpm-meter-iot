#!/usr/bin/env python3
"""Local HTTP ingestion service for the TPM Meter IoT prototype."""
from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.environ.get("TPM_DB_PATH", ROOT / "data" / "readings.db"))
MAX_BODY = 16_384
VALID_CATEGORIES = {"UNKNOWN", "GREEN", "YELLOW", "RED"}
VALID_SOURCES = {"hardware", "demo"}


def connect_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db(db_path: Path = DB_PATH) -> None:
    with connect_db(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                capacitance_pf REAL,
                capacitance_raw INTEGER NOT NULL,
                optical_raw INTEGER NOT NULL,
                temperature_c REAL NOT NULL,
                tpm_estimate REAL,
                category TEXT NOT NULL,
                source TEXT NOT NULL
            )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_time ON readings(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_readings_device ON readings(device_id, timestamp)")


def validate_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("JSON body harus berupa object")
    try:
        device_id = str(payload["device_id"]).strip()
        cap_raw = int(payload["capacitance_raw"])
        opt_raw = int(payload["optical_raw"])
        temp = float(payload["temperature_c"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("device_id, capacitance_raw, optical_raw, dan temperature_c wajib valid") from exc

    if not device_id or len(device_id) > 64:
        raise ValueError("device_id harus berisi 1–64 karakter")
    if not 0 <= cap_raw <= 4095 or not 0 <= opt_raw <= 4095:
        raise ValueError("nilai raw sensor harus berada pada rentang ADC 0–4095")
    if not -40 <= temp <= 300:
        raise ValueError("temperature_c di luar rentang yang diizinkan")

    cap_pf = payload.get("capacitance_pf")
    if cap_pf is not None:
        cap_pf = float(cap_pf)
        if not 0 <= cap_pf <= 100_000:
            raise ValueError("capacitance_pf di luar rentang yang diizinkan")

    tpm = payload.get("tpm_estimate")
    if tpm is not None:
        tpm = float(tpm)
        if not 0 <= tpm <= 100:
            raise ValueError("tpm_estimate harus berada pada rentang 0–100")

    category = str(payload.get("category", "UNKNOWN")).upper()
    source = str(payload.get("source", "hardware")).lower()
    if category not in VALID_CATEGORIES:
        raise ValueError("category harus UNKNOWN, GREEN, YELLOW, atau RED")
    if source not in VALID_SOURCES:
        raise ValueError("source harus hardware atau demo")

    stamp = payload.get("timestamp")
    if stamp:
        try:
            datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp harus format ISO-8601") from exc
        stamp = str(stamp)
    else:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    return {
        "device_id": device_id,
        "timestamp": stamp,
        "capacitance_pf": cap_pf,
        "capacitance_raw": cap_raw,
        "optical_raw": opt_raw,
        "temperature_c": temp,
        "tpm_estimate": tpm,
        "category": category,
        "source": source,
    }


def insert_reading(reading: dict, db_path: Path = DB_PATH) -> tuple[int, str | None]:
    """Insert and return (id, previous category for this device)."""
    with connect_db(db_path) as conn:
        previous = conn.execute(
            "SELECT category FROM readings WHERE device_id=? ORDER BY id DESC LIMIT 1",
            (reading["device_id"],),
        ).fetchone()
        cur = conn.execute(
            """INSERT INTO readings (
                device_id, timestamp, capacitance_pf, capacitance_raw,
                optical_raw, temperature_c, tpm_estimate, category, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(reading[k] for k in (
                "device_id", "timestamp", "capacitance_pf", "capacitance_raw",
                "optical_raw", "temperature_c", "tpm_estimate", "category", "source"
            )),
        )
        return int(cur.lastrowid), previous["category"] if previous else None


def fetch_readings(limit: int = 100, device_id: str | None = None, db_path: Path = DB_PATH) -> list[dict]:
    limit = max(1, min(int(limit), 1000))
    with connect_db(db_path) as conn:
        if device_id:
            rows = conn.execute(
                "SELECT * FROM readings WHERE device_id=? ORDER BY id DESC LIMIT ?",
                (device_id, limit),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM readings ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def send_telegram(reading: dict) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    message = (
        f"TPM Meter: perangkat {reading['device_id']} berstatus RED. "
        f"Estimasi TPM: {reading['tpm_estimate']}%. Periksa dengan alat acuan; "
        "notifikasi ini bukan hasil pengukuran tersertifikasi."
    )
    body = json.dumps({"chat_id": chat_id, "text": message}).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=8) as response:
            if response.status >= 300:
                print(f"Telegram mengembalikan HTTP {response.status}", file=sys.stderr)
    except Exception as exc:  # Notification failure must not fail ingestion.
        print(f"Notifikasi Telegram gagal: {type(exc).__name__}", file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    server_version = "TPMMeterLocal/0.1"

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str = "application/json; charset=utf-8",
        cache_control: str = "no-store",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _static_file(
        self,
        relative_path: str,
        *,
        cache_control: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        """Serve only regular files inside STATIC, preventing traversal and symlink escapes."""
        try:
            decoded = unquote(relative_path)
            if "\\" in decoded:
                raise ValueError("invalid path")
            root = STATIC.resolve()
            target = (root / decoded).resolve()
            target.relative_to(root)
            if not target.is_file():
                raise FileNotFoundError
            body = target.read_bytes()
        except (OSError, ValueError):
            self._json(404, {"error": "not found"})
            return

        suffix = target.suffix.lower()
        if suffix == ".webmanifest":
            content_type = "application/manifest+json; charset=utf-8"
        elif suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        else:
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type in {"application/json", "application/xml"}:
                content_type += "; charset=utf-8"
        self._send(200, body, content_type, cache_control, extra_headers)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self._static_file("index.html", cache_control="no-cache")
            return
        if parsed.path == "/manifest.webmanifest":
            self._static_file("manifest.webmanifest", cache_control="no-cache")
            return
        if parsed.path == "/sw.js":
            self._static_file(
                "sw.js",
                cache_control="no-cache",
                extra_headers={"Service-Worker-Allowed": "/"},
            )
            return
        if parsed.path.startswith("/static/"):
            self._static_file(parsed.path[len("/static/"):], cache_control="public, max-age=86400")
            return
        if parsed.path == "/api/health":
            self._json(200, {"ok": True, "service": "tpm-meter-iot", "time": datetime.now(timezone.utc).isoformat()})
            return
        if parsed.path == "/api/readings":
            query = parse_qs(parsed.query)
            try:
                limit = int(query.get("limit", [100])[0])
                device = query.get("device_id", [None])[0]
                readings = fetch_readings(limit, device)
            except (ValueError, sqlite3.Error) as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"readings": readings})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/readings":
            self._json(404, {"error": "not found"})
            return
        expected = os.environ.get("DEVICE_TOKEN")
        if expected and self.headers.get("Authorization") != f"Bearer {expected}":
            self._json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("ukuran body tidak valid")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            reading = validate_payload(payload)
            reading_id, previous = insert_reading(reading)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
            return
        except sqlite3.Error:
            self._json(500, {"error": "gagal menyimpan pembacaan"})
            return

        if reading["source"] == "hardware" and reading["category"] == "RED" and previous != "RED":
            send_telegram(reading)
        self._json(201, {"ok": True, "id": reading_id, "stored": reading})

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")


def main() -> None:
    initialize_db()
    host = os.environ.get("TPM_HOST", "0.0.0.0")
    port = int(os.environ.get("TPM_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"TPM Meter IoT API & dashboard berjalan di http://127.0.0.1:{port}")
    print("Tekan Ctrl+C untuk menghentikan server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer dihentikan.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
