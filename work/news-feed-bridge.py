"""
World Cup news bridge for outputs/worldcup-predictions.html.

Fetches public RSS feeds, filters World Cup related items, and writes
outputs/news-feed.json for the page to poll.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import learning_store


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "news-feed.json"
LOG = ROOT / "work" / "news-feed-bridge.log"

SOURCES = [
    {
        "name": "Google 新闻 中文",
        "url": "https://news.google.com/rss/search?q=FIFA%20World%20Cup%202026%20OR%20%E4%B8%96%E7%95%8C%E6%9D%AF%202026%20when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    },
    {
        "name": "Google News",
        "url": "https://news.google.com/rss/search?q=2026%20FIFA%20World%20Cup%20when:1d&hl=en-US&gl=US&ceid=US:en",
    },
    {
        "name": "ESPN 足球",
        "url": "https://www.espn.com/espn/rss/soccer/news",
    },
]

KEYWORDS = [
    "world cup",
    "fifa",
    "2026",
    "世界杯",
    "世俱杯",
    "spain",
    "cape verde",
    "belgium",
    "egypt",
    "uruguay",
    "iran",
    "new zealand",
]

TRANSLATION_CACHE: dict[str, str] = {}
ENABLE_ONLINE_TRANSLATE = os.environ.get("ENABLE_ONLINE_TRANSLATE") == "1"


def log_line(message: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.open("a", encoding="utf-8").write(f"{datetime.now(timezone.utc).isoformat()} {message}\n")


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml, text/xml",
            "User-Agent": "Mozilla/5.0 news-feed-bridge/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=7) as response:
        return response.read().decode("utf-8", errors="replace")


def text_of(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    if node is None or node.text is None:
        return ""
    return html.unescape(re.sub(r"<[^>]+>", "", node.text)).strip()


def parse_date(raw: str) -> str:
    if not raw:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return datetime.now(timezone.utc).isoformat()


def is_relevant(title: str, summary: str) -> bool:
    combined = f"{title} {summary}".lower()
    return any(keyword in combined for keyword in KEYWORDS)


def has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def local_translate(text: str) -> str:
    if not text:
        return ""
    rule_text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text).strip()
    exact = {
        "Red Sox host 'Scotland Day' amid World Cup": "红袜队在世界杯期间举办“苏格兰日”活动",
        "Iran team downplays protests: We aren't political": "伊朗队淡化抗议：我们不是政治团队",
        "Van Dijk criticizes World Cup hydration breaks": "范戴克批评世界杯补水暂停安排",
        "Brazil-born Nunes: 'I owe more to Portugal'": "巴西出生的努内斯：我更亏欠葡萄牙",
        "Utd's Amad scores late as Ivory Coast top Ecuador": "曼联球员阿马德终场前破门，科特迪瓦击败厄瓜多尔",
        "So close! Germany nearly got a World Cup Scorigami...": "差一点！德国险些踢出世界杯罕见比分",
        "'Finally': Norway star Erling Haaland on fulfilling World Cup dream": "终于等到：挪威球星哈兰德谈圆梦世界杯",
        "2026 World Cup updates: Spain still searching for ...": "2026年世界杯动态：西班牙仍在寻找突破口",
    }
    if rule_text in exact:
        return exact[rule_text]
    patterns = [
        (r"^(.+) host '(.+)' amid World Cup$", r"\1 在世界杯期间举办“\2”活动"),
        (r"^(.+) criticizes World Cup (.+)$", r"\1 批评世界杯\2"),
        (r"^(.+) scores late as (.+) top (.+)$", r"\1 终场前破门，\2 击败 \3"),
        (r"^(.+) on fulfilling World Cup dream$", r"\1 谈圆梦世界杯"),
        (r"^(.+) still searching for (.+)$", r"\1 仍在寻找\2"),
    ]
    for pattern, replacement in patterns:
        if re.search(pattern, rule_text):
            rule_text = re.sub(pattern, replacement, rule_text)
            break
    replacements = {
        "World Cup": "世界杯",
        "world cup": "世界杯",
        "FIFA": "国际足联",
        "2026 World Cup": "2026年世界杯",
        "World Cup updates": "世界杯动态",
        "Red Sox": "红袜",
        "Scotland Day": "苏格兰日",
        "Iran team": "伊朗队",
        "downplays protests": "淡化抗议",
        "We aren't political": "我们不是政治团队",
        "Van Dijk": "范戴克",
        "hydration breaks": "补水暂停",
        "Brazil-born": "巴西出生的",
        "Nunes": "努内斯",
        "I owe more to Portugal": "我更亏欠葡萄牙",
        "Ivory Coast": "科特迪瓦",
        "Ecuador": "厄瓜多尔",
        "Utd's": "曼联的",
        "Amad": "阿马德",
        "Egypt coach": "埃及主帅",
        "Egypt": "埃及",
        "coach": "主帅",
        "tabs": "点名",
        "Barça": "巴萨",
        "teen": "小将",
        "Salah": "萨拉赫",
        "successor": "接班人",
        " as ": " 作为 ",
        "Spain": "西班牙",
        "Cape Verde": "佛得角",
        "Cabo Verde": "佛得角",
        "Germany": "德国",
        "Norway": "挪威",
        "Erling Haaland": "埃尔林·哈兰德",
        "Haaland": "哈兰德",
        "finally": "终于",
        "Finally": "终于",
        "star": "球星",
        "dream": "梦想",
        "updates": "动态",
        "live": "实时",
        "odds": "赔率",
        "lineup": "首发",
        "injury": "伤病",
        "goal": "进球",
        "goals": "进球",
        "searching for": "仍在寻找",
        "ready": "准备好",
        "debut": "首秀",
        "nearly": "差点",
        "host": "举办",
        "amid": "期间",
        "criticizes": "批评",
        "scores late": "终场前破门",
        "top": "击败",
        "born": "出生",
        "breaking": "突发",
        "football": "足球",
        "soccer": "足球",
    }
    translated = rule_text
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated


def translate_online(text: str) -> str | None:
    if not text or has_cjk(text):
        return text
    if text in TRANSLATION_CACHE:
        return TRANSLATION_CACHE[text]
    query = urllib.parse.urlencode({"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text})
    url = f"https://translate.googleapis.com/translate_a/single?{query}"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 news-feed-bridge/1.0"})
        with urllib.request.urlopen(request, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        translated = "".join(part[0] for part in payload[0] if part and part[0]).strip()
        if translated:
            TRANSLATION_CACHE[text] = translated
            return translated
    except Exception as error:
        log_line(f"TRANSLATE_WARN {type(error).__name__}: {error}")
    return None


def zh_text(text: str) -> tuple[str, str]:
    if not text:
        return "", "empty"
    if has_cjk(text):
        return text, "source"
    if ENABLE_ONLINE_TRANSLATE:
        online = translate_online(text)
        if online and has_cjk(online):
            return online, "online"
    fallback = local_translate(text)
    return fallback, "local"


def heat_score(title: str, summary: str, source: str) -> int:
    combined = f"{title} {summary}".lower()
    score = 40
    for keyword in ["breaking", "live", "injury", "odds", "lineup", "world cup", "世界杯", "fifa"]:
        if keyword in combined:
            score += 8
    if "google" in source.lower():
        score += 4
    return max(35, min(score, 96))


def parse_feed(source: dict[str, str]) -> list[dict[str, Any]]:
    try:
        xml = fetch_text(source["url"])
        root = ET.fromstring(xml)
    except Exception as error:
        log_line(f"ERROR {source['name']} {type(error).__name__}: {error}")
        return []
    items = []
    for item in root.findall(".//item"):
        title = text_of(item, "title")
        link = text_of(item, "link")
        summary = text_of(item, "description")
        published = parse_date(text_of(item, "pubDate"))
        if not title or not link or not is_relevant(title, summary):
            continue
        title_zh, title_translation = zh_text(title)
        summary_zh, summary_translation = zh_text(summary[:220])
        items.append(
            {
                "id": re.sub(r"\W+", "-", f"{source['name']}-{title}".lower()).strip("-")[:120],
                "title": title_zh or title,
                "summary": summary_zh or summary[:220],
                "originalTitle": title,
                "originalSummary": summary[:220],
                "translation": title_translation if title_translation == summary_translation else f"{title_translation}/{summary_translation}",
                "source": source["name"],
                "url": link,
                "publishedAt": published,
                "heat": heat_score(title, summary, source["name"]),
            }
        )
    return items


def fetch_news() -> dict[str, Any]:
    seen = set()
    articles = []
    for source in SOURCES:
        for item in parse_feed(source):
            key = re.sub(r"\W+", "", item["title"].lower())[:90]
            if key in seen:
                continue
            seen.add(key)
            articles.append(item)
    articles.sort(key=lambda item: item["publishedAt"], reverse=True)
    return {
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "provider": "Google News RSS + ESPN RSS",
        "sources": [source["name"] for source in SOURCES],
        "articles": articles[:18],
    }


def write_feed(payload: dict[str, Any]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(OUT)
    try:
        learning_store.write_news(payload)
    except Exception as error:
        log_line(f"LEARNING_STORE_WARN {type(error).__name__}: {error}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    while True:
        try:
            payload = fetch_news()
            write_feed(payload)
            message = f"{payload['updatedAt']} wrote {len(payload['articles'])} articles"
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
        time.sleep(max(args.interval, 60))


if __name__ == "__main__":
    main()
