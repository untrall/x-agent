#!/usr/bin/env python3
"""Precompute everything the demo front-end needs.

Runs the real matching engine over data/personas.json and emits
demo/demo_data.json: protagonist card, pool layout, both rankings
(default + after the scripted feedback), and the demo's Q&A beats.

    python scripts/build_demo_data.py
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.match import apply_feedback, rank_pool  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROTAGONIST_ID = "azhe"
FEEDBACK = {
    "text": "她太安静了，我希望对方外向一点。",
    "trait_min": {"extroversion": 0.55},
    "penalty": 0.45,
    "note": "反馈没有重掷骰子——它把「外向程度」变成了一道门槛偏好，门槛以下的候选人被显式降权。",
}

# The two questions X-Agent asks live on stage (phase 2 of the demo).
QA_BEATS = [
    {
        "q": "如果吵架了，你希望怎么处理？",
        "a": "别冷战，有事当天聊开——我最怕猜来猜去。",
        "updates": [
            {"label": "表达欲（新证据并入）", "from": 0.30, "to": 0.36},
            {"label": "「深度交流」置信度", "from": 0.86, "to": 0.93},
        ],
    },
    {
        "q": "理想的周末是什么样？",
        "a": "睡到自然醒，一起买菜做饭，晚上看一部科幻片。",
        "updates": [
            {"label": "居家倾向（新证据并入）", "from": 0.60, "to": 0.67},
        ],
    },
]

SOURCES = [
    {"name": "日常助手 Agent", "desc": "生活记忆 · 作息、习惯、朋友评价"},
    {"name": "工作 Agent", "desc": "职业记忆 · 目标感、计划性、财务自律"},
    {"name": "情感咨询 Agent", "desc": "自述 · 想要的关系、分手复盘"},
]


def main():
    scenario = json.loads((ROOT / "scenarios/dating.json").read_text(encoding="utf-8"))
    personas = json.loads((ROOT / "data/personas.json").read_text(encoding="utf-8"))
    hero = next(p for p in personas if p["id"] == PROTAGONIST_ID)

    default_ranking = rank_pool(hero, personas, scenario)
    feedback_ranking = apply_feedback(
        default_ranking, FEEDBACK["trait_min"], FEEDBACK["penalty"]
    )

    rng = random.Random(42)
    pool_layout = []
    for i, p in enumerate(personas):
        if p["id"] == PROTAGONIST_ID:
            continue
        ang = (i / max(1, len(personas) - 1)) * 6.283 + rng.uniform(-0.2, 0.2)
        rad = rng.uniform(0.30, 0.44)
        px = min(0.94, max(0.06, 0.5 + rad * __import__("math").cos(ang)))
        py = min(0.92, max(0.10, 0.52 + rad * 0.78 * __import__("math").sin(ang)))
        pool_layout.append(
            {
                "id": p["id"],
                "name": p["name"],
                "x": round(px, 3),
                "y": round(py, 3),
                "z": round(rng.uniform(0.35, 1.0), 2),
            }
        )

    axes = [
        {"key": a["key"], "label": a["label"], "mode": a["mode"]}
        for a in scenario["trait_axes"]
    ]
    data = {
        "scenario": scenario["scenario"],
        "protagonist": {
            k: hero[k]
            for k in (
                "id", "name", "age", "city", "job", "essence",
                "values", "needs", "offers", "interests",
            )
        },
        "protagonist_traits": hero["traits"],
        "axes": axes,
        "sources": SOURCES,
        "qa_beats": QA_BEATS,
        "pool": pool_layout,
        "rankings": {"default": default_ranking, "after_feedback": feedback_ranking},
        "feedback": FEEDBACK,
    }
    out = ROOT / "demo/demo_data.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"wrote {out}")
    for title, ranking in (("default", default_ranking), ("after feedback", feedback_ranking)):
        print(f"\n[{title}]")
        for r in ranking:
            c = r["candidate"]
            flag = "" if r["passed"] else "  [FILTERED]"
            dem = "  [demoted by feedback]" if r.get("demoted_by_feedback") else ""
            print(f"  {r['score']:.3f}  {c['name']} ({c['job']}){flag}{dem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
