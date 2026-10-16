# X Agent 两人实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. 本文先供两名团队成员协作；不自动启动代码实现或其他 agent。步骤使用 checkbox 记录完成状态。

**Goal:** 在 2026-10-17 结束前交付两个独立 Agent 的发现、协商、追问、恢复、双确认和介绍结果完整流程。

**Architecture:** A/B 各自运行相同 Python 服务并持有私有数据，经官方 A2A SDK 通信。LangGraph + SQLite 保持可恢复会话，纯规则校验约束和批准，浏览器展示公开事件与各自的 owner 操作。

**Tech Stack:** Python 3.12、A2A Python SDK 固定源码版本或经烟测的固定发行版、LangGraph 1.2.15、langgraph-checkpoint-sqlite 3.1.2、FastAPI、SQLite、轻量原生 HTML/JS 前端。若前端成员熟 React，可用 Vite，但不同时引入 Next.js 服务端和 Python API 两套后端。

**Spec:** [design.md](design.md)。已确认团队两人，截止为 2026-10-17 17:00（北京时间）。优先今天起步；另提供明天 09:00–17:00 的压缩方案。14:30 停止新增功能，15:00 冻结演示版本，16:30 内部提交。以下产品文件与命令仍为实施目标。

## Global Constraints

- 主场景 `cofounder.v1`；第二场景 `event_partner.v1`；共用核心状态机与协议 schema。
- A/B 独立进程、独立 owner token、独立数据库、独立模型上下文；中央服务只持有允许公开的数据。
- 默认每会话最多 6 次 Agent 决策、2 次 owner 追问；模型 timeout 15 秒，结构错误最多修复一次。
- 用户回答默认只更新 session overlay；写入全局 profile 必须明确选择。
- 不允许自动修改硬约束、不允许模型生成 owner approval；所有批准绑定同一 proposal digest。
- 同 session_id 恢复；A2A task_id/context_id 映射持久化；终态不可续写。
- 不复制无明确许可依据的项目代码；复用代码必须记录来源并保留许可文本。
- 本次已有产品代码不是设计约束；新核心放 `src/xagent/`，不将原先静态演示混成新功能完成证据。

## Review Focus

| 高风险输入/情况 | 预期行为 | 所属任务 |
|---|---|---|
| 画像缺字段或未知可协商项 | 保留 unknown，发给正确 owner，不默认满足也不擅自拒绝 | T1、T2 |
| 重复/迟到回答、旧 revision、错 owner | 不重复推进，不跨用户写入；返回明确冲突或权限错误 | T2、T4 |
| 模型越权改硬约束或发送对端私有内容 | 代码拒绝动作；公共消息只由允许字段构造 | T2、T3 |
| 中断后服务重启、SSE 重连 | 同 session 恢复，无双重发信、重复扣轮次或重复产物 | T2、T4 |
| A 已批准后 B 改条件，或一方拒绝 | 旧批准失效，不提前生成介绍或披露联系方式 | T3、T5 |

## 分工和关键路径

**成员 A：协议、状态机、存储、A2A、规则与授权。成员 B：画像入口、模型适配、前端、数据夹具、结果页与演示。** 两人在开工后 30 分钟内冻结 schema；谁负责文件谁处理该文件冲突，另一人通过接口协作。

关键路径是 `消息契约 → 可恢复状态机 → 两进程通信 → 用户回答 → 双确认 → 演示验证`。视觉完善不能阻塞这条路径。

### 推荐排期 今天起步

今天先完成能从头到尾执行的最小流程。若比赛限制赛前编码，今天仅做研究、数据/界面草图和环境检查，编码采用后面的保底排期。

