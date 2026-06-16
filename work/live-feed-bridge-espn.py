"""
ESPN live-feed bridge for outputs/worldcup-predictions.html.

Writes structured live score, match stats, odds snapshots, event stream, and
short rolling history into outputs/live-feed.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import learning_store


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "live-feed.json"
LOG = ROOT / "work" / "live-feed-bridge-espn.log"
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={event_id}"
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds"
ODDS_API_KEY_ENV = "THE_ODDS_API_KEY"

EVENT_MAP = {
    "760428": "esp-cpv",
    "760426": "bel-egy",
    "760429": "ksa-uru",
    "760427": "irn-nzl",
    "760432": "fra-sen",
    "760430": "irq-nor",
    "760433": "arg-alg",
    "760431": "aut-jor",
    "760435": "por-cod",
}

TEAM_ALIAS = {
    "esp-cpv": ("spain", "cape verde"),
    "bel-egy": ("belgium", "egypt"),
    "ksa-uru": ("saudi arabia", "uruguay"),
    "irn-nzl": ("iran", "new zealand"),
    "fra-sen": ("france", "senegal"),
    "irq-nor": ("iraq", "norway"),
    "arg-alg": ("argentina", "algeria"),
    "aut-jor": ("austria", "jordan"),
    "por-cod": ("portugal", "congo dr"),
}

SCOREBOARD_DATES = ["20260616", "20260617", "20260618"]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 live-feed-bridge/2.0",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_json_list(url: str) -> list[dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 live-feed-bridge/2.0",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_minute(status: dict[str, Any]) -> int:
    candidates = [
        status.get("displayClock"),
        status.get("type", {}).get("detail"),
        status.get("type", {}).get("shortDetail"),
        status.get("type", {}).get("statusPrimary"),
    ]
    for value in candidates:
        match = re.search(r"(\d+)", str(value or ""))
        if match:
            return int(match.group(1))
    return 0


def competitor(competition: dict[str, Any], home_away: str) -> dict[str, Any]:
    for item in competition.get("competitors", []):
        if item.get("homeAway") == home_away:
            return item
    return {}


def stat_map(summary: dict[str, Any], home_away: str) -> dict[str, float]:
    for team in summary.get("boxscore", {}).get("teams", []):
        if team.get("homeAway") == home_away:
            stats: dict[str, float] = {}
            for stat in team.get("statistics", []):
                raw = str(stat.get("displayValue", "0")).replace("%", "")
                try:
                    stats[stat.get("name", "")] = float(raw)
                except ValueError:
                    stats[stat.get("name", "")] = 0.0
            return stats
    return {}


def compact_stats(stats: dict[str, float]) -> dict[str, float]:
    return {
        "shots": stats.get("totalShots", 0.0),
        "shotsOnTarget": stats.get("shotsOnTarget", 0.0),
        "corners": stats.get("wonCorners", 0.0),
        "possession": stats.get("possessionPct", 0.0),
        "passes": stats.get("totalPasses", 0.0),
        "redCards": stats.get("redCards", 0.0),
    }


def xg_proxy(stats: dict[str, float]) -> float:
    shots = stats.get("totalShots", 0.0)
    on_target = stats.get("shotsOnTarget", 0.0)
    corners = stats.get("wonCorners", 0.0)
    penalties = stats.get("penaltyKickShots", 0.0)
    blocked = stats.get("blockedShots", 0.0)
    return round(clamp(shots * 0.08 + on_target * 0.18 + corners * 0.035 + blocked * 0.04 + penalties * 0.45, 0, 8), 2)


def tempo_proxy(minute: int, home_stats: dict[str, float], away_stats: dict[str, float]) -> int:
    if minute <= 0:
        return 0
    attacks = (
        home_stats.get("totalShots", 0.0)
        + away_stats.get("totalShots", 0.0)
        + 0.7 * (home_stats.get("wonCorners", 0.0) + away_stats.get("wonCorners", 0.0))
    )
    shots_per_90 = attacks / max(minute, 1) * 90
    return int(round(clamp((shots_per_90 - 22) * 1.25, -30, 40)))


def american_probability(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).replace("+", "").strip()
    if not text:
        return None
    try:
        odds = float(text)
    except ValueError:
        return None
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def decimal_to_american(raw: Any) -> str | None:
    if raw is None:
        return None
    try:
        decimal = float(raw)
    except (TypeError, ValueError):
        return None
    if decimal <= 1:
        return None
    if decimal >= 2:
        return f"+{round((decimal - 1) * 100):.0f}"
    return f"{round(-100 / (decimal - 1)):.0f}"


def odds_snapshot(summary: dict[str, Any]) -> dict[str, Any]:
    odds_list = summary.get("odds") or []
    if not odds_list:
        return {}
    market = next(
        (
            item
            for item in odds_list
            if item.get("moneyline", {}).get("home", {}).get("live")
            or "Live" in item.get("provider", {}).get("name", "")
        ),
        odds_list[0],
    )
    moneyline = market.get("moneyline", {})
    spread = market.get("pointSpread", {})
    total = market.get("total", {})
    return {
        "provider": market.get("provider", {}).get("name", "odds"),
        "homeMoneyline": moneyline.get("home", {}).get("live", {}).get("odds")
        or moneyline.get("home", {}).get("close", {}).get("odds"),
        "drawMoneyline": moneyline.get("draw", {}).get("live", {}).get("odds")
        or moneyline.get("draw", {}).get("close", {}).get("odds"),
        "awayMoneyline": moneyline.get("away", {}).get("live", {}).get("odds")
        or moneyline.get("away", {}).get("close", {}).get("odds"),
        "homeOpenMoneyline": moneyline.get("home", {}).get("open", {}).get("odds"),
        "spreadLine": spread.get("home", {}).get("live", {}).get("line")
        or spread.get("home", {}).get("close", {}).get("line"),
        "spreadOdds": spread.get("home", {}).get("live", {}).get("odds")
        or spread.get("home", {}).get("close", {}).get("odds"),
        "totalLine": total.get("over", {}).get("live", {}).get("line")
        or total.get("over", {}).get("close", {}).get("line"),
        "overOdds": total.get("over", {}).get("live", {}).get("odds")
        or total.get("over", {}).get("close", {}).get("odds"),
        "underOdds": total.get("under", {}).get("live", {}).get("odds")
        or total.get("under", {}).get("close", {}).get("odds"),
    }


def bookmaker_snapshots(summary: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots = []
    for market in summary.get("odds") or []:
        moneyline = market.get("moneyline", {})
        spread = market.get("pointSpread", {})
        total = market.get("total", {})
        home_ml = (
            moneyline.get("home", {}).get("live", {}).get("odds")
            or moneyline.get("home", {}).get("close", {}).get("odds")
            or market.get("homeTeamOdds", {}).get("moneyLine")
        )
        draw_ml = (
            moneyline.get("draw", {}).get("live", {}).get("odds")
            or moneyline.get("draw", {}).get("close", {}).get("odds")
            or market.get("drawOdds", {}).get("moneyLine")
        )
        away_ml = (
            moneyline.get("away", {}).get("live", {}).get("odds")
            or moneyline.get("away", {}).get("close", {}).get("odds")
            or market.get("awayTeamOdds", {}).get("moneyLine")
        )
        spread_line = (
            spread.get("home", {}).get("live", {}).get("line")
            or spread.get("home", {}).get("close", {}).get("line")
            or market.get("details")
        )
        total_line = (
            total.get("over", {}).get("live", {}).get("line")
            or total.get("over", {}).get("close", {}).get("line")
            or market.get("overUnder")
        )
        provider = market.get("provider", {}).get("name", "Unknown")
        snapshots.append(
            {
                "provider": provider,
                "scope": "live" if "Live" in provider or moneyline.get("home", {}).get("live") else "pregame",
                "homeMoneyline": str(home_ml) if home_ml is not None else None,
                "drawMoneyline": str(draw_ml) if draw_ml is not None else None,
                "awayMoneyline": str(away_ml) if away_ml is not None else None,
                "spreadLine": str(spread_line) if spread_line is not None else None,
                "spreadOdds": spread.get("home", {}).get("live", {}).get("odds") or spread.get("home", {}).get("close", {}).get("odds"),
                "totalLine": str(total_line) if total_line is not None else None,
                "overOdds": total.get("over", {}).get("live", {}).get("odds") or total.get("over", {}).get("close", {}).get("odds"),
                "underOdds": total.get("under", {}).get("live", {}).get("odds") or total.get("under", {}).get("close", {}).get("odds"),
                "homeImplied": american_probability(home_ml),
                "drawImplied": american_probability(draw_ml),
                "awayImplied": american_probability(away_ml),
                "available": home_ml is not None or draw_ml is not None or away_ml is not None,
            }
        )
    preferred = {item["provider"] for item in snapshots}
    for provider in ["Pinnacle", "Bet365", "FanDuel", "BetMGM", "Caesars", "William Hill"]:
        if provider not in preferred:
            snapshots.append(
                {
                    "provider": provider,
                    "scope": "api-pending",
                    "homeMoneyline": None,
                    "drawMoneyline": None,
                    "awayMoneyline": None,
                    "spreadLine": None,
                    "spreadOdds": None,
                    "totalLine": None,
                    "overOdds": None,
                    "underOdds": None,
                    "homeImplied": None,
                    "drawImplied": None,
                    "awayImplied": None,
                    "available": False,
                }
            )
    return snapshots


def odds_api_events() -> list[dict[str, Any]]:
    api_key = os.environ.get(ODDS_API_KEY_ENV)
    if not api_key:
        return []
    query = urllib.parse.urlencode(
        {
            "apiKey": api_key,
            "regions": "us,uk,eu",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
        }
    )
    try:
        return fetch_json_list(f"{ODDS_API_URL}?{query}")
    except Exception as error:
        log_line(f"ODDS_API_ERROR {type(error).__name__}: {error}")
        return []


def find_odds_api_event(local_id: str, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    home_alias, away_alias = TEAM_ALIAS.get(local_id, ("", ""))
    for event in events:
        home = str(event.get("home_team", "")).lower()
        away = str(event.get("away_team", "")).lower()
        teams = f"{home} {away}"
        if home_alias in teams and away_alias in teams:
            return event
    return None


def odds_api_bookmakers(local_id: str, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    event = find_odds_api_event(local_id, events)
    if not event:
        return []
    home_name = event.get("home_team")
    away_name = event.get("away_team")
    snapshots = []
    for bookmaker in event.get("bookmakers", []):
        markets = {market.get("key"): market for market in bookmaker.get("markets", [])}
        h2h = markets.get("h2h", {})
        spread = markets.get("spreads", {})
        total = markets.get("totals", {})
        home_ml = draw_ml = away_ml = None
        for outcome in h2h.get("outcomes", []):
            name = outcome.get("name")
            price = outcome.get("price")
            if name == home_name:
                home_ml = price
            elif name == away_name:
                away_ml = price
            elif str(name).lower() == "draw":
                draw_ml = price
        spread_line = spread_odds = None
        for outcome in spread.get("outcomes", []):
            if outcome.get("name") == home_name:
                spread_line = outcome.get("point")
                spread_odds = outcome.get("price")
                break
        total_line = over_odds = under_odds = None
        for outcome in total.get("outcomes", []):
            name = str(outcome.get("name", "")).lower()
            if name == "over":
                total_line = outcome.get("point")
                over_odds = outcome.get("price")
            elif name == "under":
                under_odds = outcome.get("price")
        snapshots.append(
            {
                "provider": bookmaker.get("title") or bookmaker.get("key") or "Odds API",
                "scope": "live",
                "homeMoneyline": str(home_ml) if home_ml is not None else None,
                "drawMoneyline": str(draw_ml) if draw_ml is not None else None,
                "awayMoneyline": str(away_ml) if away_ml is not None else None,
                "spreadLine": str(spread_line) if spread_line is not None else None,
                "spreadOdds": str(spread_odds) if spread_odds is not None else None,
                "totalLine": str(total_line) if total_line is not None else None,
                "overOdds": str(over_odds) if over_odds is not None else None,
                "underOdds": str(under_odds) if under_odds is not None else None,
                "homeImplied": american_probability(home_ml),
                "drawImplied": american_probability(draw_ml),
                "awayImplied": american_probability(away_ml),
                "available": home_ml is not None or draw_ml is not None or away_ml is not None,
                "source": "The Odds API",
            }
        )
    return snapshots


def merge_bookmakers(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in [*primary, *secondary]:
        provider = item.get("provider", "Unknown")
        current = merged.get(provider)
        if current is None or (not current.get("available") and item.get("available")):
            merged[provider] = item
    return list(merged.values())


def market_move_from_odds(odds: dict[str, Any]) -> int:
    open_prob = american_probability(odds.get("homeOpenMoneyline"))
    live_prob = american_probability(odds.get("homeMoneyline"))
    if open_prob is None or live_prob is None:
        return 0
    return int(round(clamp((live_prob - open_prob) * 120, -30, 30)))


def event_stream(summary: dict[str, Any]) -> list[dict[str, Any]]:
    source_events = summary.get("keyEvents") or summary.get("commentary") or []
    normalized = []
    for event in source_events[-14:]:
        play = event.get("play", event)
        clock = play.get("clock", event.get("time", {}))
        event_type = play.get("type", {}).get("type") or play.get("type", {}).get("text") or "event"
        normalized.append(
            {
                "id": str(play.get("id") or event.get("sequence") or len(normalized)),
                "minute": clock.get("displayValue") or "",
                "type": event_type,
                "team": play.get("team", {}).get("displayName", ""),
                "text": event.get("text") or play.get("text") or "",
                "scoringPlay": bool(play.get("scoringPlay", False)),
                "wallclock": play.get("wallclock") or event.get("wallclock") or "",
            }
        )
    return normalized


def build_state(event: dict[str, Any], external_odds_events: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    event_id = str(event.get("id", ""))
    local_id = EVENT_MAP.get(event_id)
    if not local_id:
        return None

    competition = (event.get("competitions") or [{}])[0]
    status = event.get("status", {})
    status_type = status.get("type", {})
    state = status_type.get("state")
    minute = parse_minute(status)
    home = competitor(competition, "home")
    away = competitor(competition, "away")

    try:
        summary = fetch_json(SUMMARY_URL.format(event_id=event_id))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        summary = {}

    home_stats = stat_map(summary, "home")
    away_stats = stat_map(summary, "away")
    odds = odds_snapshot(summary)
    espn_bookmakers = bookmaker_snapshots(summary)
    external_bookmakers = odds_api_bookmakers(local_id, external_odds_events or [])
    bookmakers = merge_bookmakers(espn_bookmakers, external_bookmakers)
    if state == "in":
        local_status = "live"
    elif state == "post":
        local_status = "ft"
    else:
        local_status = "pre"

    return {
        "id": local_id,
        "espnEventId": event_id,
        "status": local_status,
        "detail": status_type.get("detail") or status_type.get("shortDetail") or "Unknown",
        "minute": minute,
        "homeName": home.get("team", {}).get("displayName", "Home"),
        "awayName": away.get("team", {}).get("displayName", "Away"),
        "homeGoals": int(home.get("score") or 0),
        "awayGoals": int(away.get("score") or 0),
        "homeXg": xg_proxy(home_stats),
        "awayXg": xg_proxy(away_stats),
        "homeRedCards": int(home_stats.get("redCards", 0)),
        "awayRedCards": int(away_stats.get("redCards", 0)),
        "tempo": tempo_proxy(minute, home_stats, away_stats),
        "marketMove": market_move_from_odds(odds),
        "stats": {"home": compact_stats(home_stats), "away": compact_stats(away_stats)},
        "odds": odds,
        "bookmakers": bookmakers,
        "bookmakerSourceStatus": {
            "espn": len([book for book in espn_bookmakers if book.get("available")]),
            "oddsApi": len([book for book in external_bookmakers if book.get("available")]),
            "oddsApiConfigured": bool(os.environ.get(ODDS_API_KEY_ENV)),
        },
        "events": event_stream(summary),
        "note": "",
    }


def load_previous() -> dict[str, Any]:
    if not OUT.exists():
        return {}
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def attach_history(payload: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    previous_by_id = {match.get("id"): match for match in previous.get("matches", [])}
    for match in payload.get("matches", []):
        old = previous_by_id.get(match.get("id"), {})
        old_market = old.get("marketHistory", [])
        old_scores = old.get("scoreHistory", [])
        market_point = {
            "minute": match.get("minute", 0),
            "marketMove": match.get("marketMove", 0),
            "homeMoneyline": match.get("odds", {}).get("homeMoneyline"),
            "drawMoneyline": match.get("odds", {}).get("drawMoneyline"),
            "awayMoneyline": match.get("odds", {}).get("awayMoneyline"),
            "spreadLine": match.get("odds", {}).get("spreadLine"),
            "totalLine": match.get("odds", {}).get("totalLine"),
        }
        score_point = {
            "minute": match.get("minute", 0),
            "homeGoals": match.get("homeGoals", 0),
            "awayGoals": match.get("awayGoals", 0),
            "homeXg": match.get("homeXg", 0),
            "awayXg": match.get("awayXg", 0),
        }
        if not old_market or old_market[-1] != market_point:
            old_market = [*old_market, market_point][-28:]
        if not old_scores or old_scores[-1] != score_point:
            old_scores = [*old_scores, score_point][-28:]
        match["marketHistory"] = old_market
        match["scoreHistory"] = old_scores
    return payload


def fetch_feed() -> dict[str, Any]:
    scoreboards = []
    for date in SCOREBOARD_DATES:
        try:
            scoreboards.append(fetch_json(f"{SCOREBOARD_URL}?dates={date}"))
        except Exception as error:
            log_line(f"SCOREBOARD_WARN {date} {type(error).__name__}: {error}")
    if not scoreboards:
        scoreboards = [fetch_json(SCOREBOARD_URL)]
    external_odds_events = odds_api_events()
    matches = []
    seen: set[str] = set()
    for scoreboard in scoreboards:
        for event in scoreboard.get("events", []):
            event_id = str(event.get("id", ""))
            if event_id in seen:
                continue
            seen.add(event_id)
            state = build_state(event, external_odds_events)
            if state:
                matches.append(state)
    payload = {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "provider": "ESPN public scoreboard + summary",
        "source": SCOREBOARD_URL,
        "matches": matches,
    }
    previous = load_previous()
    if not matches and previous.get("matches"):
        previous["updatedAt"] = payload["updatedAt"]
        previous["provider"] = "ESPN public scoreboard + summary（当前源无比赛，保留上一份有效数据）"
        previous["source"] = SCOREBOARD_URL
        previous["sourceStatus"] = "empty-scoreboard-retained-last-valid"
        return previous
    return attach_history(payload, previous)


def write_feed(payload: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)
    learning_store.write_feed(payload)


def log_line(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp} {message}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="write one update and exit")
    parser.add_argument("--interval", type=int, default=15, help="poll interval in seconds")
    args = parser.parse_args()

    while True:
        try:
            payload = fetch_feed()
            write_feed(payload)
            message = f"{payload['updatedAt']} wrote {len(payload['matches'])} matches to {OUT}"
            print(message, flush=True)
            log_line(message)
            if args.once:
                break
        except Exception as error:
            message = f"ERROR {type(error).__name__}: {error}"
            print(message, flush=True)
            log_line(message)
            if args.once:
                raise
        time.sleep(max(args.interval, 5))


if __name__ == "__main__":
    main()
