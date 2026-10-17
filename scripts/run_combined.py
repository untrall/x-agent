#!/usr/bin/env python3
"""Combined flow: admin-view matching -> user-view agent negotiation.

Phase A (admin view): run the core matching engine (core/match.py) over
data/personas.json and rank the pool for one protagonist. The top-N
candidates and the hard-filter casualties are the admin story.

Phase B (bridge): translate the protagonist + top-N candidates into
per-agent configs for the decentralized negotiation runtime
(src/xagent/mvp). Persona facts map onto scenario fields:

    same_city   <- candidate.city == protagonist.city   (preloaded)
    non_smoker  <- not candidate.facts.smoker           (preloaded)
    long_term_same_city <- confirmed live by each owner (WITHHELD)

long_term_same_city is deliberately not preloaded: the scenario followup asks
the protagonist live, and each candidate's owner is then asked to
confirm the fact -- the loop-in beat. In --auto mode this driver
uses explicit scripted demo answers (the followup answer
defaults to yes and is overridable); for the live venue demo, use
--configs-only and answer by hand in four TUI windows.

Phase C (user view): start N+1 headless agent processes, broadcast
the demand, drive questions/approvals to completion, and write a
combined transcript (TRANSCRIPT.md + result.json) into the run dir.

At the choice stage the protagonist may chat with each candidate's
agent, which answers from its own owner's persona via a real model
(--chat, LLM_* env). --auto-chat asks preset questions before picking
the #1 candidate; --owner-choice leaves chat and /choose to the human
in the protagonist's TUI window.

    .venv/bin/python scripts/run_combined.py
    .venv/bin/python scripts/run_combined.py --chat --auto-chat
    .venv/bin/python scripts/run_combined.py --configs-only
    .venv/bin/python scripts/run_combined.py --user azhe --top 3 --keep
"""

import argparse
import json
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.match import apply_feedback, hard_filter, rank_pool  # noqa: E402
from scripts.build_demo_data import FEEDBACK  # noqa: E402

LAUNCHER = ROOT / "scripts" / "run_agent.py"
SCENARIO_PATH = ROOT / "configs" / "mvp" / "dating-match.json"
TERMINAL = {"CONNECTED", "NO_MATCH", "DECLINED", "REJECTED", "CANCELLED",
            "ERROR"}


# ---------------------------------------------------------------- phase A

def admin_ranking(user_id: str, top: int, feedback: bool = True) -> dict:
    """Rank the pool; with feedback, apply the same 「太安静了」 step as the
    web demo (demo/) so act 2 starts from the ranking the audience last saw.
    The #1 candidate is the one the protagonist will actually meet."""
    personas = json.loads((ROOT / "data" / "personas.json").read_text())
    scenario = json.loads((ROOT / "scenarios" / "dating.json").read_text())
    by_id = {p["id"]: p for p in personas}
    user = by_id[user_id]
    pool = [p for p in personas if p["id"] != user_id]
    default = rank_pool(user, pool, scenario)
    ranked = (apply_feedback(default, FEEDBACK["trait_min"], FEEDBACK["penalty"])
              if feedback else default)
    passed = [r for r in ranked if r["passed"]]
    filtered = []
    for p in pool:
        failed = hard_filter(user, p)
        if failed:
            filtered.append({"candidate": by_id[p["id"]], "failed_rules": failed})
    return {"user": user, "top": passed[:top],
            "runner_up": passed[top:top + 2], "filtered": filtered,
            "default_top": [r for r in default if r["passed"]][:top],
            "feedback": FEEDBACK if feedback else None}


def demand_requirements(user: dict) -> list:
    """Hard requirements for the broadcast, derived from the user persona."""
    facts = user.get("facts", {})
    reqs = []
    if facts.get("require_same_city"):
        reqs.append({"field": "same_city", "op": "eq", "value": True})
    if facts.get("dealbreaker_smoking"):
        reqs.append({"field": "non_smoker", "op": "eq", "value": True})
    return reqs


# ---------------------------------------------------------------- phase B

def free_ports(count: int) -> list:
    socks = []
    try:
        for _ in range(count):
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            socks.append(s)
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


