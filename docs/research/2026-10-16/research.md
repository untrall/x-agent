# 仓库调研与技术选择

## 结论

两人在一天内可以完成可展示、可复现的通用双边协商内核，但无法同时交付成熟的社交网络、招聘平台、婚恋平台和去中心化基础设施。明天的“通用”应有可检验的含义：**相同通信与状态机，换一份场景配置和数据，就能处理另一类双方供需协商。**

推荐组合：**Python 3.12 + 官方 A2A Python SDK + LangGraph + SQLite + 轻量 Web UI**。复用通信和持久化机制；自行定义少量业务结构、规则校验和场景配置。Tacit、AgentPair、CSNP 提供设计参考，避免把三个不同协议和运行时硬拼在一起。

最有说服力的创新点是：候选条件不完全满足时，系统指出具体未知或可协商项，只向有权回答的人提问，保存回答的适用范围，再在同一会话继续；最终交付双方认可的条件和介绍机会。匹配分数只负责候选排序，不能替代协议达成和人类确认。

## 调研范围与可信度

已读取[原分享](https://chatgpt.com/share/6ad18b30-a7e4-83ee-a9b5-be39191403f4)的公开内容。分享含重复消息、截断回答及已隐藏的工具输出，不能把其中所有推荐当成经过验证的事实。去重后的可见消息保存在 [shared-chat.json](evidence/shared-chat.json)。

实际拉取 23 个仓库，其中包含原调研里直接相关的项目，以及补充的官方 Python SDK 和 Python LangGraph。没有拉取搜索误命中的 TensorRT、Captum、TracIn、NyaaDocs；LangGraph 教程合集和 A2A 镜像由官方仓库替代。PROXAI 拉取后确认不相关，仍保留并列出结论。未额外扩展 CrewAI、AutoGen，因为本次所需机制已能由更小组合覆盖。

证据分为三层：

1. **实测**：实际执行的测试、构建、脚本及其日志。
2. **代码阅读**：入口、状态转换、依赖和边界的静态检查，不等于全量审计。
3. **文档定位**：项目宣称的方向，不据此承诺性能、安全或生产成熟度。

所有判断对应 [sources.md](sources.md) 中固定的 commit，不以星数作为质量指标。

## 候选仓库比较

| 仓库 | 实际定位与主要代码 | 对 X-Agent 的价值 | 结论与验证级别 |
|---|---|---|---|
| `tacit` | TS SDK、relay、intent discovery、匹配、介绍提案；`packages/sdk-ts/src` | 身份/场景画像分离、渐进披露、双向介绍 | 借鉴设计。SDK 41 测试通过但构建失败；评分存在实测缺陷 |
| `agent-pair-protocol` | 已配对双方的加密会话、协商、产物 hash、人工 ratify；协议库和 MCP server | 同一份结果双边确认、授权预算、消息顺序、撤销 | 优先读状态机。157 个选定测试通过；全构建缺 wasm-pack，不能称全项目已跑通 |
| `consent-scoped-agent-negotiation` | Python 库和 CLI，公共选项目录上的有界协商 | 模型与权限分离；scope、轮次预算、明确拒绝路径 | 最清晰的控制逻辑参考；294 通过、3 跳过，离线 demo 成功 |
| `A2A` | 官方协议定义及文档；`specification/a2a.proto` | Agent Card、Task、Message、Artifact、input-required | 作为通信标准；协议本身不提供业务匹配/用户画像 |
| `a2a-python` | 官方 Python 通信 SDK、路由、任务存储、客户端 | 接入独立 Agent，减少自造传输协议 | 推荐运行依赖；本地源码安装和 JSON-RPC 暂停/继续探针成功 |
| `a2a-samples` | 多框架示例；Python helloworld、LangGraph agent | 从最小 server/executor 接入，理解任务更新 | 推荐抄接入模式，注意当前示例 API 与旧教程不同 |
| `a2a-js` | 官方 JS/TS SDK | 团队以 TS 为主或后续做异构客户端时有用 | 代码/manifest 检查，未安装运行 |
| `langgraph` | 持久化状态图、interrupt、Command、SQLite checkpoint | 用户不在线时暂停、输入后恢复 | 推荐运行依赖；跨进程 checkpoint 探针成功 |
| `langgraphjs` | JS/TS 版图执行和 checkpoint 体系 | 全 TS 团队备选 | 不与 Python 版同时引入；未运行 |
| `ai-agents-p2p` | Python 节点、A2A、MCP reader、matching、negotiation、React UI | 模块拆分和独立节点形态很接近目标 | 读 `src/negotiation`。状态机里的 owner_review 位于接受后，未提供目标所需的中途追问恢复状态；依赖重 |
| `JuntoAI-A2A` | Python LangGraph 场景协商、SSE、Next.js UI | 场景配置、过程可视化、结果 receipt | 重要产品参考；`confirmation_node` 调用模型，不等于人类批准；`build_graph` 直接 compile，没有在该入口接 checkpointer |
| `agent-rendezvous` | MCP + Postgres 的发现、对话、互相推荐、介绍同意 | 从 agent 建议到人类联系的产品边界 | `introductions.ts` 有双方 consent 后披露；适合参考流程，代码 AGPL，不直接复制进计划中的宽松许可核心 |
| `hani` | 基于 NegMAS 的人机谈判研究界面 | offer、utility、谈判过程展示 | 更适合正式谈判实验；并非个人 Agent 发现网络；AGPL |
| `jupiter` | Rust/Actix + React 的匹配 POC | 入场访谈和个人画像体验 | `evaluate_compatibility` 在一次模型请求中评估双方画像，不能据此当作独立 Agent 通信已实现 |
| `matchclaws` | 5 个跟踪文件，skill/API 文档与 Python helper | 第三方 agent 接入教程 | 当前公开仓库不是完整可自托管后端；且主要让 agent 自己社交 |
| `in-bed-ai` | Next.js + Supabase 的 agent 约会平台和 MCP 工具 | onboarding、候选卡、mutual match UI | 产品主体是 agent 自己约会，不是代表人协商；部署链条对明天过重 |
| `secure-ai-agent-matching-platform` | 可信 agent store、代理服务编排、安全过滤 | 对端内容校验、能力发现、安全边界 | 匹配的是服务 Agent，不是用户之间的供需；不是直接底座 |
| `agent-protocol` | LangChain 的 runs/threads/store API 规范和生成代码 | 持久会话服务 API 设计 | 与官方 A2A 不同；不再添加第二套对外协议 |
| `agi-agent-protocol` | AGI/e2b 的 task/step 接口规范与 SDK | 通用 agent 调用概念 | 不是双边协商协议，明天不用 |
| `agentchat` | WebSocket agent 频道、提案、身份和市场机制 | 消息观测与代理接入 | README 标明官方公共 server 已关闭；不要依赖公共演示服务 |
| `openclaw` | 大型个人助手 gateway 与插件生态 | 赛后作为外部个人 Agent 的适配端 | 已拉取，未安装；不是明天实现协商核心的必要依赖 |
| `Trialmatch.ai` | 临床试验匹配的垂直应用 | 一般性匹配展示参考 | 领域和数据要求不适合本次；不接入 |
| `PROXAI` | ML 数据溯源和解释性工具 | 无直接价值 | 原搜索误命中，明确排除 |

完整来源、许可证文件和代码入口在 [sources.md](sources.md)。README 写 MIT 但根目录未发现 LICENSE 的项目包括 JuntoAI-A2A 和 ai-agents-p2p；当前建议仅参考思路，不把其代码作为必需依赖。此处记录文件状态，不推断作者未表达的授权。

## 重要纠正

### Tacit 不能直接视为现成的完整闭环

`packages/sdk-ts/src/core/agent.ts` 的 `connect({demo:true})` 会产生固定的模拟 match（87 分），这是明确的演示分支。真实 relay 分支另有实现，因此既不能说整个仓库都是 mock，也不能用这个演示证明真实网络匹配。

`matching/scorer.ts` 的总分计算先对 0–1 加权值做 `Math.round`，再乘 100。本地探针给出：

| 输入 | 加权原值 | 按百分数取整应得 | 实际总分 |
|---|---:|---:|---:|
| 相同 co-founder 寻找条件 | 0.911 | 91 | 100 |
| 不相关 role | 0.611 | 61 | 100 |

因此正常范围内会退化为二值总分。其现有匹配测试主要断言阈值，41 项通过并未发现这个问题。另有 `src/storage/store.ts:13` 的 TS6196 未使用 `Intent` 导入，使 DTS 构建失败。JS bundle 已生成不等于完整包构建成功。[复现日志](evidence/tacit-scoring-probe.log)、[构建日志](evidence/tacit-build.log)。本次不修上游，只记录选型风险。

### 三种确认必须分开

- **模型判断接受**：Agent 认为提案满足其已知要求。
- **用户允许修改条件**：例如只在本次协商允许 90 天后全职；不是把所有未来需求自动改掉。
- **用户批准建立联系**：批准一份确切的结果摘要和披露范围。

JuntoAI 的模型 confirmation、ai-agents-p2p 的 owner_review、AgentPair 的 ratify 分别覆盖不同层面。X-Agent 要显式建模后两种用户行为，不能把字符串 `accept` 当作人类授权。

### CSNP 的通用性有明确范围

它覆盖会议时间、餐厅、供应商等共享选项集合中的选择，不覆盖任意开放式价格、合同和多方协商。它适合借鉴“输出只选合法选项，代码检查权限”的方法。不要因此声称它已经能直接解决所有招聘/婚恋条件。其 MCP adapter 是扩展点，不是已验证的完整 MCP 集成。

### A2A 版本不能混用

本地官方 SDK 源码使用现代 protobuf 类型，例如 `TaskState.TASK_STATE_INPUT_REQUIRED`，JSON-RPC 方法为 `SendMessage`；旧项目和教程常见 v0.3 接口。探针使用 `A2A-Version: 1.0`。不能把旧示例中的 `message/send`、旧 AgentCard 字段和当前 API 混起来。以本次已安装的 commit 或验证后的固定发行版为准，并保存锁文件。[官方规范](https://a2a-protocol.org/latest/specification/)。

## 可运行性验证

| 验证对象 | 命令/方法 | 实际结果 | 尚未证明 |
|---|---|---|---|
| Tacit SDK | `npm ci --ignore-scripts --workspace=packages/sdk-ts`，`npm test`，`npm run build` | 41 passed；构建 exit 1；评分缺陷复现 | relay 多端联通、完整 SDK 类型构建 |
| AgentPair | `pnpm install --frozen-lockfile --ignore-scripts`，protocol build；3 个选定 test 文件 | 157 passed；build 缺 wasm-pack | pairing WASM、MCP native SQLite、完整 e2e |
| CSNP | `uv run --python 3.12 --extra dev pytest -q` | 294 passed、3 skipped | 真实模型表现和 X-Agent 业务适配 |
| CSNP CLI | `csnp demo --task schedule.meeting` | 双方批准、各自 commit、内建传输检查完成 | 普遍隐私保证；选项选择仍有推断通道 |
| LangGraph | [probe_runtime.py](evidence/probe_runtime.py) | 一个进程 interrupt，退出后另一进程读 SQLite、Command resume，session 不变，version 1→2 | 并发竞态、产品授权、跨设备同步 |
| A2A SDK | 同脚本，真实 ASGI JSON-RPC 路由 | Card 读取、同 task/context 的 input-required→completed、artifact | 实际 TCP、多机、异构 SDK 互通、端到端业务 |

本次未读取或使用 API key，没有调用付费模型，也没有向外部 agent、用户或服务发送业务消息。真实模型延迟、质量和费用需在明天第一小时用比赛提供的 endpoint 验证。

探针环境位于工作区 `.research-venv`。依赖快照在 [probe-requirements.txt](evidence/probe-requirements.txt)，A2A 安装自本地固定源码。复现命令见 [delivery.md](delivery.md)。

## 三种实现路径

| 路径 | 适合条件 | 优点 | 成本/风险 |
|---|---|---|---|
| A：官方 A2A + LangGraph + 小业务层，推荐 | 至少一人熟悉 Python | 两个核心机制已探针验证，依赖边界清楚，支持人类暂停/恢复 | 必须自行实现画像、约束、审批与 UI；仍需首次集成 |
| B：全 TS，官方 a2a-js + 自写 SQLite 状态机 | 两人都只熟 TS | 一个语言栈，前后端类型共享 | 本次没有实测该组合；需要补恢复和状态机测试；不要再叠 LangGraph Python |
| C：直接 fork JuntoAI / P2P / Tacit | 已熟悉某一项目且本地全链路已跑通 | 初期页面/模块多 | 现有语义与目标不一致、授权/版本/构建问题，整合可能比小核心更慢 |

推荐 A。若首个 45 分钟无法打通 LangGraph checkpoint，保留 A2A，改用 SQLite 明确状态迁移；不因框架配置消耗整个上午。若 A2A 接入卡住，可先用 `LocalTransport` 做业务测试，但它只能叫本地原型，最终“独立 A2A 框架”的验收仍需 HTTP transport。

## 不投入明天的事项

不做 DID/VC、端到端加密、全网 DHT、向量数据库、支付、真实招聘数据抓取、社交平台消息发送、全局稳定婚姻匹配、自动日历写入和多方博弈。每项都可能有价值，但不影响本次核心闭环成立。

画像保留在各自 Agent 存储，中央注册表只放经过允许的公开摘要。若使用远程 LLM，输入会交给模型服务商处理，因此不能说“原始数据永不离开设备”。对外表述应限定为“原始私有材料不发送给对端 Agent，公开日志不包含私有字段”。这也是 Demo 中要实测的边界。
