# Live Distillation — Run Record & Evaluation

*Recorded 2026-10-15, the night before the hackathon. This document proves the distillation operator runs end-to-end against a real LLM endpoint — and reports what it got right, what it got wrong, and what changed downstream.*

## The run

| | |
|---|---|
| Endpoint | Semantix sponsor gateway (OpenAI-compatible), `https://sem.ensureok.ai/v1` |
| Model | `glm-5.2` (chosen from the account's model list) |
| Input | `data/raw_logs/azhe.md` — memory exports from three source agents (daily assistant / work agent / self-reflection notes) |
| Command | `python3 scripts/distill_persona.py --raw data/raw_logs/azhe.md --scenario scenarios/dating.json` |
| Cost | One chat-completion call; negligible against the $50 sponsor credit |
| Output | Captured verbatim in [`examples/azhe_live_profile.json`](../examples/azhe_live_profile.json) |

Essence line produced by the operator:

> 目标感强、行动多于言语的AI工程师，渴望能深聊、情绪稳定、一起成长的关系。

## Evaluation (vs the hand-written reference profile)

Reproduce offline, no API key needed:

```bash
python3 scripts/eval_distillation.py          # analyze the captured run
python3 scripts/eval_distillation.py --live   # re-distill, then evaluate
```

**Hard facts — 5/5 correct.** City （上海）, `wants_kids=open`, `smoker=false`, `require_same_city=true`, `dealbreaker_smoking=true`. Every gate-critical field was extracted correctly, so hard-filter behavior on the live profile is sound.

**Tag coverage — needs 4/4, offers 2/4, values 2/4.**

- Needs were fully recovered （深度交流 / 倾听 / 情绪稳定 / 共同成长）, plus one reasonable inference （空间感）.
- Offers were read differently: the model heard 情绪稳定 / 陪伴 / 倾听 where the reference says 经济独立 / 幽默感 — explicit signals in the raw material ("经济上自律", "冷幽默") were softened into vaguer traits.
- Values skewed toward 事业 / 稳定 / 健康 and dropped 家庭 / 体验 — two of the three source documents are work- and routine-heavy, and the extraction weighted them accordingly.
- Trait sliders were directionally right (planning 0.9, extroversion 0.2) except romanticism (0.2 vs reference 0.55 — the model took the breakup postmortem literally).

**Downstream consequence — the winner changes.** Re-ranking the pool with the live profile:

| | #1 | #2 |
|---|---|---|
| Reference profile | 林小满 (0.935) | 陈语桐 (0.590) |
| Live profile | **顾晚 (0.618)** | 林小满 (0.576) |

The more career-and-stability-flavored reading of 阿哲 happens to cover 顾晚's needs better. Nothing crashed; the ranking is coherent — for a *different reading of the same person*.

## What this means

1. **The pipeline is real.** Operator → validated profile → matcher, no mocks, one API call. On stage, distilling an unseen raw log live takes ~30 seconds — that is the answer to "is any of this actually running?"
2. **A distilled profile is a reading, not ground truth.** Extraction is sensitive to source mix and model choice. That is precisely why the design carries per-field confidence, merges new evidence instead of re-freezing, and keeps the user in the loop — the eval above is the evidence, not an embarrassment.
3. **Stage guidance.** The choreographed demo keeps the pre-distilled pool (its narrative — the mutual-coverage winner, the one-sided decoy — is tuned and must not move). Live distillation is the encore / Q&A proof, now rehearsed and verified.

## 中文摘要

2026-10-15 实跑：用 Semantix 网关的 glm-5.2 对阿哲的三源材料做了一次真实蒸馏，一次调用出卡。硬事实 5/5 全对（硬门行为可信）；需求命中 4/4；供给与价值观出现可解释偏差（原料偏工作记录，模型把人读得更"事业稳定"）。把真画像放回引擎重排，冠军从林小满（0.935）变为顾晚（0.618）——蒸馏是"一种读法"而非唯一真相，这正是画像要带置信度、要持续 merge 的原因。复现：`python3 scripts/eval_distillation.py`（离线分析已存档的运行）或加 `--live` 重新蒸馏。
