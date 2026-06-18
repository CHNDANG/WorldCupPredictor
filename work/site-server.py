"""
Local web server for the World Cup predictor.

It serves files from outputs/. Opening the homepage starts an immediate refresh,
and live-feed.json/API requests refresh the ESPN feed before returning data, so
the page checks current and upcoming fixtures as soon as it loads.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import sys
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"
OUTPUTS = ROOT / "outputs"
LOG = WORK / "site-server.log"


def log_line(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def load_live_bridge():
    if str(WORK) not in sys.path:
        sys.path.insert(0, str(WORK))
    module_path = WORK / "live-feed-bridge-espn.py"
    spec = importlib.util.spec_from_file_location("live_feed_bridge_espn", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["live_feed_bridge_espn"] = module
    spec.loader.exec_module(module)
    return module


class LiveFeedRefresher:
    def __init__(self, min_interval: int) -> None:
        self.min_interval = max(min_interval, 5)
        self.lock = threading.Lock()
        self.live = load_live_bridge()
        self.last_attempt = 0.0
        self.last_success = 0.0
        self.last_error = ""

    def refresh(self, force: bool = False, reason: str = "request") -> dict[str, Any]:
        request_started = time.time()
        if self.live.OUT.exists() and request_started - self.last_success < self.min_interval:
            return self.status("fresh-recent")
        if not force and request_started - self.last_attempt < self.min_interval and self.live.OUT.exists():
            return self.status("cached")
        with self.lock:
            now = time.time()
            if self.live.OUT.exists() and self.last_success >= request_started:
                return self.status("fresh-current")
            if self.live.OUT.exists() and now - self.last_success < self.min_interval:
                return self.status("fresh-recent")
            if not force and now - self.last_attempt < self.min_interval and self.live.OUT.exists():
                return self.status("cached")
            self.last_attempt = now
            try:
                payload = self.live.fetch_feed()
                self.live.write_feed(payload)
                self.last_success = time.time()
                self.last_error = ""
                log_line(f"REFRESH ok reason={reason} matches={len(payload.get('matches', []))}")
                return {
                    "ok": True,
                    "mode": "fresh",
                    "reason": reason,
                    "updatedAt": payload.get("updatedAt"),
                    "matches": len(payload.get("matches", [])),
                    "sourceStatus": payload.get("sourceStatus", ""),
                }
            except Exception as error:  # noqa: BLE001 - keep serving last valid file.
                self.last_error = f"{type(error).__name__}: {error}"
                log_line(f"REFRESH error reason={reason} {self.last_error}")
                return self.status("error")

    def status(self, mode: str = "status") -> dict[str, Any]:
        return {
            "ok": not self.last_error,
            "mode": mode,
            "lastAttempt": self.last_attempt,
            "lastSuccess": self.last_success,
            "lastError": self.last_error,
            "liveFeedExists": self.live.OUT.exists(),
        }


def make_handler(refresher: LiveFeedRefresher):
    class RefreshingHandler(SimpleHTTPRequestHandler):
        server_version = "WorldCupPredictor/1.0"

        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, directory=str(OUTPUTS), **kwargs)

        def end_headers(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.endswith((".json", ".html")) or parsed.path.startswith("/api/"):
                self.send_header("Cache-Control", "no-store, max-age=0")
            super().end_headers()

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = urllib.parse.parse_qs(parsed.query)
            if path == "/api/refresh-live":
                status = refresher.refresh(force=query.get("force", ["0"])[0] == "1", reason="api")
                self.send_json(status)
                return
            if path in ("", "/", "/worldcup-predictions.html"):
                threading.Thread(
                    target=refresher.refresh,
                    kwargs={"force": True, "reason": "open-page"},
                    daemon=True,
                ).start()
            elif path.endswith("/live-feed.json") or path == "/live-feed.json":
                if query.get("cached", ["0"])[0] != "1":
                    force = query.get("force", ["0"])[0] == "1"
                    refresher.refresh(force=force, reason="live-feed-json")
            super().do_GET()

        def send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib API.
            log_line(f"HTTP {self.address_string()} {format % args}")

        def handle(self) -> None:
            try:
                super().handle()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                log_line("HTTP client disconnected before response finished")

    return RefreshingHandler


def start_background_refresh(refresher: LiveFeedRefresher, interval: int) -> None:
    if interval <= 0:
        return

    def loop() -> None:
        while True:
            refresher.refresh(force=False, reason="background")
            time.sleep(max(interval, 5))

    thread = threading.Thread(target=loop, name="live-feed-background-refresh", daemon=True)
    thread.start()


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        host_name = socket.gethostname()
        for item in socket.getaddrinfo(host_name, None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass
    return sorted(addresses)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--min-refresh-seconds", type=int, default=12)
    parser.add_argument("--background-interval", type=int, default=15)
    args = parser.parse_args()

    refresher = LiveFeedRefresher(min_interval=args.min_refresh_seconds)
    start_background_refresh(refresher, args.background_interval)
    handler = make_handler(refresher)
    server = ThreadingHTTPServer((args.bind, args.port), handler)
    log_line(f"SERVER start http://{args.bind}:{args.port}/worldcup-predictions.html")
    print(f"ready local: http://127.0.0.1:{args.port}/worldcup-predictions.html", flush=True)
    for ip in local_ipv4_addresses():
        print(f"ready phone: http://{ip}:{args.port}/worldcup-predictions.html", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
