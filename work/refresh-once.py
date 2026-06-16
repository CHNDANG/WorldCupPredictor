"""
Refresh all public data files once.

Useful for GitHub Actions, cron jobs, and quick health checks.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "work"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    live = load_module("live_feed_bridge_espn", WORK / "live-feed-bridge-espn.py")
    news = load_module("news_feed_bridge", WORK / "news-feed-bridge.py")
    learning = load_module("learning_summary", WORK / "learning-summary.py")

    live_payload = live.fetch_feed()
    live.write_feed(live_payload)

    news_payload = news.fetch_news()
    news.write_feed(news_payload)

    learning.main()

    print(json.dumps({
        "liveMatches": len(live_payload.get("matches", [])),
        "newsArticles": len(news_payload.get("articles", [])),
        "outputs": str(ROOT / "outputs"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
