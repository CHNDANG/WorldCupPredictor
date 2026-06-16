"""
Example live-feed bridge for worldcup-predictions.html.

Replace fetch_live_state() with a real provider:
- API-FOOTBALL fixtures/events endpoint
- Sofascore live incidents endpoint
- Opta/StatsBomb/Wyscout event feed
- Odds API / bookmaker stream for marketMove

The website polls outputs/live-feed.json every 15 seconds.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(r"C:\Users\Administrator\Documents\Codex\2026-06-14\new-chat\outputs\live-feed.json")


def fetch_live_state() -> dict:
    # TODO: Replace this demo state with provider data.
    return {
        "id": "esp-cpv",
        "status": "live",
        "minute": 12,
        "homeGoals": 1,
        "awayGoals": 0,
        "homeXg": 0.85,
        "awayXg": 0.15,
        "homeRedCards": 0,
        "awayRedCards": 0,
        "tempo": 10,
        "marketMove": 10,
        "note": "Provider update: goal/xG/market move synced.",
    }


def write_feed(match_state: dict, provider: str = "provider-bridge") -> None:
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "matches": [match_state],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    while True:
      write_feed(fetch_live_state())
      time.sleep(15)


if __name__ == "__main__":
    main()