| 时段 | 成员 A 协商内核 | 成员 B 用户闭环 | 共同验收 |
|---|---|---|---|
| 今天开工前 30min | 定义 Session/Decision/Question/Event | 定义主故事、问题卡和结果卡 | 固定接口、三个候选、一个主场景 |
| 今天随后 2h | T1/T2：规则、FakePolicy、暂停与恢复 | 画像预览、合成数据、前端 fixture | 同一份 JSON 数据跑通到用户问题 |
| 今天再 2h | T3：独立 A/B 服务、真实 HTTP、审批存储 | UI 接真实 API、模型结构化输出 | 输入→协商→追问→回答→结果的粗糙闭环 |
| 今天结束前 30min | 保存 checkpoint 和 HTTP trace | 走一遍全流程，记录阻塞点 | 不留“明天第一次联调”的风险 |
| 明天 09:00–09:30 | 两人重跑昨晚版本、核对剩余工作 | 两人重跑昨晚版本、核对剩余工作 | 今天工作以实际状态为起点 |
| 09:30–11:00 | 恢复、幂等、双确认和权限 | 真实回答 patch、模型错误提示、结果导出 | **11:00 主场景 live 全链路通过** |
| 11:00–12:00 | 重启/重复消息/错 owner 检查 | 同意与拒绝两条 UI 流程、简化布局 | 一次成功、一次拒绝、一次恢复 |
| 12:00–12:30 | 午餐和缓冲 | 午餐和缓冲 | 不增加范围 |
| 12:30–13:30 | 第二场景契约用例、修确定性故障 | 第二场景配置、讲稿初版、截图 | 第二场景至少有同核心运行证据 |
| 13:30–14:30 | 启动脚本、脱敏日志、关键回归 | 跑实际 4min Demo，录一份可用备份 | **14:30 停止加功能** |
| 14:30–15:00 | 只修阻断展示的问题 | 只修阻断展示的问题 | **15:00 冻结演示版本** |
| 15:00–16:00 | 干净启动、README、依赖和许可证 | 最终录屏、截图、提交文案 | 交付包与视频对应同一版本 |
| 16:00–16:30 | 与 B 互查仓库/启动/文件 | 主责提交，与 A 核对视频/链接 | **16:30 提交完成并检查回执** |
| 16:30–17:00 | 处理上传、权限或链接故障 | 彩排、检查提交状态 | 不再改产品功能 |

若两人技术栈接近，建议你担任 A，同时负责产品范围和架构决策；队友担任 B，并担任提交负责人。若队友更熟 Python、异步服务和协议，则交换，模块边界保持不变。B 不只是写页面，还负责模型适配、画像提取和结果产物，以平衡工作量。

### 保底排期 只剩明天

| 时间 | 成员 A | 成员 B | 出口 |
|---|---|---|---|
| 09:00–09:30 | 冻结契约、检查依赖与端点 | 冻结故事、准备三个候选和 UI fixture | 只保留一个主场景完整 UI |
| 09:30–11:00 | 规则 + FakePolicy + SQLite 暂停/恢复 | 三视图、画像/模型适配、问题卡 | 后端状态流与前端数据形状一致 |
| 11:00–12:00 | A2A 双进程、双确认 API | UI 接真 API、结果卡 | **12:00 首次完整联调通过** |
| 12:00–12:30 | 午餐及必要缓冲 | 午餐及必要缓冲 | 不加新功能 |
| 12:30–13:30 | 重启、权限、重复输入、过期批准 | 真实模型一遍、拒绝分支、第二场景配置 | 第二场景只做契约用例 |
| 13:30–14:30 | 修阻断问题、启动/烟测脚本 | 彩排、初版录像、运行说明 | 14:30 停止加功能 |
| 14:30–15:00 | 最后一轮必要修复 | 最后一轮必要修复 | 15:00 冻结 |
| 15:00–16:00 | 干净环境验证、README | 最终录屏、截图和提交文案 | 可交付包齐备 |
| 16:00–16:30 | 技术项复核 | 主责提交，检查回执 | 16:30 提交完成 |
| 16:30–17:00 | 提交故障缓冲 | 提交故障缓冲与彩排 | 不再开发 |

