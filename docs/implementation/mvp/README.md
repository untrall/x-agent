# 去中心化 TUI MVP

每个窗口运行同一份应用，各自持有画像、SQLite、HTTP 端口和策略实例。[Agent 交流界面](tui-conversation.svg)、[需要本人参与时](tui-loop-in.svg)、[方案批准卡](tui-approval.svg)。广播是发起方逐一发送点对点 HTTP 消息；后续每条会话都由双方自行管理。没有中央协调服务。协议是本项目的 HTTP JSON 协议，本阶段不宣称兼容标准 A2A。

## 启动四个窗口

在 `x-agent` 目录执行 `uv sync --group dev`，然后在四个终端或分屏中分别执行：

```bash
uv run python scripts/run_agent.py --config configs/mvp/agent-1.json
uv run python scripts/run_agent.py --config configs/mvp/agent-2.json
uv run python scripts/run_agent.py --config configs/mvp/agent-3.json
uv run python scripts/run_agent.py --config configs/mvp/agent-4.json
```

每条命令运行一个进程；端口依次为 8011–8014。每个窗口建议至少 90 列、28 行。默认 `deterministic` 模式使用真实网络和存储，但决策为确定性规则。`--headless` 运行完全相同的 HTTP/协商内核，关闭 TUI，供自动验收使用。

默认界面只常驻顶部用户名片、简短状态和 Agent 交流流。名片中的简介来自各配置的 `profile.description`，事实来自 `profile.facts` 与已确认长期记忆，仅展示 `public_fields`；未提供的公开事实显示「待确认」。同一份画像视图也传给模型的 `own_profile`，已确认事实继续用于硬条件筛选。名片整理不额外调用模型，不会凭空生成用户经历。

`Ctrl+N` 发起需求，`Ctrl+P` 打开命令输入，`Ctrl+D` 展开/收起模型、端口、会话 ID 等详情。默认隐藏工具栏和会话选择器；有多个待确认方案或多个结果时才自动显示必要选择器。

## 三分钟主线

1. 四个窗口并排，展示不同身份和顶部用户名片。窗口 1 按 `Ctrl+N`，输入 `寻找创业合伙人，每周至少15小时` 后回车。输入区收起，Agent 交流流成为主画面。
2. 窗口 2 每周只有 2 小时，收到需求后被硬条件淘汰。窗口 3 每周 20 小时、窗口 4 每周 15 小时，继续协商。
3. 窗口 1 出现脉动高亮的「需要你参与」卡片，询问“是否还要求 AI 产品经验？”，输入 `是` 后卡片自动收起。这是同一需求的补充，应用到仍在进行的候选会话。
4. 窗口 3、4 分别询问自己的用户是否具备 AI 产品经验。窗口 3 输入 `是`，窗口 4 输入 `否`。两份回答只属于各自用户。
5. 窗口 1 和窗口 3 各自出现方案确认卡，卡片明确显示对方身份及条件。各自点击「批准方案」（自动聚焦后可按 Enter）。本人批准后卡片收起，等待对方确认；双方均批准同一提案后，生成一致的结果卡。

同样的输入交换窗口 3、4 的回答，符合要求的人随之改变。结果由实际事实决定，没有内定编号。普通回答不代表批准。每人对同一提案只作一次决定；当前不提供批准后的撤回协议。

平时没有常驻输入框，主区域显示有发送方向的 Agent 交流和单独标明的本地决策。仅有待回答问题或尚未本人批准的方案时，自动显示参与卡；发起需求、打开命令属于用户主动打开的输入区域。脉动每 0.75 秒切换轻微背景/边框高亮，关闭动画设置时保持静态提示。

问题卡中的文字用于回答当前问题；「发起需求」中的文字始终用于新需求，途中到达的问题不会抢走草稿。多问题可用下拉选择，开始输入后锁定问题，清空草稿后可切换。回答失败会保留草稿并恢复焦点；已过期的问题会提示清空草稿，不会误发为新需求。补充信息卡只保留问题和输入框，回车提交，不显示任何回答按钮。保存本人事实仍可使用命令 `/remember 问题ID 回答内容`。

