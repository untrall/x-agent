"""The distillation operator D.

    D(raw_text, scenario) -> profile

It takes everything a person's agents know about them (chat logs, memory
exports, self-descriptions) and strips it down to the matchable structure
defined by core/schema.py. The prompt is *generated from the scenario
config* — the operator skeleton never changes per use case, only the
scenario declaration does:

    profile_scenario = Project_scenario( Distill_universal(raw) )

In this implementation the two stages are fused into one LLM pass whose
instructions are built from scenarios/<name>.json (schema + vocabularies).
The merge operator below keeps the profile *alive*: new chat / feedback
evidence is distilled again and merged in by confidence and recency.

LLM access is OpenAI-compatible (works with the hackathon's Semantix
credits, OpenAI, or any local server):

    LLM_BASE_URL   e.g. https://sem.ensureok.ai/v1
    LLM_API_KEY    your key
    LLM_MODEL      model name from the provider's list
"""
import json
import os
import urllib.request

from core.schema import validate_profile

SYSTEM_TEMPLATE = """你是一个画像蒸馏算子。你的任务：阅读关于某个人的原始材料（聊天记录、其他 AI agent 的记忆、自述），\
把这个人蒸馏成一张可用于「{display_name}」匹配的结构化画像卡。

规则：
1. 只提取材料中有证据的内容，不要臆测；没有证据的字段留空或用中性值。
2. values 只能从这个词表里选，按重要程度排序，最多 5 个：{values_vocab}
3. needs（这个人在关系中寻找的）和 offers（这个人能提供的）只能从这个词表里选，各最多 6 个：{tag_vocab}
4. traits 是 0 到 1 的滑杆，只能包含这些轴：{trait_axes}
5. essence 用一句话（50 字内）概括这个人是谁、想要什么样的关系，第一人称视角改写为第三人称。
6. confidence 给出你对整体抽取的置信度 0 到 1。
7. 只输出一个 JSON 对象，不要任何解释文字，不要 markdown 代码块。JSON 结构：
{{"name": "", "gender": "M|F", "age": 0, "city": "", "job": "",
  "facts": {{"wants_kids": "yes|no|open", "smoker": false, "require_same_city": false, "dealbreaker_smoking": false}},
  "values": [], "traits": {{}}, "needs": [], "offers": [], "interests": [], "essence": "", "confidence": 0.0}}
"""


def build_messages(raw_text: str, scenario: dict) -> list:
    system = SYSTEM_TEMPLATE.format(
        display_name=scenario.get("display_name", "匹配"),
        values_vocab="、".join(scenario.get("values_vocab", [])),
        tag_vocab="、".join(scenario.get("needs_offers_vocab", [])),
        trait_axes="、".join(
            f'{a["key"]}({a["label"]})' for a in scenario.get("trait_axes", [])
        ),
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "原始材料如下：\n\n" + raw_text[:12000]},
    ]


def call_llm(messages: list) -> str:
    base = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    if not key:
        raise RuntimeError(
            "LLM_API_KEY not set. Export LLM_BASE_URL / LLM_API_KEY / LLM_MODEL "
            "(any OpenAI-compatible endpoint works, e.g. the Semantix credits)."
        )
    body = json.dumps(
        {"model": model, "messages": messages, "temperature": 0.2}
    ).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


def distill(raw_text: str, scenario: dict) -> dict:
    """Run the distillation operator over raw material."""
    raw_profile = _parse_json(call_llm(build_messages(raw_text, scenario)))
    return validate_profile(raw_profile, scenario)


def merge_profile(old: dict, new: dict) -> dict:
    """Merge freshly distilled evidence into a living profile.

    - scalar facts: newer evidence wins when its confidence is not lower
    - traits: confidence-weighted average (profile moves, never jumps)
    - tag lists (values/needs/offers/interests): union, new items first
    """
    merged = dict(old)
    oc, nc = old.get("confidence", 0.7), new.get("confidence", 0.7)
    if nc >= oc:
        for k in ("name", "age", "city", "job", "essence"):
            if new.get(k):
                merged[k] = new[k]
        merged["facts"] = {**old.get("facts", {}), **new.get("facts", {})}

    traits = dict(old.get("traits", {}))
    for k, v in new.get("traits", {}).items():
        if k in traits:
            traits[k] = round((traits[k] * oc + v * nc) / (oc + nc), 3)
        else:
            traits[k] = v
    merged["traits"] = traits

    for k in ("values", "needs", "offers", "interests"):
        combined = list(new.get(k, [])) + [
            x for x in old.get(k, []) if x not in new.get(k, [])
        ]
        merged[k] = combined[: (5 if k == "values" else 6 if k != "interests" else 8)]
    merged["confidence"] = max(oc, nc)
    return merged
