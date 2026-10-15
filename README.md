<p align="center">
  <h1 align="center">X-Agent</h1>
  <h3 align="center">Your agents already know you. X turns that into a meeting.</h3>
</p>

<p align="center">
| <a href="#quick-start"><b>Quick Start</b></a> | <a href="#how-it-works"><b>How It Works</b></a> | <a href="#demo"><b>Demo</b></a> | <a href="#scenarios"><b>Scenarios</b></a> | <a href="#roadmap"><b>Roadmap</b></a> | <a href="#中文版"><b>中文版</b></a> |
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/core%20dependencies-0-brightgreen" alt="Zero dependencies">
  <img src="https://img.shields.io/badge/scenario-dating-ff4d5e" alt="Scenario: dating">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="MIT License">
  <img src="https://img.shields.io/badge/built%20at-Zhangjiang%20Alumni%20Hackathon%202026-e8b34b" alt="Hackathon">
</p>

🔥 Built in 48 hours at the Zhangjiang Alumni Hackathon (Oct 16–17, 2026). One engine for dating, friendship, job matching, and cofounder matching — this repo ships the dating scenario end to end.

---

## About

X-Agent is an **agent-pool matching network**. The agents already around you — Muse, ChatGPT, Gemini, your daily assistants — know you deeply: your habits, your values, what you actually want. X-Agent never asks you to fill in another form. It **distills** what those agents know into a structured, matchable profile, and runs **two-sided matching** over the pool.

X-Agent is built on:

- **Distillation, not data collection** — raw conversations never leave the user's side; only a distilled profile card enters the pool. Privacy by distillation.
- **Two-sided by construction** — the final score is the harmonic mean of both directional scores. She fits you *and* you fit her; one-sided attraction sinks.
- **Explainable by default** — every score ships with human-readable reasons: who covers whose needs, which values align, which traits complement. A black box cannot tell its story; this can.
- **Scenarios as configuration** — a scenario is one declarative file (vocabularies, similarity/complementarity trait axes, weights). Dating today, jobs tomorrow; the engine never changes.
- **Living profiles** — conversation and feedback are re-distilled and merged in by confidence. Feedback becomes an explicit, inspectable threshold — never a hidden re-roll.

## How It Works

The distillation operator decomposes by scenario:

```
profile_scenario = Project_scenario( Distill_universal(raw material) )
```

The universal pass answers *"who is this person"*; the scenario projection answers *"in this arena, what about them matters"*. The same sentence — *"I pull all-nighters to ship"* — projects to *irregular schedule* in dating, and to *high execution drive* in cofounder matching.

```
 your agents                  X-Agent                       the pool
 ┌────────────┐  raw text   ┌───────────────────┐
 │ daily asst │ ──────────▶ │ Distillation D     │  profile cards
 │ work agent │ (never      │  prompt generated  │ ──────────────▶  circulate
 │ chat agent │  leaves)    │  from the scenario │                  │
 └────────────┘             └───────────────────┘                  ▼
        ▲                            │ merge (confidence-weighted)   two-sided
        └──── questions / feedback ──┘                               matching
```

Matching runs in three steps — hard rules filter first, then directional scoring, then combination:

```
s(A→B) = w_no · cover(A.needs, B.offers) + w_v · values + w_t · traits(sim/comp) + w_i · interests
score  = harmonic_mean( s(A→B), s(B→A) )
```

Every trait axis is declared `sim` (closeness scores) or `comp` (complementarity scores) in the scenario config. Pool-wide pairing is the classic two-sided stable-matching problem — see the roadmap.

## Quick Start

The core engine is pure Python 3 standard library. Zero dependencies.

```bash
# 1. Precompute the demo data (runs the real matching engine — nothing is faked)
python3 scripts/build_demo_data.py

# 2. Serve the demo
cd demo && python3 -m http.server 8000
# open http://localhost:8000 and hit "▶ 自动演示" (auto-play)
```

