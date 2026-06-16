"""
Cloud runner for the World Cup predictor.

Runs the static website and refreshes live scores, news, and learning summary
inside one long-lived process. Intended for a VPS, Docker container, or any
always-on machine. Local Windows users can keep using start-site.ps1.
"""

from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import socketserver
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
WORK = ROOT / "work"
STATUS_FILE = OUTPUTS / "api" / "status.json"
STATUS_LOCK = threading.Lock()
STATUS: dict[str, object] = {
    "startedAt": datetime.now(timezone.utc).isoformat(),
    "live": {"ok": False},
    "news": {"ok": False},
    "learning": {"ok": False},
}


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


live_bridge = load_module("live_feed_bridge_espn", WORK / "live-feed-bridge-espn.py")
news_bridge = load_module("news_feed_bridge", WORK / "news-feed-bridge.py")
learning_summary = load_module("learning_summary", WORK / "learning-summary.py")


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(message: str) -> None:
    print(f"{stamp()} {message}", flush=True)


def write_status(section: str, values: dict[str, object]) -> None:
    with STATUS_LOCK:
        STATUS[section] = {
            **dict(STATUS.get(section, {})),
            **values,
            "updatedAt": stamp(),
        }
        STATUS["updatedAt"] = stamp()
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = STATUS_FILE.with_suffix(".json.tmp")
        temp.write_text(json.dumps(STATUS, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(STATUS_FILE)


def run_loop(name: str, interval: int, job: Callable[[], None]) -> None:
    while True:
        started = time.monotonic()
        try:
            result = job()
            if isinstance(result, dict):
                write_status(name, {"ok": True, **result})
            else:
                write_status(name, {"ok": True})
            log(f"{name} OK")
        except Exception as error:  # keep the cloud process alive
            write_status(name, {"ok": False, "error": f"{type(error).__name__}: {error}"})
            log(f"{name} ERROR {type(error).__name__}: {error}")
        elapsed = time.monotonic() - started
        time.sleep(max(3, interval - elapsed))


def update_live_once() -> dict[str, object]:
    payload = live_bridge.fetch_feed()
    live_bridge.write_feed(payload)
    matches = len(payload.get("matches", []))
    log(f"live wrote {matches} matches")
    return {
        "matches": matches,
        "provider": payload.get("provider"),
        "sourceStatus": payload.get("sourceStatus", "ok"),
    }


def update_news_once() -> dict[str, object]:
    feed = news_bridge.fetch_news()
    news_bridge.write_feed(feed)
    articles = len(feed.get("articles", []))
    log(f"news wrote {articles} articles")
    return {"articles": articles, "provider": feed.get("provider")}


def update_learning_once() -> dict[str, object]:
    learning_summary.main()
    return {"summary": "updated"}


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/healthz", "/api/healthz"}:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "updatedAt": stamp()}, ensure_ascii=False).encode("utf-8"))
            return
        super().do_GET()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        log(f"http {self.address_string()} {format % args}")


def serve(port: int) -> None:
    socketserver.TCPServer.allow_reuse_address = True
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(OUTPUTS), **kwargs)
    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        log(f"site serving http://0.0.0.0:{port}")
        httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4173)
    parser.add_argument("--live-interval", type=int, default=15)
    parser.add_argument("--news-interval", type=int, default=300)
    parser.add_argument("--learning-interval", type=int, default=60)
    parser.add_argument("--no-server", action="store_true")
    args = parser.parse_args()

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    threads = [
        threading.Thread(target=run_loop, args=("live", args.live_interval, update_live_once), daemon=True),
        threading.Thread(target=run_loop, args=("news", args.news_interval, update_news_once), daemon=True),
        threading.Thread(target=run_loop, args=("learning", args.learning_interval, update_learning_once), daemon=True),
    ]
    if not args.no_server:
        threads.append(threading.Thread(target=serve, args=(args.port,), daemon=True))

    for thread in threads:
        thread.start()

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log("shutdown requested")


if __name__ == "__main__":
    main()
