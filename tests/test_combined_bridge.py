"""Bridge tests: admin ranking -> negotiation configs (no processes)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_combined import (  # noqa: E402
    admin_ranking,
    build_configs,
    demand_requirements,
    kids_open,
)


def test_admin_ranking_top3_and_filtered():
    admin = admin_ranking("azhe", 3)
    ids = [row["candidate"]["id"] for row in admin["top"]]
    assert ids == ["xiaoman", "yutong", "suqing"]
    scores = [row["score"] for row in admin["top"]]
    assert scores == sorted(scores, reverse=True)
    filtered_ids = {f["candidate"]["id"] for f in admin["filtered"]}
    assert {"yizhou", "luman"} <= filtered_ids


def test_demand_requirements_come_from_persona_facts():
    admin = admin_ranking("azhe", 3)
    reqs = demand_requirements(admin["user"])
    assert {"field": "same_city", "op": "eq", "value": True} in reqs
    assert {"field": "non_smoker", "op": "eq", "value": True} in reqs


def test_configs_withhold_kids_open_but_preload_hard_facts(tmp_path):
    admin = admin_ranking("azhe", 3)
    configs = build_configs(admin, tmp_path)
    assert len(configs) == 4
    for cfg in configs:
        assert cfg["scenario"]["id"] == "dating.match.v1"
        assert len(cfg["peers"]) == 3
    for cfg in configs[1:]:  # candidates
        facts = cfg["profile"]["facts"]
        assert facts["same_city"] is True
        assert facts["non_smoker"] is True
        assert "kids_open" not in facts  # negotiated live, not preloaded
        assert "kids_open" in cfg["profile"]["public_fields"]


def test_kids_open_derivation():
    assert kids_open({"facts": {"wants_kids": "open"}}) is True
    assert kids_open({"facts": {"wants_kids": "yes"}}) is True
    assert kids_open({"facts": {"wants_kids": "no"}}) is False


def test_generated_config_files_are_valid_json(tmp_path):
    admin = admin_ranking("azhe", 3)
    build_configs(admin, tmp_path)
    for n in range(1, 5):
        cfg = json.loads((tmp_path / f"agent-{n}.json").read_text())
        assert cfg["agent_id"] == f"agent-{n}"
