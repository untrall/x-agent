# 结合流程：管理员视角匹配 → 用户视角协商

X-Agent 的完整故事是两幕，分别由仓库的两套代码承载，现在由
`scripts/run_combined.py` 串成一条流水线：

## 第一幕 · 管理员视角（`core/`）

匹配引擎对候选池做硬门过滤（Hard Gates）→ 双向契合打分
（Directional Fit）→ 调和平均合并，产出带理由的排名。
以阿哲为例：林小满 0.935、陈语桐 0.590、苏晴 0.495 上榜；
沈亦舟被异地硬门淘汰、陆蔓被吸烟 dealbreaker 淘汰。
这一幕就是 GitHub Pages 演示（`demo/`）呈现的内容。

## 第二幕 · 用户视角（`src/xagent/mvp/`）

排名只是"系统觉得合适"。真正的确认发生在用户视角：上榜的每位候选
由**自己的 Agent** 出面，与主角的 Agent 点对点协商（去中心化，
各自持有画像与数据，无中央协调服务）：

1. 主角 Agent 广播需求，附硬条件（由主角画像事实生成）；
2. 每个候选 Agent 本地核对硬条件（FILTER PASS/FAIL）；
3. 画像里没定的偏好（本场景：是否要求对方对要孩子持开放态度）
   由系统**当场补问主角本人**，新条件实时同步给所有进行中的会话；
4. 候选人被问到未公开的事实时，由其 Agent 询问本人确认；
5. 条件全过 → 主角 Agent 发提案 → 双方 Agent 核对 →
   **双方本人批准** → 生成一致的「见面提案」结果卡。

## 桥接设计（`scripts/run_combined.py` + `configs/mvp/dating-match.json`）

桥接层只做翻译，不改两边任何一行的核心逻辑：

| 画像（core/schema.py） | 协商字段（dating-match.json） | 来源 |
|---|---|---|
| `city` 与主角相同 | `same_city` | 预置事实 |
| `facts.smoker` 取反 | `non_smoker` | 预置事实 |
| `facts.wants_kids != "no"` | `kids_open` | **故意不预置**，协商中补问 |

`kids_open` 不预置是关键设计：它演示了"画像未定的偏好由本人当场
决定、候选事实由对方本人当场确认"的 loop-in 机制，而不是把一切
都写死在配置里。

## 运行方式

环境：`python3 -m venv .venv && .venv/bin/pip install -e .`
（或 `uv sync --group dev`）。

自动全程（代答问题、自动批准，约 10 秒出全记录）：

```bash
.venv/bin/python scripts/run_combined.py
# 产出 .local/combined/<user>-<时间>/TRANSCRIPT.md + result.json
```

现场手动（TUI 四窗口，适合路演互动）：

```bash
.venv/bin/python scripts/run_combined.py --configs-only
# 按打印出的四条命令各开一个终端运行 run_agent.py
# 在 agent-1（阿哲）窗口 Ctrl+N 发起需求，其余窗口按提示回答/批准
```

样例输出见 `docs/combined-transcript-sample.md`（自动模式真实运行
记录：三位候选全部 CONNECTED，各生成一份见面提案）。
