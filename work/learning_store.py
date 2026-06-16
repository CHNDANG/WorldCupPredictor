"""
Persistent learning store for the World Cup predictor.

The database lives under D:/WorldCupPredictor/data so live snapshots, odds,
news, predictions, and future calibration records do not grow on C:.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "football_learning.sqlite3"


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS matches (
  id TEXT PRIMARY KEY,
  espn_event_id TEXT,
  home_team TEXT,
  away_team TEXT,
  status TEXT,
  kickoff_utc TEXT,
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS live_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  minute INTEGER,
  home_goals INTEGER,
  away_goals INTEGER,
  home_xg REAL,
  away_xg REAL,
  home_red_cards INTEGER,
  away_red_cards INTEGER,
  tempo INTEGER,
  market_move INTEGER,
  detail TEXT,
  payload_json TEXT
);

CREATE TABLE IF NOT EXISTS bookmaker_odds (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  provider TEXT,
  scope TEXT,
  home_moneyline TEXT,
  draw_moneyline TEXT,
  away_moneyline TEXT,
  spread_line TEXT,
  total_line TEXT,
  available INTEGER,
  payload_json TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  match_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  phase TEXT,
  predicted_score TEXT,
  probability REAL,
  confidence REAL,
  model_version TEXT,
  features_json TEXT
);

CREATE TABLE IF NOT EXISTS match_results (
  match_id TEXT PRIMARY KEY,
  finished_at TEXT,
  home_goals INTEGER,
  away_goals INTEGER,
  result_json TEXT,
  review_json TEXT
);

CREATE TABLE IF NOT EXISTS news_articles (
  id TEXT PRIMARY KEY,
  captured_at TEXT NOT NULL,
  title TEXT,
  original_title TEXT,
  source TEXT,
  published_at TEXT,
  heat INTEGER,
  url TEXT,
  payload_json TEXT
);

CREATE TABLE IF NOT EXISTS entities (
  id TEXT PRIMARY KEY,
  type TEXT,
  name TEXT,
  country TEXT,
  features_json TEXT,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_match_time ON live_snapshots(match_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_odds_match_time ON bookmaker_odds(match_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_predictions_match_time ON predictions(match_id, created_at);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def write_feed(feed: dict[str, Any]) -> None:
    init_db()
    captured_at = feed.get("updatedAt") or now_utc()
    with connect() as conn:
        for match in feed.get("matches", []):
            match_id = match.get("id")
            if not match_id:
                continue
            conn.execute(
                """
                INSERT INTO matches(id, espn_event_id, home_team, away_team, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  espn_event_id=excluded.espn_event_id,
                  home_team=excluded.home_team,
                  away_team=excluded.away_team,
                  status=excluded.status,
                  updated_at=excluded.updated_at
                """,
                (
                    match_id,
                    match.get("espnEventId"),
                    match.get("homeName"),
                    match.get("awayName"),
                    match.get("status"),
                    captured_at,
                    captured_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO live_snapshots(
                  match_id, captured_at, minute, home_goals, away_goals, home_xg, away_xg,
                  home_red_cards, away_red_cards, tempo, market_move, detail, payload_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    match_id,
                    captured_at,
                    match.get("minute"),
                    match.get("homeGoals"),
                    match.get("awayGoals"),
                    match.get("homeXg"),
                    match.get("awayXg"),
                    match.get("homeRedCards"),
                    match.get("awayRedCards"),
                    match.get("tempo"),
                    match.get("marketMove"),
                    match.get("detail"),
                    json.dumps(match, ensure_ascii=False),
                ),
            )
            for book in match.get("bookmakers", []):
                if not book.get("available"):
                    continue
                conn.execute(
                    """
                    INSERT INTO bookmaker_odds(
                      match_id, captured_at, provider, scope, home_moneyline, draw_moneyline,
                      away_moneyline, spread_line, total_line, available, payload_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match_id,
                        captured_at,
                        book.get("provider"),
                        book.get("scope"),
                        book.get("homeMoneyline"),
                        book.get("drawMoneyline"),
                        book.get("awayMoneyline"),
                        book.get("spreadLine"),
                        book.get("totalLine"),
                        int(bool(book.get("available"))),
                        json.dumps(book, ensure_ascii=False),
                    ),
                )


def write_news(feed: dict[str, Any]) -> None:
    init_db()
    captured_at = feed.get("updatedAt") or now_utc()
    with connect() as conn:
        for article in feed.get("articles", []):
            article_id = article.get("id")
            if not article_id:
                continue
            conn.execute(
                """
                INSERT INTO news_articles(id, captured_at, title, original_title, source, published_at, heat, url, payload_json)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  captured_at=excluded.captured_at,
                  title=excluded.title,
                  original_title=excluded.original_title,
                  source=excluded.source,
                  published_at=excluded.published_at,
                  heat=excluded.heat,
                  url=excluded.url,
                  payload_json=excluded.payload_json
                """,
                (
                    article_id,
                    captured_at,
                    article.get("title"),
                    article.get("originalTitle"),
                    article.get("source"),
                    article.get("publishedAt"),
                    article.get("heat"),
                    article.get("url"),
                    json.dumps(article, ensure_ascii=False),
                ),
            )


def summarize() -> dict[str, Any]:
    init_db()
    with connect() as conn:
        return {
            "database": str(DB_PATH),
            "matches": conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0],
            "liveSnapshots": conn.execute("SELECT COUNT(*) FROM live_snapshots").fetchone()[0],
            "bookmakerOdds": conn.execute("SELECT COUNT(*) FROM bookmaker_odds").fetchone()[0],
            "predictions": conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0],
            "newsArticles": conn.execute("SELECT COUNT(*) FROM news_articles").fetchone()[0],
        }


if __name__ == "__main__":
    init_db()
    print(json.dumps(summarize(), ensure_ascii=False, indent=2))