不把网络部署作为默认关键路径。当前环境没有发现 Docker CLI，优先用 `uv` + 启动脚本。如主办方必须有公网地址，09:30 前确认并分配部署预算；保持同一服务静态页面，避免比赛后半段临时引入新云服务。

## 文件边界

```text
src/xagent/
  contracts.py           # A：唯一共享 Pydantic 模型和枚举
  scenario.py            # A：配置载入、校验、受限条件操作符
  matching.py            # A：三值硬约束、方向覆盖、稳定排序
  repository.py          # A：会话/事件/幂等/审批/任务映射 SQLite
  negotiation.py         # A：状态图、暂停、恢复、预算
  privacy.py             # A：公开字段投影、模型动作权限
  approvals.py           # A：canonical digest、双确认、失效
  transport_a2a.py       # A：SDK 接口和业务消息映射
  server.py              # A：owner API、SSE、启动入口
  policy.py              # B：AgentPolicy 接口、FakePolicy、LLMPolicy
  profile_builder.py     # B：自然语言到待确认画像
  artifacts.py           # B：结果 JSON、可选 ICS
scenarios_v2/
  cofounder.json         # B：与现有 dating 配置隔离
  event_partner.json     # B：相同 schema 的第二场景
web/
  index.html             # B：三个视图的单页入口
  app.js                 # B：API/SSE/问题卡/审批与事件渲染
  styles.css             # B：可读布局和状态样式
fixtures/v2/             # B：合成用户、候选、可重放事件
tests/                   # 两人按所属模块编写
scripts/dev.py           # A：启动/关闭 8000、8001、8002
scripts/smoke.py         # A/B：同协议端到端验收
docs/quickstart.md        # A：启动与固定版本
docs/demo-runbook.md      # B：实际最终版演示脚本
```

目录名是建议，不覆盖已有 `demo/`、`core/` 和 `scenarios/`。实现时先检查是否发生新修改。新入口在 README 中明确；不要把旧页面能打开当作新系统验收通过。

## T1 数据契约和候选筛选

**负责人：A；B 共同 review 数据夹具。**

**Files:** 创建 `contracts.py`、`scenario.py`、`matching.py`、`tests/test_matching_v2.py`；B 创建两份 scenario 和 fixtures。

**Interfaces:**

- `load_scenario(path: Path) -> ScenarioSpec`
- `evaluate_requirement(requirement: Requirement, facts: dict) -> GateResult`，status 为 pass/fail/unknown。
- `rank_candidates(profile: PrivateProfile, candidates: list[PublicProfile], spec: ScenarioSpec) -> list[CandidateMatch]`
- 共享 `SessionState`、`Decision`、`Proposal`、`Question` 等类型定义以 design.md 为准，模型 extra fields 禁止。

- [ ] 写测试：A 的 hard `start_in_days <= 30`，B 为 90，结果 fail；B 未知则 unknown；标为 ask 时可进入询问；空需求不返回满分。
- [ ] `uv run pytest tests/test_matching_v2.py -q`，确认新增测试先失败。
- [ ] 实现受限操作符与公开数据排序；候选按 min directional fit 降序，平分按 agent_id。
- [ ] 同命令通过；确认 cofounder 和 event_partner 都能载入且未知字段报错。
- [ ] 提交一个契约版本，B 从此只消费这一份 schema。验收输出为可读候选 JSON。

## T2 可恢复协商和幂等

**负责人：A。**

**Files:** `repository.py`、`negotiation.py`、`tests/test_negotiation_resume.py`、`tests/test_event_idempotency.py`。

**Interfaces:**

- B 提供 `AgentPolicy.decide(context: AgentContext) -> Decision`；先用 FakePolicy。
- `start_session(request: StartRequest, principal: Principal) -> SessionView`
- `answer_question(session_id: str, answer: AnswerRequest, principal: Principal) -> SessionView`
- `apply_peer_message(message: PeerMessage, peer: PeerPrincipal) -> PeerReply`
- `read_events(session_id: str, after_seq: int, principal: Principal) -> list[PublicEvent]`

