"""
Seed current pre-match predictions into the learning database.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import learning_store


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "outputs" / "worldcup-predictions.html"


def extract_object_array(text: str, name: str) -> str:
    start = text.find(f"const {name} = [")
    if start < 0:
        return ""
    start = text.find("[", start)
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return ""


def prediction_from_lambdas(lambda_a: float, lambda_b: float) -> tuple[str, str, float]:
    rows = []
    for home in range(6):
        for away in range(6):
            probability = (
                math.exp(-lambda_a)
                * (lambda_a ** home)
                / math.factorial(home)
                * math.exp(-lambda_b)
                * (lambda_b ** away)
                / math.factorial(away)
            )
            rows.append((probability, home, away))
    rows.sort(reverse=True)
    best = rows[0]
    alt = " / ".join(f"{home}-{away}" for _, home, away in rows[1:3])
    return f"{best[1]}-{best[2]}", alt, round(max(50, min(76, 52 + abs(lambda_a - lambda_b) * 12)), 1)


def iter_object_chunks(block: str):
    index = 0
    while index < len(block):
        start = block.find("{", index)
        if start < 0:
            break
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(block)):
            char = block[end]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield block[start : end + 1]
                    index = end + 1
                    break
        else:
            break


def parse_items(block: str) -> list[dict]:
    items = []
    for body in iter_object_chunks(block):
        found_id = re.search(r"id:\s*\"([^\"]+)\"", body)
        if not found_id:
            continue
        item = {"id": found_id.group(1)}
        for key in ["teamA", "teamB", "score", "alt", "market", "sentiment", "reason"]:
            found = re.search(rf"{key}:\s*\"([^\"]*)\"", body)
            if found:
                item[key] = found.group(1)
        for key in ["confidence", "lambdaA", "lambdaB"]:
            found = re.search(rf"{key}:\s*([0-9.]+)", body)
            if found:
                item[key] = float(found.group(1))
        if "score" not in item and "lambdaA" in item and "lambdaB" in item:
            item["score"], item["alt"], item["confidence"] = prediction_from_lambdas(item["lambdaA"], item["lambdaB"])
        if "market" not in item:
            item["market"] = "自动生成赛程初始预测；等待临场盘口继续校准"
        if "sentiment" not in item:
            item["sentiment"] = "待临场确认"
        if "reason" not in item:
            item["reason"] = "后续赛程自动补齐，先用初始 λ 保存赛前预测样本。"
        items.append(item)
    return items


def extract_matches() -> list[dict]:
    text = HTML.read_text(encoding="utf-8")
    return [
        *parse_items(extract_object_array(text, "seededMatches")),
        *parse_items(extract_object_array(text, "futureFixtures")),
    ]


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