Distillation needs any OpenAI-compatible endpoint (the hackathon's Semantix credits work):

```bash
export LLM_BASE_URL=https://sem.ensureok.ai/v1
export LLM_API_KEY=<your key>
export LLM_MODEL=<a model from the provider's list>
python3 scripts/distill_persona.py \
  --raw data/raw_logs/azhe.md \
  --scenario scenarios/dating.json \
  --out /tmp/azhe.json
```

## Repository Layout

```
core/schema.py          profile structure + validation/normalization
core/distill.py         distillation operator D (prompt generated from scenario config) + merge
core/match.py           matching engine: hard filters, two-sided scoring, reasons, feedback re-ranking
scenarios/dating.json   the dating scenario: vocabularies, sim/comp axes, weights, hard rules
data/personas.json      13 pre-distilled personas (protagonist + 12 candidates)
data/raw_logs/          sample raw material (memory exports from three source agents)
scripts/                distill CLI + demo data builder
demo/index.html         single-file demo front-end (canvas starfield + the red thread)
```

## Demo

A 2–3 minute stage script, choreographed around one moment: thousands of threads flicker, and exactly one turns red.

| Time | Action | What it proves |
|---|---|---|
| 0:00 | Click **① 接入我的 Agents** | Three source agents stream their memories into X; a profile card crystallizes — raw text never leaves the user's side |
| 0:40 | Click **② 和我聊聊** | The profile is alive: follow-up answers are re-distilled and merged by confidence |
| 1:20 | Click **③ 开始匹配** | Hard rules first (long-distance / smoking rejected on stage, with reasons), then two-sided scoring |
| 2:00 | The red thread locks onto 林小满 (0.935) | Open the reasons panel: mutual needs/offers coverage + harmonic mean; the one-sided decoy 苏晴 sits at #3 as proof |
| 2:30 | Click **④ 反馈：太安静了** | Feedback becomes an explicit extroversion threshold — 林小满 is demoted, 陈语桐 wins. No hidden re-roll |

The demo arcs are designed into the personas but **computed by the real engine**, never scripted: mutual-coverage winner, high-similarity one-sided decoy, and two hard-filter rejections.

## Scenarios

Adding a scenario (jobs, cofounder matching, friendship) means writing one config file — copy `scenarios/dating.json` and change:

1. **Vocabularies** — `values_vocab` and `needs_offers_vocab` for the arena (in jobs, offers are skills and needs are role requirements)
2. **Trait axes** — each axis marked `sim` or `comp`, with a weight (cofounder matching: skills complementary, risk appetite similar)
3. **Weights** — the four score components
4. **Hard rules** — scenario-specific filters live in `core/match.py: hard_filter`, branched by scenario name

The same person gets a *different profile per scenario* — and can share a different one with each pool. That granularity is a feature, not a bug.

## Roadmap

- [ ] Second scenario end to end: `scenarios/cofounder.json` or `scenarios/jobs.json`, with a fresh persona set — same engine, new config
- [ ] Real agent integration: expose each source agent as an MCP server with a `get_user_model` tool (the architecture already assumes this)
- [ ] Pool-wide pairing: from top-1 to global stable matching (Gale–Shapley), with a "whole pool paired" finale animation
- [ ] Closed feedback loop: live chat answers → distill → merge → re-rank (the demo currently scripts the Q&A beats)
- [ ] Click a candidate node to inspect their profile card from the other direction
- [ ] Weight learning: after repeated feedback, adjust scenario `weights` with a simple online update

## Contributing

Built by a two-person hackathon team; PRs and issues welcome. Three design rules before you touch the code:

- The matcher must stay a **pure, deterministic function** — same input, same ranking, every time. No randomness on stage.
- Every score component must generate a **human-readable reason**. If it cannot explain itself, it does not ship.
- Raw text lives only in user-side material (`data/raw_logs/`). It **never** enters pool data structures.

## License

MIT

---

## 中文版

<p align="center"><i>你的 agent 已经很懂你了 — X 把这份「懂」，变成一次相遇。</i></p>

### 关于

X-Agent 是一个**智能体池匹配网络**。每个人身边都有越来越懂自己的 agent（Muse、ChatGPT、Gemini、各类助手），X-Agent 不再让用户填一遍表：它接入这些 agent 的记忆，**蒸馏**成一张可计算的结构化画像，再在池子里做**双边匹配**。婚恋、交友、求职、创业伙伴 — 同一套引擎。

它的立场：

- **蒸馏，而非搬运** — 原始聊天永不离开用户侧；进入池子的只有蒸馏后的结构化画像。隐私靠蒸馏解决。
- **双边匹配** — 最终分 = 两个方向分数的调和平均。她合你、你也得合她 — 单相思，沉底。
- **可解释** — 每个分数都带理由（谁覆盖了谁的哪些需求、共同看重什么、哪条特质互补）。黑盒匹配讲不出故事，我们讲得出。
- **场景可插拔** — 场景 = 一份声明式配置（词表、sim/comp 特质轴、权重）。换场景只改配置，引擎不动。
- **活画像** — 聊天与反馈持续蒸馏、按置信度并入画像；反馈会变成显式的门槛偏好，而不是偷偷重掷骰子。

### 工作原理

算子分解：`画像_场景 = Project_场景( Distill_通用(原始材料) )`。通用蒸馏回答"这个人是谁"，场景投影回答"在这个场景里，该看他的什么"。同一句"我经常熬夜赶项目"：婚恋投影读出*作息不规律*，创业投影读出*执行力强*。

匹配三步：硬约束过滤 → 双向打分 → 调和平均合并：

```
s(A→B) = w_no · cover(A 的需求, B 的供给) + w_v · 价值观 + w_t · 特质(sim/comp) + w_i · 兴趣
score  = harmonic_mean( s(A→B), s(B→A) )
```

每条特质轴在场景配置里标注 `sim`（求同）或 `comp`（互补）。池级全局配对是经典的**双边稳定匹配问题**（Gale–Shapley），见路线图。

### 快速开始

核心引擎零第三方依赖（Python 3 标准库）：

```bash
python3 scripts/build_demo_data.py        # 跑真实引擎生成演示数据（不是写死的假数据）
cd demo && python3 -m http.server 8000    # 打开 http://localhost:8000，点「自动演示」
```

真实蒸馏接任意 OpenAI 兼容端点（黑客松的 Semantix 额度即可）：设置 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` 三个环境变量后运行 `scripts/distill_persona.py`（参数见英文版 Quick Start）。

### 演示讲稿（2–3 分钟）

| 时间 | 动作 | 要讲的一句 |
|---|---|---|
| 0:00 | 点「接入我的 Agents」 | 三个 agent 的记忆汇成一张画像卡 — 原始文本不出用户侧 |
| 0:40 | 点「和我聊聊」 | 画像是活的：追问 → 再蒸馏 → 置信度加权 merge |
| 1:20 | 点「开始匹配」 | 先硬约束、再双向分；异地/吸烟当场淘汰且给理由 |
| 2:00 | 红线锁定林小满（0.935） | 理由面板：双向需求覆盖 + 调和平均；单向诱饵苏晴第 3 就是证据 |
| 2:30 | 点「反馈：太安静了」 | 反馈变成显式门槛，林小满降权、陈语桐胜出 — 不是重掷骰子 |

### 场景扩展

复制 `scenarios/dating.json`，只改四样：词表、特质轴的 sim/comp 与权重、四个分项权重、硬规则（在 `core/match.py: hard_filter` 按场景名分支）。同一个人 在不同场景 是不同的画像，投给不同池子的也可以是不同份 — 这是特性，不是缺陷。

### 路线图

- [ ] 第二个场景落地（`cofounder.json` 或 `jobs.json`）+ 第二组 personas，验证"同引擎、换配置"
- [ ] 源 agent 改为 MCP server，暴露 `get_user_model` 工具
- [ ] 从 top-1 扩展到全局稳定匹配（Gale–Shapley）+ "全场配对"收尾动画
- [ ] 聊天闭环：真实回答 → 蒸馏 → merge → 重排（当前 demo 是脚本化 QA beats）
- [ ] 点击候选人节点，从对方视角查看画像卡
- [ ] 多次反馈后用在线学习微调场景权重

### 设计原则

- 匹配函数必须是**纯函数 + 确定性输出** — 同样的输入永远同样的排名，舞台上不许有随机性。
- 任何分数都要能生成**人类可读的理由**；给不出理由的分项不要加。
- 原始文本只出现在用户侧材料里，**永不进入池数据结构**。

### 许可证

MIT