- [ ] 测试 `test_resume_keeps_session`：WAITING_INPUT → 重建服务/图对象 → 正确 owner 回答 → session_id 不变、profile overlay version 增加、进入 NEGOTIATING。
- [ ] 测试 `test_stale_and_duplicate_answers`：重复 message_id 不增轮次；新消息但旧 revision 返回冲突；B 不能回答 A 的问题。
- [ ] 测试 6 次决策上限和 2 次追问上限，耗尽后明确 NO_MATCH/需人工结束，不无限循环。
- [ ] 运行上述测试确认失败，再实现 SQLite 会话、事件和 checkpoint；数据库用唯一 message_id 和事务控制 revision。
- [ ] 运行 `uv run pytest tests/test_negotiation_resume.py tests/test_event_idempotency.py -q`，全部通过后提交。

**实现注意：** 读取 checkpoint 不能代替 owner 授权校验；interrupt 前的外部消息必须幂等。graph state 保存引用/业务状态，不把对端整个私有 profile 带入。

## T3 A2A transport 和结果批准

**负责人：A；B 消费响应结构。**

**Files:** `transport_a2a.py`、`privacy.py`、`approvals.py`、`tests/test_a2a_roundtrip.py`、`tests/test_approvals.py`、`tests/test_privacy.py`。

**Interfaces:**

- `Transport.exchange(peer: AgentEndpoint, message: PeerMessage) -> PeerReply`
- `project_public(profile: PrivateProfile, spec: ScenarioSpec) -> PublicProfile`
- `proposal_digest(proposal: Proposal, participants: list[str], profile_versions: dict[str,int], disclosure: dict) -> str`
- `approve(session_id: str, request: ApprovalRequest, principal: Principal) -> SessionView`

- [ ] 写独立进程测试：8001/8002 Agent Card 可读取，实际 HTTP SendMessage 成功；input-required 后补消息保持各端 task/context 映射。
- [ ] 写批准测试：仅 A 批准不能出 artifact；B 改条件后 A 的旧批准无效；双方同 digest 才可 CONNECTED；重复批准只能生成一个结果。
- [ ] 写隐私测试：A/B 各自 canary、联系方式不出现在未授权对端消息和 public events；非法字段/外部 URL/伪造 OWNER_APPROVAL 被拒绝。
- [ ] 固定已验证 SDK 版本，按 evidence/probe_runtime.py 的现代 API 接入；不要混用旧 v0.3 示例。
- [ ] `uv run pytest tests/test_a2a_roundtrip.py tests/test_approvals.py tests/test_privacy.py -q` 通过；保存一次真实 HTTP trace 后提交。

## T4 模型和产品交互

**负责人：B；A 提供 server 接口实现。**

**Files:** `policy.py`、`profile_builder.py`、`artifacts.py`、`web/*`、`tests/test_policy_contract.py`、`tests/test_profile_builder.py`。

**Interfaces:**

- `build_profile(text: str, spec: ScenarioSpec) -> ProfileDraft`；只返回预览，用户确认后才发布。
- `AgentPolicy.decide(context: AgentContext) -> Decision`；输入只包含本方信息和已授权对端材料。
- `build_artifact(session: ConfirmedSession) -> IntroductionArtifact`；未双确认的 Session 无法调用。
- UI 仅消费 design.md 的 owner API 和 PublicEvent。事件字段固定：seq、session_id、timestamp、actor、type、public_summary、payload、mode。

