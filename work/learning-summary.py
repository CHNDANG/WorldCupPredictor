"""
Write a lightweight learning summary JSON for the frontend.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import learning_store


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "learning-summary.json"


def main() -> None:
    summary = learning_store.summarize()
    summary["updatedAt"] = datetime.now(timezone.utc).isoformat()
    summary["storage"] = "D盘持久化数据库"
    summary["nextUse"] = [
        "用历史快照学习强队久攻不进时的总进球降温幅度",
        "用博彩公司盘口变化校准市场权重",
        "用赛后比分复盘修正球队 λ 和比分区间",
        "长期积累球队、球员、教练、新闻情绪与赛中事件特征",
    ]
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
