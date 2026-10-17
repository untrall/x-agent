# 结合演示：阿哲的匹配 → 协商全记录

## 第一幕 · 管理员视角（匹配引擎 core/match.py）

引擎对候选池完成硬门过滤 + 双向契合打分，排名如下：

默认排名：林小满 0.935、陈语桐 0.590、苏晴 0.495。

阿哲反馈：「她太安静了，我希望对方外向一点。」反馈没有重掷骰子——它把「外向程度」变成了一道门槛偏好，门槛以下的候选人被显式降权。

反馈后的排名（第二幕从这里接着走）：

1. **陈语桐**（设计师 · 上海） — 契合分 **0.590**
   - 陈语桐能给你：深度交流
   - 你能给陈语桐：上进心、幽默感、经济独立
   - 共同看重：成长、诚实、体验
2. **方糖**（电商运营 · 上海） — 契合分 **0.462**
   - 方糖能给你：共同成长
   - 你能给方糖：幽默感、经济独立
   - 共同看重：家庭、体验
3. **林小满**（产品经理 · 上海） — 契合分 **0.421**
   - 林小满能给你：深度交流、倾听、情绪稳定、共同成长
   - 你能给林小满：经济独立、上进心、居家温馨、幽默感
   - 共同看重：成长、诚实、家庭
- ❌ 沈亦舟 被硬门淘汰：异地：阿哲在上海、沈亦舟在北京，而一方要求同城
- ❌ 陆蔓 被硬门淘汰：陆蔓吸烟，触发阿哲的 dealbreaker

## 第二幕 · 用户视角（去中心化协商 src/xagent/mvp）

上榜的候选各自由自己的 Agent 出面，与主角的 Agent 逐一核对硬条件、补问画像未定的偏好、互发提案。所有提案到齐后，阿哲只批准排名第一的一位，其余婉拒——最终只见一个人。

### 候选 1：陈语桐 — 最终状态：CONNECTED

- `REQUEST_SENT` Request queued for 陈语桐
- `REQUEST_RECEIVED` Peer request received
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` 进入稳定关系后是否愿意在同一个城市长期生活？
- `POLICY_DECISION` Need to confirm 进入稳定关系后愿意在同一个城市长期生活
- `QUESTION` 进入稳定关系后愿意在同一个城市长期生活
- `FILTER_RESULT` Local filter UNKNOWN
- `POLICY_DECISION` All stated conditions pass
- `ANSWER` Owner answered fact question
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` All stated conditions pass
- `PROPOSAL` Proposal sent
- `POLICY_DECISION` All stated conditions pass
- `PENDING_APPROVAL` Proposal awaits owner approval
- `PENDING_APPROVAL` Proposal awaits owner approval
- `APPROVAL` Owner approved proposal
- `APPROVAL` Peer approved
- `CONNECTED` Both owners approved
- `CONNECTED` Both owners approved
- 🎉 **见面提案**已生成（digest 6e83dbcbfde7…）：双方自行安排进一步沟通

### 候选 2：方糖 — 最终状态：REJECTED

- `REQUEST_SENT` Request queued for 方糖
- `REQUEST_RECEIVED` Peer request received
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` 进入稳定关系后是否愿意在同一个城市长期生活？
- `POLICY_DECISION` Need to confirm 进入稳定关系后愿意在同一个城市长期生活
- `QUESTION` 进入稳定关系后愿意在同一个城市长期生活
- `FILTER_RESULT` Local filter UNKNOWN
- `POLICY_DECISION` All stated conditions pass
- `ANSWER` Owner answered fact question
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` All stated conditions pass
- `PROPOSAL` Proposal sent
- `POLICY_DECISION` All stated conditions pass
- `PENDING_APPROVAL` Proposal awaits owner approval
- `PENDING_APPROVAL` Proposal awaits owner approval
- `REJECTED` Owner rejected proposal
- `REJECTED` Peer rejected this pair
- 条件都对上了，但阿哲只确认排名第一的陈语桐，婉拒了这份提案。

### 候选 3：林小满 — 最终状态：REJECTED

- `REQUEST_SENT` Request queued for 林小满
- `REQUEST_RECEIVED` Peer request received
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` 进入稳定关系后是否愿意在同一个城市长期生活？
- `POLICY_DECISION` Need to confirm 进入稳定关系后愿意在同一个城市长期生活
- `QUESTION` 进入稳定关系后愿意在同一个城市长期生活
- `FILTER_RESULT` Local filter UNKNOWN
- `POLICY_DECISION` All stated conditions pass
- `ANSWER` Owner answered fact question
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` All stated conditions pass
- `PROPOSAL` Proposal sent
- `POLICY_DECISION` All stated conditions pass
- `PENDING_APPROVAL` Proposal awaits owner approval
- `PENDING_APPROVAL` Proposal awaits owner approval
- `REJECTED` Owner rejected proposal
- `REJECTED` Peer rejected this pair
- 条件都对上了，但阿哲只确认排名第一的陈语桐，婉拒了这份提案。
