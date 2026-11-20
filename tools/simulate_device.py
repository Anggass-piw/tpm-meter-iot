#!/usr/bin/env python3
"""Send clearly synthetic readings to the local TPM Meter API."""
import argparse
import json
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def make_reading(index: int, count: int, device_id: str) -> dict:
    progress = index / max(1, count - 1)
    tpm = round(6.5 + 26.0 * progress, 2)  # Synthetic demo curve only.
    category = "RED" if tpm >= 24 else "YELLOW" if tpm >= 20 else "GREEN"
    return {
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "capacitance_pf": round(12.0 + 0.55 * tpm, 3),
        "capacitance_raw": min(4095, max(0, int(450 + tpm * 42))),
        "optical_raw": min(4095, max(0, int(600 + tpm * 48))),
        "temperature_c": round(145.0 + ((index % 5) - 2) * 1.4, 2),
        "tpm_estimate": tpm,
        "category": category,
        "source": "demo",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="base URL API")
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--interval", type=float, default=0.2, help="jeda antar rekaman dalam detik")
    parser.add_argument("--device-id", default="demo-device-01")
    parser.add_argument("--token", default="", help="opsional; lebih aman gunakan perangkat sungguhan dengan env server")
    args = parser.parse_args()
    if args.count < 1 or args.count > 1000:
        parser.error("--count harus 1 sampai 1000")
    if args.interval < 0:
        parser.error("--interval tidak boleh negatif")

    endpoint = args.url.rstrip("/") + "/api/readings"
    for i in range(args.count):
        body = json.dumps(make_reading(i, args.count, args.device_id)).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if args.token:
            headers["Authorization"] = f"Bearer {args.token}"
        request = Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=5) as response:
                print(f"{i + 1}/{args.count}: HTTP {response.status}")
        except (HTTPError, URLError) as exc:
            print(f"Pengiriman gagal: {exc}")
            return 1
        if args.interval and i + 1 < args.count:
            time.sleep(args.interval)
    print("Selesai. Semua pembacaan bertanda source=demo dan bukan data eksperimen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