# Scripted stand-in for a human answer in automatic demos only.
# Current city and other persona facts do not imply future living plans.
AUTO_LONG_TERM_SAME_CITY = True


def persona_brief(person: dict) -> dict:
    """What a candidate's own agent may draw on when chatting.

    Hard facts (facts.*) stay out: they go through the negotiation
    protocol and owner confirmation, never through free chat.
    """
    axes = json.loads((ROOT / "scenarios" / "dating.json").read_text())["trait_axes"]
    labels = {a["key"]: a["label"] for a in axes}
    # Ranking rows carry a trimmed candidate; read the full persona by id.
    full = {p["id"]: p for p in json.loads((ROOT / "data" / "personas.json").read_text())}
    person = full.get(person.get("id"), person)
    brief = {k: person[k] for k in ("name", "age", "city", "job", "essence",
                                   "values", "interests", "needs", "offers")
             if k in person}
    brief["traits"] = {labels.get(k, k): v for k, v in person.get("traits", {}).items()}
    return brief


def build_configs(admin: dict, workdir: Path) -> list:
    scenario = json.loads(SCENARIO_PATH.read_text())
    user = admin["user"]
    people = [user] + [row["candidate"] for row in admin["top"]]
    ports = free_ports(len(people))
    configs = []
    for i, person in enumerate(people):
        n = i + 1
        facts = {
            "same_city": person.get("city") == user.get("city"),
            "non_smoker": not person.get("facts", {}).get("smoker", False),
        }
        # long_term_same_city intentionally withheld -> negotiated live (followup).
        cfg = {
            "agent_id": f"agent-{n}",
            "owner_id": f"owner-{n}",
            "name": person["name"],
            "host": "127.0.0.1",
            "port": ports[i],
            "database": str(workdir / f"agent-{n}.sqlite3"),
            "token": f"demo-token-{n}",
            "owner_token": f"demo-owner-{n}",
            "scenario": scenario,
            "profile": {
                "facts": facts,
                "public_fields": ["same_city", "non_smoker", "long_term_same_city"],
                "tags": person.get("interests", [])[:3],
                "description": person.get("essence", ""),
                "persona": persona_brief(person),
            },
            "peers": [
                {
                    "agent_id": f"agent-{m + 1}",
                    "name": people[m]["name"],
                    "url": f"http://127.0.0.1:{ports[m]}",
                    "token": f"demo-token-{m + 1}",
                }
                for m in range(len(people))
                if m != i
            ],
        }
        path = workdir / f"agent-{n}.json"
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))
        configs.append(cfg)
    return configs


# ---------------------------------------------------------------- phase C

