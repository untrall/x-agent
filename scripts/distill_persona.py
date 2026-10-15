#!/usr/bin/env python3
"""Distill one person's raw material into a profile.

Usage:
    export LLM_BASE_URL=https://sem.ensureok.ai/v1
    export LLM_API_KEY=<your key>
    export LLM_MODEL=<model name>
    python scripts/distill_persona.py \
        --raw data/raw_logs/azhe.md \
        --scenario scenarios/dating.json \
        --out /tmp/azhe.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.distill import distill  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    raw = Path(args.raw).read_text(encoding="utf-8")
    try:
        profile = distill(raw, scenario)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    profile.setdefault("id", Path(args.raw).stem)
    Path(args.out).write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"distilled -> {args.out}")
    print(f"  essence: {profile['essence']}")
    print(f"  needs:   {'、'.join(profile['needs'])}")
    print(f"  offers:  {'、'.join(profile['offers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