使用 `--mode codex` 或 `--mode model` 时，可以自然语言回答当前问题。例如窗口 1 输入“需要合伙人有 AI 产品经验”，窗口 3 输入“我负责过一款 AI 产品的设计和上线”，窗口 4 输入“我还没有做过 AI 产品”。模型模式下所有回答（包括简短的是/否或数字）均经过模型解释。模型结合问题类型区分“需求条件”和“本人事实”，转换成经过类型校验的字段值；保留原话与解析结果。含义不明确时补问，原问题和草稿保留，不写入记忆。当前只支持回答当前字段；额外条件需要另发需求。模型暂时不可用时也保留问题，可稍后重新回车提交。

默认 `deterministic` 模式只接收明确的“是 / 否 / 需要 / 不需要”或数字，不支持自由语言理解。四个窗口均需加 `--mode codex` 才能使用上述体验。更新代码后以原配置重启，已有 SQLite 会话仍保留。

`Ctrl+P` 打开命令输入；仍支持 `/request`、`/answer`、`/approve` 等命令。`Ctrl+D` 展开详情后也有对应按钮。`Esc` 收起主动打开的输入区，`Tab` 切换控件，`Ctrl+Q` 退出应用并停止本机 HTTP 服务。

| 操作 | 命令 |
|---|---|
| 新需求 | `/request 寻找创业合伙人，每周至少15小时` |
| 回答指定问题 | `/answer 问题ID 是` |
| 回答并记住本人事实 | `/remember 问题ID 是` |
| 批准所选会话 | `/approve` 或 `/approve 会话ID` |
| 拒绝所选提案 | `/reject` 或 `/reject 会话ID` |
| 明确重试失败消息 | `/retry 消息ID` |
| 列出会话、帮助 | `/sessions`、`/help` |

普通回答仅在该会话生效；`/remember` 只适用于本人事实问题，会将确认事实保存到自己的 SQLite，重启后可供新会话复用。需求方“这次是否要求 AI 经验”不当作本人画像事实保存。当前还没有跨请求的偏好记忆管理界面。

## 模型模式

### 本地 Codex 登录（本次演示推荐）

先确认 `codex login status` 已登录，然后在四个终端分别启动：

```bash
uv run python scripts/run_agent.py --config configs/mvp/agent-1.json --mode codex
uv run python scripts/run_agent.py --config configs/mvp/agent-2.json --mode codex
uv run python scripts/run_agent.py --config configs/mvp/agent-3.json --mode codex
uv run python scripts/run_agent.py --config configs/mvp/agent-4.json --mode codex
```

默认调用 `gpt-6-luna`，推理档位为 `low`。本机 Codex CLI 0.160.0 已实测可用；其他账号的模型可用性需要以实际调用为准。每个应用仍自行发送 HTTP 消息、管理自己的状态和记忆。模型参与需求抽取、缺失信息补问、提案与核对；硬标签筛选及最终用户批准由内核执行。被硬条件淘汰的窗口无需调用模型。按 `Ctrl+D` 可查看 `codex · gpt-6-luna · low`。

可按需覆盖配置，无需设置 API Key：

```bash
export XAGENT_CODEX_MODEL='gpt-6-luna'
export XAGENT_CODEX_REASONING='low'
export XAGENT_CODEX_TIMEOUT='90'
# CLI 不在 PATH 时：export XAGENT_CODEX_BIN='/opt/homebrew/bin/codex'
```

适配器通过 `codex exec` 复用现有登录。它使用临时独立目录、`--ephemeral` 和 JSON Schema，每次仅传入当前任务的业务上下文，不恢复其他 Codex 会话。`--ignore-user-config` 避免个人工具配置干扰决策，仍使用 Codex 自己的登录机制；不读取或复制凭证。长期记忆由 X-Agent 的 SQLite 管理。候选人的事实补问与需求方的偏好补问使用不同角色上下文。