class AgentProc:
    def __init__(self, cfg: dict, workdir: Path, chat: bool = False):
        self.cfg = cfg
        self.workdir = workdir
        self.n = int(cfg["agent_id"].split("-")[-1])
        self.url = f"http://127.0.0.1:{cfg['port']}"
        self.log = (workdir / f"process-{self.n}.log").open("a")
        self.proc = None
        # Only candidates answer chat; the protagonist only asks.
        self.chat = chat and self.n > 1

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(LAUNCHER), "--config",
             str(self.workdir / f"agent-{self.n}.json"),
             "--headless", "--mode", "deterministic"]
            + (["--chat-model"] if self.chat else []),
            cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT,
        )

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)

    def call(self, method: str, path: str, body: dict | None = None) -> dict:
        r = httpx.request(
            method, self.url + path,
            headers={"Authorization": f"Bearer {self.cfg['owner_token']}"},
            # Answer interpretation may take two 20-second model requests
            # (including schema repair); don't abandon the owner operation early.
            json=body, timeout=50 if path == '/owner/answers' else 10, trust_env=False)
        r.raise_for_status()
        return r.json()

    def state(self) -> dict:
        return self.call("GET", "/owner/state")

    def healthy(self) -> bool:
        # proc is None when attached to an agent someone else started (TUI).
        if self.proc is not None and self.proc.poll() is not None:
            return False
        try:
            return httpx.get(self.url + "/health", timeout=0.3,
                             trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False


def wait_for(predicate, label: str, timeout: float = 30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise TimeoutError(f"timed out: {label}")


AUTO_CHAT = ["{name}周末一般喜欢怎么过？",
             "{name}觉得两个人在一起，最重要的是什么？"]


def wait_chat_replies(requester, expected: int, timeout: float = 90) -> None:
    def done():
        events = requester.state()["events"]
        return sum(e["type"] == "CHAT_REPLY" for e in events) >= expected
    wait_for(done, "chat replies", timeout=timeout)


_focused = {"pane": None}


def focus_chooser(target: str, req_sessions: list, waiting_on: list | None = None) -> None:
    """Give the keyboard to whoever must act next: someone who has to answer
    a question first, then the chosen candidate while they consider 阿哲's
    choice, otherwise 阿哲 (pane 0). Pane n-1 shows agent-n
    (see scripts/demo_tui.sh)."""
    awaiting = next((s for s in req_sessions if s["state"] == "PENDING_APPROVAL"
                     and "agent-1" in s.get("approvals", [])), None)
    if waiting_on:
        pane = int(waiting_on[0].split("-")[-1]) - 1
    else:
        pane = int(awaiting["peer_id"].split("-")[-1]) - 1 if awaiting else 0
    if pane != _focused["pane"]:
        subprocess.run(["tmux", "select-pane", "-t", f"{target}.{pane}"], check=False)
        _focused["pane"] = pane


def drive(agents: list, admin: dict, followup_answer: str,
          delay: float = 0.0, auto_chat: bool = False,
          owner_choice: bool = False, tmux_target: str | None = None) -> dict:
    """Auto-owner: use scripted demo answers, then pick one.

    Once every candidate has reached a proposal, the protagonist chooses
    exactly one. owner_choice leaves that to the human (chat with @名字,
    then /choose in the TUI); otherwise this driver optionally asks the
    AUTO_CHAT questions (auto_chat) and chooses the #1 ranked candidate.
    A candidate's owner approves only after the protagonist has approved
    their pair, so declined candidates never approve. Result: one meeting.

    delay pauses after each owner action so a watching audience (attached
    TUI windows) can follow every step.
    """
    user = admin["user"]
    people = {}
    roster = [user] + [r["candidate"] for r in admin["top"]]
    for i, p in enumerate(roster):
        people[f"agent-{i + 1}"] = p
    requester = agents[0]
    demand_text = "想找一位同城、不抽烟的约会对象，先从聊天开始认识。"
    requester.call("POST", "/owner/requests",
                   {"text": demand_text,
                    "requirements": demand_requirements(user)})
    time.sleep(delay)

    answered, decided, chose = set(), set(), False
    # A human deciding in the TUI may take as long as the pitch needs.
    deadline = time.monotonic() + (3600 if owner_choice else 300)
    while time.monotonic() < deadline:
        waiting_on = []  # agents whose owner must answer (manual demo)
        for agent in agents:
            for q in agent.state()["questions"]:
                if q.get("answered") or q["question_id"] in answered:
                    continue
                if owner_choice:
                    # Real people answer in their own window; just point the
                    # keyboard there and wait.
                    waiting_on.append(agent.cfg["agent_id"])
                    continue
                if q.get("kind") == "additional_requirements":
                    text = followup_answer
                elif q.get("field") == "long_term_same_city":
                    text = "是" if AUTO_LONG_TERM_SAME_CITY else "否"
                else:
                    continue
                agent.call("POST", "/owner/answers",
                           {"question_id": q["question_id"], "text": text,
                            "expected_revision": q["revision"], "proxy": True})
                answered.add(q["question_id"])
                time.sleep(delay)
        req_sessions = requester.state()["sessions"]
        all_proposed = len(req_sessions) == len(agents) - 1 and all(
            s["state"] == "PENDING_APPROVAL" or s["state"] in TERMINAL
            for s in req_sessions)
        if all_proposed and not chose and not owner_choice:
            pending = {s["peer_id"]: s for s in req_sessions
                       if s["state"] == "PENDING_APPROVAL"}
            if auto_chat:
                sent = 0
                for template in AUTO_CHAT:
                    for peer_id, s in pending.items():
                        name = people[peer_id]["name"]
                        requester.call("POST", "/owner/chat",
                                       {"session_id": s["session_id"],
                                        "text": template.format(name=name)})
                        sent += 1
                        time.sleep(delay)
                    wait_chat_replies(requester, sent)
                    time.sleep(delay)
            top = next(f"agent-{i + 2}" for i in range(len(admin["top"]))
                       if f"agent-{i + 2}" in pending)
            requester.call("POST", "/owner/choose",
                           {"session_id": pending[top]["session_id"]})
            chose = True
            time.sleep(delay)
        if tmux_target:
            focus_chooser(tmux_target, req_sessions, waiting_on)
        for agent in agents[1:]:
            if owner_choice:
                break  # two-way consent: the chosen candidate decides in their own window
            me = agent.cfg["agent_id"]
            for s in agent.state()["sessions"]:
                key = (me, s["session_id"])
                # Approve only once the protagonist has approved this pair.
                if s["state"] == "PENDING_APPROVAL" and s.get("proposal") \
                        and "agent-1" in s.get("approvals", []) \
                        and key not in decided:
                    agent.call("POST", "/owner/approvals",
                               {"session_id": s["session_id"], "approve": True,
                                "proposal_digest": s["proposal"]["digest"],
                                "expected_revision": s["revision"]})
                    decided.add(key)
                    time.sleep(delay)
        states = [s["state"] for s in requester.state()["sessions"]]
        if states and all(st in TERMINAL for st in states):
            break
        time.sleep(0.3)
    return {"answered": sorted(answered), "decided": len(decided)}


# ---------------------------------------------------------------- output

def chosen_name(admin: dict, snaps: dict) -> str:
    """The candidate the protagonist ended up meeting (not necessarily #1);
    with two-way consent an earlier choice may have declined."""
    rows = [(row["candidate"]["name"],
             next((s for s in snaps["agent-1"]["sessions"]
                   if s["peer_id"] == f"agent-{i + 2}"), {}))
            for i, row in enumerate(admin["top"])]
    for name, sess in rows:
        if sess.get("state") == "CONNECTED":
            return name
    for name, sess in rows:
        if "agent-1" in sess.get("approvals", []):
            return name
    return "另一位"


def write_transcript(admin: dict, agents: list, workdir: Path) -> dict:
    user = admin["user"]
    snaps = {a.cfg["agent_id"]: a.state() for a in agents}
    req_sessions = {s["peer_id"]: s for s in snaps["agent-1"]["sessions"]}
    chosen = chosen_name(admin, snaps)
    result = {"user": user["name"], "ranking": [], "sessions": {},
              "artifacts": {}}
    lines = [f"# 结合演示：{user['name']}的匹配 → 协商全记录", "",
             "## 第一幕 · 管理员视角（匹配引擎 core/match.py）", "",
             "引擎对候选池完成硬门过滤 + 双向契合打分，排名如下：", ""]
    fb = admin.get("feedback")
    if fb:
        default = "、".join(f"{r['candidate']['name']} {r['score']:.3f}"
                            for r in admin["default_top"])
        lines += [f"默认排名：{default}。", "",
                  f"{user['name']}反馈：「{fb['text']}」{fb['note']}", "",
                  "反馈后的排名（第二幕从这里接着走）：", ""]
    for i, row in enumerate(admin["top"], 1):
        c = row["candidate"]
        result["ranking"].append(
            {"rank": i, "id": c["id"], "name": c["name"], "score": row["score"]})
        lines.append(f"{i}. **{c['name']}**（{c['job']} · {c['city']}）"
                     f" — 契合分 **{row['score']:.3f}**")
        for reason in row.get("reasons", [])[:3]:
            lines.append(f"   - {reason}")
    for f in admin["filtered"]:
        lines.append(f"- ❌ {f['candidate']['name']} 被硬门淘汰："
                     f"{'；'.join(f['failed_rules'])}")
    lines += ["", "## 第二幕 · 用户视角（去中心化协商 src/xagent/mvp）", "",
              "上榜的候选各自由自己的 Agent 出面，与主角的 Agent 逐一核对"
              "硬条件、补问画像未定的偏好、互发提案。所有提案到齐后，"
              f"{user['name']}可以先和各位候选的 Agent 聊聊（对方 Agent 按"
              f"本人画像用真模型回答），再选定一位、其余婉拒——最终只见一个人。",
              ""]
    for i, row in enumerate(admin["top"], 1):
        c = row["candidate"]
        peer_id = f"agent-{i + 1}"
        sess = req_sessions.get(peer_id, {})
        result["sessions"][c["name"]] = sess.get("state")
        result["artifacts"][c["name"]] = sess.get("artifact")
        lines.append(f"### 候选 {i}：{c['name']} — 最终状态：{sess.get('state')}")
        lines.append("")
        events = [e for e in snaps["agent-1"]["events"]
                  if e.get("peer_id") == peer_id]
        events += [e for e in snaps[peer_id]["events"]
                   if e.get("peer_id") == "agent-1"]
        events.sort(key=lambda e: e.get("timestamp", ""))
        for e in events:
            lines.append(f"- `{e.get('type')}` {e.get('summary')}")
        art = sess.get("artifact")
        if art:
            lines.append(f"- 🎉 **{art['title']}**已生成（digest "
                         f"{art['proposal_digest'][:12]}…）：{art['next_step']}")
        elif sess.get("state") == "REJECTED":
            lines.append(f"- 条件都对上了，但{user['name']}选定了{chosen}，"
                         "婉拒了这份提案。")
        lines.append("")
    (workdir / "TRANSCRIPT.md").write_text("\n".join(lines))
    (workdir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2))
    render_dialogue(admin, snaps, workdir)
    return result


def new_workdir(user):
    return ROOT / '.local' / 'combined' / f'{user}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:8]}'


def main():
    parser = argparse.ArgumentParser(
        description="管理员排名 → 用户视角协商的结合演示")
    parser.add_argument("--user", default="azhe")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--followup-answer", default="是",
                        help="自动模式下代答补问（现场 TUI 模式请本人回答）")
    parser.add_argument("--configs-only", action="store_true",
                        help="只生成 agent 配置并打印 TUI 启动命令")
    parser.add_argument("--keep", action="store_true",
                        help="跑完不停止 agent 进程")
    parser.add_argument("--attach", metavar="DIR",
                        help="连接 --configs-only 生成目录里已开着的 TUI 窗口，"
                             "自动代答，不另起进程")
    parser.add_argument("--delay", type=float, default=None,
                        help="每个自动操作后的停顿秒数（--attach 默认 1.5，否则 0）")
    parser.add_argument("--no-feedback", action="store_true",
                        help="不应用网页里的「太安静了」反馈，用默认排名")
    parser.add_argument("--wait-enter", action="store_true",
                        help="开始协商前等待按 Enter（先讲完网页第一幕）")
    parser.add_argument("--chat", action="store_true",
                        help="候选 Agent 用真模型按画像回答聊天（读 LLM_* 环境变量；--attach 时由窗口进程决定）")
    parser.add_argument("--auto-chat", action="store_true",
                        help="三选一前自动问每位候选两个预设问题（隐含 --chat）")
    parser.add_argument("--owner-choice", action="store_true",
                        help="三选一交给真人：主角窗口里选人聊天、选定，被选中的候选在自己窗口里接受或婉拒")
    parser.add_argument("--tmux-target", metavar="SESSION:WINDOW",
                        help="键盘跟着决策走：切到被选中候选的窗格，婉拒后切回主角（窗格 n-1 是 agent-n）")
    args = parser.parse_args()
    if args.auto_chat and args.owner_choice:
        parser.error("--auto-chat 和 --owner-choice 只能二选一")
    delay = args.delay if args.delay is not None else (1.5 if args.attach else 0.0)

    admin = admin_ranking(args.user, args.top, feedback=not args.no_feedback)
    if args.attach:
        workdir = Path(args.attach).resolve()
        configs = [json.loads((workdir / f"agent-{n}.json").read_text())
                   for n in range(1, args.top + 2)]
        roster = [admin["user"]] + [r["candidate"] for r in admin["top"]]
        if [c["name"] for c in configs] != [p["name"] for p in roster]:
            sys.exit(f"{workdir} 里的配置与 --user {args.user} --top "
                     f"{args.top} 的排名不一致")
    else:
        workdir = new_workdir(args.user)
        workdir.mkdir(parents=True, exist_ok=True)
        configs = build_configs(admin, workdir)

    print(f"【管理员视角】{admin['user']['name']}的 Top {args.top}"
          f"{'（已应用反馈：' + admin['feedback']['text'] + '）' if admin['feedback'] else ''}：")
    for i, row in enumerate(admin["top"], 1):
        print(f"  {i}. {row['candidate']['name']}  {row['score']:.3f}")
    for f in admin["filtered"]:
        print(f"  ❌ {f['candidate']['name']}：{'；'.join(f['failed_rules'])}")
    print(f"配置目录：{workdir}")

    if args.configs_only:
        print("\n现场 TUI 模式（四个终端分别运行）：")
        for cfg in configs:
            n = cfg["agent_id"].split("-")[-1]
            print(f"  .venv/bin/python scripts/run_agent.py "
                  f"--config {workdir}/agent-{n}.json")
        print("在 agent-1 窗口按 Ctrl+N 输入需求，或 /request "
              "想找一位同城、不抽烟的约会对象")
        print("或自动代答（窗口里能看到每一步）：\n  .venv/bin/python "
              f"scripts/run_combined.py --attach {workdir}"
              f"{' --no-feedback' if args.no_feedback else ''}")
        return

    agents = [AgentProc(cfg, workdir, chat=args.chat or args.auto_chat)
              for cfg in configs]
    try:
        if not args.attach:
            for a in agents:
                a.start()
        for a in agents:
            wait_for(a.healthy, f"{a.cfg['agent_id']} starts", timeout=15)
        if args.wait_enter:
            input(f"{len(agents)} 个 Agent 已上线。讲完网页第一幕后，"
                  "按 Enter 开始第二幕…")
        print(f"【用户视角】{len(agents)} 个 Agent 已上线，开始协商…")
        if args.owner_choice:
            print("需要谁回答时，键盘会自动切到谁的窗口，等本人回答后才继续；"
                  f"提案到齐后，在{admin['user']['name']}的窗口里选人聊天、点「选定」，"
                  "被选中的候选在自己窗口里接受或婉拒。")
        drive(agents, admin, args.followup_answer, delay,
              auto_chat=args.auto_chat, owner_choice=args.owner_choice,
              tmux_target=args.tmux_target)
        result = write_transcript(admin, agents, workdir)
        print("协商结果：")
        for name, state in result["sessions"].items():
            print(f"  {name}: {state}")
        met = [n for n, s in result["sessions"].items() if s == "CONNECTED"]
        print(f"最终见面：{'、'.join(met) or '无'}")
        print(f"全记录：{workdir / 'TRANSCRIPT.md'}")
    finally:
        if not args.keep:
            for a in agents:
                a.stop()




