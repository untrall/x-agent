# 结合演示：阿哲的匹配 → 协商全记录

## 第一幕 · 管理员视角（匹配引擎 core/match.py）

引擎对候选池完成硬门过滤 + 双向契合打分，排名如下：

1. **林小满**（产品经理 · 上海） — 契合分 **0.935**
   - 林小满能给你：深度交流、倾听、情绪稳定、共同成长
   - 你能给林小满：经济独立、上进心、居家温馨、幽默感
   - 共同看重：成长、诚实、家庭
2. **陈语桐**（设计师 · 上海） — 契合分 **0.590**
   - 陈语桐能给你：深度交流
   - 你能给陈语桐：上进心、幽默感、经济独立
   - 共同看重：成长、诚实、体验
3. **苏晴**（咨询顾问 · 上海） — 契合分 **0.495**
   - 你能给苏晴：经济独立、上进心
   - 共同看重：成长、诚实、家庭
   - 居家倾向很合拍（0.60 / 0.60）
- ❌ 沈亦舟 被硬门淘汰：异地：阿哲在上海、沈亦舟在北京，而一方要求同城
- ❌ 陆蔓 被硬门淘汰：陆蔓吸烟，触发阿哲的 dealbreaker

## 第二幕 · 用户视角（去中心化协商 src/xagent/mvp）

上榜的候选各自由自己的 Agent 出面，与主角的 Agent 逐一核对硬条件、补问画像未定的偏好、互发提案；双方本人批准后生成见面提案。

### 候选 1：林小满 — 最终状态：CONNECTED

- `REQUEST_SENT` Request queued for 林小满
- `REQUEST_RECEIVED` Peer request received
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` 是否要求对方对要孩子持开放态度？
- `POLICY_DECISION` Need to confirm 对要孩子持开放态度
- `QUESTION` 对要孩子持开放态度
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

### 候选 2：陈语桐 — 最终状态：CONNECTED

- `REQUEST_SENT` Request queued for 陈语桐
- `REQUEST_RECEIVED` Peer request received
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` 是否要求对方对要孩子持开放态度？
- `POLICY_DECISION` Need to confirm 对要孩子持开放态度
- `QUESTION` 对要孩子持开放态度
- `FILTER_RESULT` Local filter UNKNOWN
- `POLICY_DECISION` All stated conditions pass
- `ANSWER` Owner answered fact question
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` All stated conditions pass
- `PROPOSAL` Proposal sent
- `POLICY_DECISION` All stated conditions pass
- `PENDING_APPROVAL` Proposal awaits owner approval
- `APPROVAL` Owner approved proposal
- `PENDING_APPROVAL` Proposal awaits owner approval
- `APPROVAL` Peer approved
- `CONNECTED` Both owners approved
- `CONNECTED` Both owners approved
- 🎉 **见面提案**已生成（digest c2e7bbfe5b2f…）：双方自行安排进一步沟通

### 候选 3：苏晴 — 最终状态：CONNECTED

- `REQUEST_SENT` Request queued for 苏晴
- `REQUEST_RECEIVED` Peer request received
- `FILTER_RESULT` Local filter PASS
- `POLICY_DECISION` 是否要求对方对要孩子持开放态度？
- `POLICY_DECISION` Need to confirm 对要孩子持开放态度
- `QUESTION` 对要孩子持开放态度
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
- 🎉 **见面提案**已生成（digest 6970484b9e2b…）：双方自行安排进一步沟通
