"""Scenario schema validation and deterministic hard constraints."""

from __future__ import annotations

import re
from copy import deepcopy


_OPS = {
    "boolean": {"eq"},
    "number": {"eq", "gte", "lte"},
    "string": {"eq", "contains"},
}


def validate_scenario(value: dict) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise ValueError("scenario requires id")
    fields = value.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("scenario requires fields")
    for name, spec in fields.items():
        if not isinstance(name, str) or not isinstance(spec, dict) or spec.get("type") not in _OPS:
            raise ValueError(f"invalid scenario field {name!r}")
        if "pattern" in spec:
            re.compile(spec["pattern"])
    scenario = deepcopy(value)
    scenario.setdefault("initial_requirements", [])
    scenario.setdefault("result_title", scenario.get("name", scenario["id"]))
    for requirement in scenario["initial_requirements"]:
        validate_requirement(requirement, scenario)
    followup = scenario.get("followup")
    if followup is not None and followup.get("field") not in fields:
        raise ValueError("followup field is not in scenario")
    return scenario


def validate_requirement(value: dict, scenario: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {"field", "op", "value"}:
        raise ValueError("requirement needs field, op and value")
    field = value["field"]
    spec = scenario["fields"].get(field)
    if spec is None:
        raise ValueError(f"unknown field {field!r}")
    op = value["op"]
    kind = spec["type"]
    if op not in _OPS[kind]:
        raise ValueError(f"operator {op!r} is invalid for {kind}")
    expected = value["value"]
    if kind == "boolean" and type(expected) is not bool:
        raise ValueError(f"{field} value must be boolean")
    if kind == "number" and (type(expected) not in (int, float) or isinstance(expected, bool)):
        raise ValueError(f"{field} value must be number")
    if kind == "string" and not isinstance(expected, str):
        raise ValueError(f"{field} value must be string")
    return deepcopy(value)


def coerce_fact(field: str, value: object, scenario: dict) -> object:
    kind = scenario["fields"][field]["type"]
    if kind == "boolean":
        if type(value) is bool:
            return value
        if isinstance(value, str):
            normalized = value.strip().casefold()
            if normalized in {"yes", "true", "1", "是", "有", "可以", "需要"}:
                return True
            if normalized in {"no", "false", "0", "否", "没有", "不可以", "不需要"}:
                return False
        raise ValueError(f"{field} answer must be yes/no")
    if kind == "number":
        if type(value) in (int, float):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise ValueError(f"{field} answer must be a number")
    if kind == "string":
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise ValueError(f"{field} answer must be text")
    raise ValueError(f"unknown field {field}")


def evaluate_requirements(requirements: list[dict], facts: dict, scenario: dict) -> dict:
    reasons = []
    unknown_fields = []
    for requirement in requirements:
        item = validate_requirement(requirement, scenario)
        field, op, expected = item["field"], item["op"], item["value"]
        if field not in facts or facts[field] is None:
            reasons.append({"field": field, "status": "UNKNOWN", "reason": "fact is unknown"})
            if field not in unknown_fields:
                unknown_fields.append(field)
            continue
        try:
            actual = coerce_fact(field, facts[field], scenario)
        except ValueError:
            reasons.append({"field": field, "status": "UNKNOWN", "reason": "fact has invalid type"})
            if field not in unknown_fields:
                unknown_fields.append(field)
            continue
        matched = {
            "eq": lambda: actual == expected,
            "gte": lambda: actual >= expected,
            "lte": lambda: actual <= expected,
            "contains": lambda: expected.casefold() in actual.casefold(),
        }[op]()
        reasons.append({"field": field, "status": "PASS" if matched else "FAIL", "reason": f"{field} {op} {expected!r}: {'matched' if matched else 'not matched'}"})
    status = "FAIL" if any(row["status"] == "FAIL" for row in reasons) else "UNKNOWN" if unknown_fields else "PASS"
    return {"status": status, "reasons": reasons, "unknown_fields": unknown_fields}