这仍是远程模型调用，会消耗 Codex 账号额度，并非离线模型或免费推理。CLI 本身带有上下文开销，不保证比直接 API 的总成本低。每个模型决策事件记录型号、档位、耗时和 token usage；默认每次调用最多等待 90 秒，适配层不自动重试或升级模型，不回退为确定性。CLI 可能自行重连；只有退出成功、收到完成事件且输出通过校验才接受结果，恢复过的错误事件计数会记录在 metadata 中。失败消息可以通过 `/retry` 人工重试。超时、协程取消及正常应用退出会终止正在运行的 CLI 子进程。

### Chat Completions 兼容服务

配置三个环境变量，然后对所需窗口在启动命令末尾加 `--mode model`：

```bash
export XAGENT_MODEL_BASE_URL='https://你的服务地址/v1'
export XAGENT_MODEL_NAME='你的模型名'
export XAGENT_MODEL_API_KEY='你的密钥'
```

适配器调用 Chat Completions 兼容接口，使用 JSON 模式并在本地严格校验结构化输出。模型负责需求抽取和当前阶段允许的协议动作建议；内核复核字段证据与硬条件，批准仍由本人执行。超时或无效输出会显示错误，模式不会偷偷切成确定性。默认 20 秒超时，每次输出校验失败最多修复一次。后台消息处理失败会持久化为阻塞状态，窗口显示原因和消息 ID；修复服务配置或故障后使用 `/retry 消息ID` 明确重试，避免反复消耗模型调用。

此 HTTP 服务路线仍只有本地假服务验证，未提供远端服务配置。上述 Codex 路线已做真实模型的四进程联调。HTTP 模型客户端当前直连服务，不读取系统代理变量。

## 自动验收与第二场景

以下命令创建临时数据库和临时端口，真实启动四个独立进程，结束后停止这些进程；不会使用或清空人工演示的数据：

```bash
uv run python scripts/smoke_mvp.py
uv run python scripts/smoke_mvp.py --scenario venue
uv run python scripts/smoke_mvp.py --mode codex
uv run --group dev pytest -q
```

场地版本只替换场景字段和画像：`capacity` 粗筛，`projector` 补问，最后双方批准场地意向方案。仍使用相同进程、协议、状态机和 TUI 代码。场地自动验收即可作为最小适配证明，不扩建另一套产品。

`--mode codex` 验收会实际消耗模型额度；普通 pytest 使用假 CLI 覆盖模型边界，不调用远程模型。真实验收使用自动提交的模拟用户回答和批准，测试筛选、补问、进程重启、原会话恢复与双方结果卡一致。

## 数据与恢复

默认数据库为 `.local/mvp/agent-1.sqlite3` 至 `agent-4.sqlite3`。退出后重新执行同一命令即可恢复会话、问题、批准和待发送消息。对端暂时不在线时，消息保存在本机 outbox 后重试。演示重置时，先退出四个窗口，再将 `.local/mvp` 整个目录改名归档；下次启动创建新数据库。不要在运行中替换数据库。

本地 owner HTTP 使用各自配置的 `owner_token`；Agent 间 HTTP 使用独立的 peer token。配置内的 token 都是演示值。此版本仅监听 loopback，不包含公网身份注册、动态节点发现或生产认证。Peer 列表由各自配置提供；新增参与者需要更新相关配置。MVP 的协商以已声明的场景字段为基础，支持缺失事实补问和拒绝，不包含任意自由聊天、反提案或开放式谈判。

## 实现位置

- `src/xagent/mvp/runtime.py`：本地会话、问题、恢复、审批和结果。
- `src/xagent/mvp/storage.py`：独立 SQLite、持久化 inbox/outbox。
- `src/xagent/mvp/server.py`：本人接口与对端消息接口。
- `src/xagent/mvp/scenario.py`：配置字段及 PASS/FAIL/UNKNOWN 条件求值。
- `src/xagent/mvp/policy.py`：确定性与模型策略。
- `src/xagent/mvp/codex_policy.py`：本地 Codex CLI 结构化决策适配。
- `src/xagent/mvp/tui.py`：身份、会话、日志、问题和结果展示。
- `configs/mvp/`：画像、节点地址、合伙人与场地场景。

既有 `web/` 工作台和旧版 `core/` 演示保持独立；本轮演示请使用上述 TUI 入口。
