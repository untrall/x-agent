"""Synthetic, public day-one scenario data."""

DEMO = {
    "scenario": {"id": "cofounder.v1", "name": "创业合伙人"},
    "profiles": [
        {
            "owner_id": "owner-a", "agent_id": "agent-a", "name": "林澈",
            "role": "技术创始人", "summary": "寻找产品与商业合伙人；每周投入至少 15 小时。",
            "facts": [
                {"field": "focus", "label": "当前方向", "value": "AI 产品创业", "source": "owner-provided", "visibility": "public"},
                {"field": "hours_per_week", "label": "每周投入要求", "value": 15, "source": "owner-provided", "visibility": "public"},
            ],
            "requirements": [
                {"field": "hours_per_week", "label": "每周投入", "kind": "hard", "operator": ">=", "value": 15},
                {"field": "start_in_days", "label": "全职加入时间", "kind": "ask", "operator": "confirm", "value": 90},
            ],
            "version": 1,
        },
        {
            "owner_id": "owner-b", "agent_id": "agent-b", "name": "陈予",
            "role": "产品负责人", "summary": "有自述的 AI 产品经验；可每周投入 15 小时，90 天后全职加入，提议先试合作 14 天。",
            "facts": [
                {"field": "ai_product_experience", "label": "AI 产品经验", "value": True, "source": "self-reported", "visibility": "public"},
                {"field": "hours_per_week", "label": "每周投入", "value": 15, "source": "self-reported", "visibility": "public"},
                {"field": "full_time_after_days", "label": "全职加入时间", "value": 90, "source": "self-reported", "visibility": "public"},
                {"field": "trial_days", "label": "试合作", "value": 14, "source": "self-reported", "visibility": "public"},
            ],
            "requirements": [], "version": 1,
        },
    ],
    "candidates": [
        {"agent_id": "agent-b", "name": "陈予", "role": "产品负责人",
         "summary": "每周 15 小时，90 天后全职，先试合作 14 天。", "eligible": True,
         "reason": "满足每周投入至少 15 小时的硬性要求。"},
        {"agent_id": "agent-c", "name": "候选人 C", "role": "潜在合伙人",
         "summary": "每周可投入 2 小时。", "eligible": False,
         "reason": "每周投入 2 小时，低于 15 小时的硬性要求。"},
    ],
}