# ---------------------------------------------------------------- dialogue

FIELD_LABELS = {"same_city": "同城", "non_smoker": "不抽烟",
                "long_term_same_city": "进入稳定关系后愿意在同一个城市长期生活"}


def render_dialogue(admin: dict, snaps: dict, workdir: Path) -> None:
    """Render the negotiation as a chat-style dialogue (DIALOGUE.md)."""
    user = admin["user"]
    reqs = demand_requirements(user)
    req_text = "、".join(FIELD_LABELS.get(r["field"], r["field"]) for r in reqs)
    out = [f"# 对话视图：{user['name']}的 Agent × 候选人的 Agent", "",
           "> 自动模式下，标注为「本人」的发言由驱动按演示脚本代答；"
           "现场 TUI 模式下为真人输入。其余皆为 Agent 间真实消息事件。", ""]
    followup_shown = False
    chosen = chosen_name(admin, snaps)
    for i, row in enumerate(admin["top"], 1):
        c = row["candidate"]
        peer_id = f"agent-{i + 1}"
        sess = next((s for s in snaps["agent-1"]["sessions"]
                     if s["peer_id"] == peer_id), {})
        art = sess.get("artifact") or {}
        agreed = (art.get("terms") or {}).get("provider_facts") or {}
        mine = [e for e in snaps["agent-1"]["events"]
                if e.get("peer_id") == peer_id]
        theirs = [e for e in snaps[peer_id]["events"]
                  if e.get("peer_id") == "agent-1"]
        out.append(f"## 与{c['name']}的 Agent（契合分 {row['score']:.3f}）")
        out.append("")
        seen, approvals_shown = set(), set()
        approval_line = {"req": f"**{user['name']}**：提案我看了，批准 ✅",
                         "prov": f"**{c['name']}**：我也批准 ✅"}
        merged = [(e, "req") for e in mine] + [(e, "prov") for e in theirs]
        merged.sort(key=lambda t: t[0].get("timestamp", ""))
        for e, side in merged:
            t = e.get("type")
            key = (t, side, e.get("summary"))
            if key in seen and t not in ("APPROVAL",):
                continue
            seen.add(key)
            if t == "REQUEST_SENT" and side == "req":
                out.append(f"**{user['name']}的 Agent**：你好，我替{user['name']}"
                           f"寻找约会对象。硬条件是：{req_text}。先核对一下？")
            elif t == "FILTER_RESULT" and side == "prov":
                status = (e.get("payload") or {}).get("status")
                if status == "PASS":
                    checks = "、".join(
                        f"{FIELD_LABELS.get(r['field'], r['field'])} ✓"
                        for r in reqs) or "硬条件"
                    out.append(f"**{c['name']}的 Agent**：收到，我在本地核对了"
                               f"——{checks}，都符合。")
                elif status == "UNKNOWN":
                    out.append(f"**{c['name']}的 Agent**：硬条件都对上了，"
                               f"但有一项我这里没有记录，我去问一下本人。")
            elif t == "POLICY_DECISION" and side == "req" \
                    and (e.get("payload") or {}).get("field") == "long_term_same_city":
                if not followup_shown:
                    out.append(f"**系统** → {user['name']}："
                               f"{e.get('summary')}（这是你画像里没定的偏好）")
                    out.append(f"**{user['name']}**：我希望稳定后能在同一个城市长期生活，也希望对方有这个打算。")
                    followup_shown = True
                else:
                    out.append("**系统**：（同一条补问已同步到这条会话）")
            elif t == "QUESTION" and side == "prov":
                out.append(f"**{c['name']}的 Agent** → {c['name']}："
                           f"对方想确认——进入稳定关系后是否愿意在同一个城市长期生活？")
            elif t == "ANSWER" and side == "prov":
                # Automatic demos use the scripted answer if no artifact exists.
                val = agreed.get("long_term_same_city", AUTO_LONG_TERM_SAME_CITY)
                out.append(f"**{c['name']}**："
                           f"{'我愿意，稳定后希望在同一个城市长期生活。' if val else '我暂时没有长期在同一个城市生活的打算。'}")
            elif t == "PROPOSAL" and side == "req":
                out.append(f"**{user['name']}的 Agent**：条件全部对齐，"
                           f"我正式发出一份「见面提案」。")
            elif t == "PENDING_APPROVAL" and side == "req":
                out.append("（提案已送达双方，等待两位本人确认…）")
            elif t == "APPROVAL" and "Owner approved" in (e.get("summary") or ""):
                out.append(approval_line[side])
                approvals_shown.add(side)
            elif t == "CONNECTED" and side == "req":
                # The second approver logs CONNECTED, not APPROVAL.
                for s in ("req", "prov"):
                    if s not in approvals_shown:
                        out.append(approval_line[s])
                out.append(f"🎉 **见面提案达成**——双方 Agent 核对一致、"
                           f"双方本人均已批准，接下来由真人自行联系。")
            elif t == "CHAT_SENT" and side == "req":
                out.append(f"**{user['name']}** → {c['name']}的 Agent："
                           f"{e.get('summary')}")
            elif t == "CHAT_REPLY" and side == "req":
                note = "" if (e.get("payload") or {}).get("ok") else "（未能回答）"
                out.append(f"**{c['name']}的 Agent**{note}：{e.get('summary')}")
            elif t == "REJECTED" and e.get("summary") == "Owner rejected proposal":
                # Whoever's own log says "Owner rejected" is the one who declined.
                if side == "req":
                    out.append(f"**{user['name']}**：条件都对上了，谢谢。不过这次我"
                               f"只想认真认识一位——我选了{chosen}，这份提案就婉拒了。")
                else:
                    out.append(f"**{c['name']}**：谢谢你选我，不过这次我先不接受。")
        out.append("")
    (workdir / "DIALOGUE.md").write_text("\n".join(out))

if __name__ == "__main__":
    main()
