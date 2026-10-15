"""Profile schema for X-Agent.

A *profile* is the distilled, matchable representation of a person.
Raw text (chat logs, other agents' memories) never enters the pool —
only this structure does. Privacy by distillation.

Profile shape (plain dict, JSON-serializable):

    {
      "id": "azhe",
      "name": "阿哲",
      "gender": "M",
      "age": 29,
      "city": "上海",
      "job": "AI 工程师",
      "facts": {                     # hard, factual attributes
        "wants_kids": "open",        # yes | no | open
        "smoker": false,
        "require_same_city": true,   # I only match within my city
        "dealbreaker_smoking": true # I never match a smoker
      },
      "values": ["成长", "诚实", ...],          # ranked, from scenario vocab
      "traits": {"extroversion": 0.35, ...},    # 0..1 sliders, scenario axes
      "needs":  ["深度交流", ...],               # what I seek (scenario vocab)
      "offers": ["经济独立", ...],               # what I give (scenario vocab)
      "interests": ["跑步", ...],                # free tags, Jaccard-scored
      "essence": "一句话的我",                    # extractor-written summary
      "confidence": 0.8                          # overall extraction confidence
    }
"""

PROFILE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "gender": {"type": "string", "enum": ["M", "F"]},
        "age": {"type": "integer"},
        "city": {"type": "string"},
        "job": {"type": "string"},
        "facts": {
            "type": "object",
            "properties": {
                "wants_kids": {"type": "string", "enum": ["yes", "no", "open"]},
                "smoker": {"type": "boolean"},
                "require_same_city": {"type": "boolean"},
                "dealbreaker_smoking": {"type": "boolean"},
            },
        },
        "values": {"type": "array", "items": {"type": "string"}},
        "traits": {"type": "object", "additionalProperties": {"type": "number"}},
        "needs": {"type": "array", "items": {"type": "string"}},
        "offers": {"type": "array", "items": {"type": "string"}},
        "interests": {"type": "array", "items": {"type": "string"}},
        "essence": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["name", "values", "traits", "needs", "offers", "essence"],
}

_DEFAULT_FACTS = {
    "wants_kids": "open",
    "smoker": False,
    "require_same_city": False,
    "dealbreaker_smoking": False,
}


def validate_profile(p: dict, scenario: dict) -> dict:
    """Coerce an LLM-produced (or hand-written) dict into a clean profile.

    - drops values / needs / offers outside the scenario vocabularies
    - clamps trait sliders to [0, 1] and fills missing axes with 0.5
    - fills fact defaults
    """
    out = dict(p)
    out["facts"] = {**_DEFAULT_FACTS, **(p.get("facts") or {})}

    values_vocab = set(scenario.get("values_vocab", []))
    out["values"] = [v for v in p.get("values", []) if v in values_vocab][:5]

    tag_vocab = set(scenario.get("needs_offers_vocab", []))
    canon = scenario.get("canonical_tags", {})

    def norm_tags(tags):
        seen, res = set(), []
        for t in tags or []:
            t = canon.get(t, t)
            if t in tag_vocab and t not in seen:
                seen.add(t)
                res.append(t)
        return res[:6]

    out["needs"] = norm_tags(p.get("needs"))
    out["offers"] = norm_tags(p.get("offers"))

    traits = {}
    for axis in scenario.get("trait_axes", []):
        key = axis["key"]
        v = (p.get("traits") or {}).get(key, 0.5)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 0.5
        traits[key] = min(1.0, max(0.0, v))
    out["traits"] = traits

    out["interests"] = list(dict.fromkeys(p.get("interests", [])))[:8]
    out["essence"] = str(p.get("essence", ""))[:200]
    try:
        out["confidence"] = float(p.get("confidence", 0.7))
    except (TypeError, ValueError):
        out["confidence"] = 0.7
    return out
