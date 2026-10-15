#!/usr/bin/env python3
"""Evaluate a distilled profile against the hand-written reference profile.

Default: analyze the captured live run in examples/azhe_live_profile.json
(offline, no API key needed). With --live, re-distill from the raw material
first (requires LLM_BASE_URL / LLM_API_KEY / LLM_MODEL, see core/distill.py).

The eval answers three questions:
  1. Hard facts — did extraction get the gate-critical fields right?
  2. Coverage  — how much of the reference needs/offers did it recover?
  3. Consequence — if this profile enters the pool, who wins? Does the
     hand-written ranking survive a different "reading" of the same person?

Usage:
    python3 scripts/eval_distillation.py [--live]
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.match import rank_pool  # noqa: E402

HARD_FACTS = ("city", "wants_kids", "smoker", "require_same_city", "dealbreaker_smoking")


def fact_of(profile, key):
    if key == "city":
        return profile.get("city")
    return profile.get("facts", {}).get(key)


def evaluate(live, reference, personas, scenario):
    print("== hard facts (gate-critical) ==")
    ok = 0
    for key in HARD_FACTS:
        got, want = fact_of(live, key), fact_of(reference, key)
        mark = "OK " if got == want else "MISS"
        ok += got == want
        print(f"  [{mark}] {key}: live={got!r} reference={want!r}")
    print(f"  -> {ok}/{len(HARD_FACTS)} correct")

    print("\n== tag coverage (vs hand-written reference) ==")
    for field in ("needs", "offers", "values"):
        ref = set(reference.get(field, []))
        got = set(live.get(field, []))
        print(f"  {field}: recovered {len(ref & got)}/{len(ref)}  live={live.get(field)}")

    print("\n== consequence: re-rank the pool with the live profile ==")
    ref_rank = rank_pool(reference, personas, scenario)
    live_rank = rank_pool(live, personas, scenario)
    print(f"  reference winner: {ref_rank[0]['candidate']['name']} ({ref_rank[0]['score']})")
    print(f"  live winner:      {live_rank[0]['candidate']['name']} ({live_rank[0]['score']})")
    for r in live_rank[:5]:
        c = r["candidate"]
        print(f"    {r['score']:.3f}  {c['name']} ({c['job']})" + ("" if r["passed"] else "  [FILTERED]"))
    if ref_rank[0]["candidate"]["id"] != live_rank[0]["candidate"]["id"]:
        print("  -> the winner changed: a distilled profile is a READING of a person,")
        print("     not ground truth. This is why profiles carry confidence scores")
        print("     and merge over time instead of being extracted once and frozen.")


def main():
    root = Path(__file__).resolve().parent.parent
    scenario = json.loads((root / "scenarios" / "dating.json").read_text())
    personas = json.loads((root / "data" / "personas.json").read_text())
    reference = next(p for p in personas if p["id"] == "azhe")

    if "--live" in sys.argv:
        from core.distill import distill

        raw = (root / "data" / "raw_logs" / "azhe.md").read_text()
        live = distill(raw, scenario, protagonist_id="azhe")
        print("(re-distilled live from data/raw_logs/azhe.md)\n")
    else:
        live = json.loads((root / "examples" / "azhe_live_profile.json").read_text())
        print("(analyzing captured live run: examples/azhe_live_profile.json)\n")

    evaluate(live, reference, personas, scenario)


if __name__ == "__main__":
    main()