- [ ] 测试坏 JSON、schema 之外字段、未知枚举、越权硬约束变更；最多一次结构修复仍失败则保留错误，不伪造成功。
- [ ] 测试未知事实保留 unknown；“愿意等 90 天，但要求 AI 产品经验”变成结构化待确认 patch，并默认 session scope。
- [ ] 实现一个现场可用 provider，通过环境变量注入 endpoint/model/key；不在前端存 key；不编造模型可用性。
- [ ] 实现同一 Policy 接口的 deterministic fixture 模式，页面显式显示模式。真实模式出错时询问是否切换，不能静默伪装为真实运行。
- [ ] 创建三视图；问题和批准都有 pending、submitted、conflict、error 状态；采用 textContent 安全渲染外部文本。
- [ ] `uv run pytest tests/test_policy_contract.py tests/test_profile_builder.py -q` 通过；浏览器实际走 A 和 B 两个身份，刷新不重发启动请求。
- [ ] 提交后保存一次真实模型日志（仅计数/延迟/脱敏结果），不记录密钥或私有原文。

## T5 场景复用、集成与发布

**负责人：两人。**

**Files:** 第二场景配置、`tests/test_scenario_contract.py`、`tests/test_end_to_end.py`、启动/烟测脚本、quickstart、demo-runbook、THIRD_PARTY_NOTICES。

- [ ] 参数化相同契约测试：cofounder 和 event_partner 都能构建画像、产生候选、发问题、继续协商、双确认产出 artifact。核心目录不出现按这两个场景 ID 特判的分支。
- [ ] 主流程一遍同意、一遍拒绝；验证拒绝没有联系方式披露；14:00 后修改条件使之前批准失效的分支也需通过。
- [ ] 接入实际端口并重启一个服务；浏览器刷新后从保存事件恢复；保存实际 smoke 输出。
- [ ] 运行 `uv run pytest tests/test_matching_v2.py tests/test_negotiation_resume.py tests/test_event_idempotency.py tests/test_a2a_roundtrip.py tests/test_approvals.py tests/test_privacy.py tests/test_policy_contract.py tests/test_profile_builder.py tests/test_scenario_contract.py tests/test_end_to_end.py -q`。
- [ ] 补 README 真实命令、环境变量、默认模式、合成数据说明；运行 `uv run python scripts/smoke.py --mode deterministic`，再在 endpoint 可用时跑 live。
- [ ] B 按 A 的 quickstart 从新虚拟环境启动；A 按 B 的演示手册跑一遍。目标启动 ≤10min、重置 ≤30s，这些是验收目标而非当前实测成绩。
- [ ] 保存真实成功 trace、失败 trace、视频和截图，填写 delivery.md 验收矩阵；确定最终 commit 并标记 `v0.1.0-hackathon`。

## 时间不足时如何裁剪

| 触发点 | 动作 | 仍需保留 |
|---|---|---|
| 10:15 checkpoint 仍未工作 | 复用已验证 probe 模式；再给 30min，之后换显式 SQLite 状态机 | 原会话恢复、幂等、用户权限 |
| 12:00 HTTP 双进程未通 | 两人暂停新功能一起打通最小 A2A；去掉 fancy UI 和多候选并行 | 真实两端通信，不把单 prompt 双角色称为独立 A2A |
| 13:30 主流程不稳定 | 第二场景仅保留契约测试，去掉第二场景 UI、ICS、第二 provider | 一套可交付主流程和另一配置的技术证据 |
| 14:00 模型不稳定 | 真实模型仅用于画像/建议；协商由确定性约束执行，明确展示实际模式 | 模型调用证据和真实状态流，不能把录制内容冒充 live |
| 14:30 任一核心步骤缺失 | 冻结范围、记录 limitation，录制最稳定可运行分支 | 启动说明、结果定义、真实完成范围 |

## 粗略工作量与后续

只剩明天的方案最多约 10 人小时用于功能开发与联调，另有约 5 人小时用于冻结前修复、复现、录屏、提交和故障缓冲，午餐另计；这是紧张的工程预算。主成本来自协议和状态语义集成，而非 HTML 页面数。今天可以开工时，用推荐排期把这些集成成本提前消化。

赛后优先级：外部 Agent 接入/SDK 契约 → 用户级账户和持久权限 → 多会话与成本控制 → 更强输入与对端校验 → 按具体行业验证匹配效果。不要先扩大场景数而忽略一个真实用户能否完成介绍。
