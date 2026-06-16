"""
Seed current pre-match predictions into the learning database.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import learning_store


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "worldcup-predictions.html"


def extract_matches() -> list[dict]:
    text = HTML.read_text(encoding="utf-8")
    block = re.search(r"const matches = \[(.*?)\];", text, re.S)
    if not block:
        return []
    items = []
    for chunk in re.finditer(r"\{\s*id:\s*\"([^\"]+)\"(.*?)\n\s*\}", block.group(1), re.S):
        body = chunk.group(0)
        item = {"id": chunk.group(1)}
        for key in ["teamA", "teamB", "score", "alt", "market", "sentiment", "reason"]:
            found = re.search(rf"{key}:\s*\"([^\"]*)\"", body)
            if found:
                item[key] = found.group(1)
        for key in ["confidence", "lambdaA", "lambdaB"]:
            found = re.search(rf"{key}:\s*([0-9.]+)", body)
            if found:
                item[key] = float(found.group(1))
        items.append(item)
    return items


def main() -> None:
    learning_store.init_db()
    created_at = datetime.now(timezone.utc).isoformat()
    matches = extract_matches()
    with learning_store.connect() as conn:
        for match in matches:
            conn.execute(
                """
                INSERT INTO matches(id, home_team, away_team, status, created_at, updated_at)
                VALUES(?, ?, ?, 'pre', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  home_team=COALESCE(matches.home_team, excluded.home_team),
                  away_team=COALESCE(matches.away_team, excluded.away_team),
                  updated_at=excluded.updated_at
                """,
                (match["id"], match.get("teamA"), match.get("teamB"), created_at, created_at),
            )
            conn.execute(
                """
                INSERT INTO predictions(match_id, created_at, phase, predicted_score, probability, confidence, model_version, features_json)
                VALUES(?, ?, 'pre', ?, NULL, ?, 'site-pre-v1', ?)
                """,
                (
                    match["id"],
                    created_at,
                    match.get("score"),
                    match.get("confidence"),
                    json.dumps(match, ensure_ascii=False),
                ),
            )
    print(json.dumps({"seeded": len(matches), **learning_store.summarize()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
