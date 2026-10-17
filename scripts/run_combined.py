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
    kids_open   <- candidate.facts.wants_kids != "no"   (WITHHELD)

kids_open is deliberately not preloaded: the scenario followup asks
the protagonist live, and each candidate's owner is then asked to
confirm the fact -- the loop-in beat. In --auto mode this driver
answers owner questions from persona truth (the followup answer
defaults to yes and is overridable); for the live venue demo, use
--configs-only and answer by hand in four TUI windows.

Phase C (user view): start N+1 headless agent processes, broadcast
the demand, drive questions/approvals to completion, and write a
combined transcript (TRANSCRIPT.md + result.json) into the run dir.

    .venv/bin/python scripts/run_combined.py
    .venv/bin/python scripts/run_combined.py --configs-only
    .venv/bin/python scripts/run_combined.py --user azhe --top 3 --keep
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.match import hard_filter, rank_pool  # noqa: E402

LAUNCHER = ROOT / "scripts" / "run_agent.py"
SCENARIO_PATH = ROOT / "configs" / "mvp" / "dating-match.json"
TERMINAL = {"CONNECTED", "NO_MATCH", "DECLINED", "CANCELLED", "ERROR"}


# ---------------------------------------------------------------- phase A

def admin_ranking(user_id: str, top: int) -> dict:
    personas = json.loads((ROOT / "data" / "personas.json").read_text())
    scenario = json.loads((ROOT / "scenarios" / "dating.json").read_text())
    by_id = {p["id"]: p for p in personas}
    user = by_id[user_id]
    pool = [p for p in personas if p["id"] != user_id]
    ranked = rank_pool(user, pool, scenario)
    passed = [r for r in ranked if r["passed"]]
    filtered = []
    for p in pool:
        failed = hard_filter(user, p)
        if failed:
            filtered.append({"candidate": by_id[p["id"]], "failed_rules": failed})
    return {"user": user, "top": passed[:top],
            "runner_up": passed[top:top + 2], "filtered": filtered}


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


def kids_open(persona: dict) -> bool:
    return persona.get("facts", {}).get("wants_kids") != "no"


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
        # kids_open intentionally withheld -> negotiated live (followup).
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
                "public_fields": ["same_city", "non_smoker", "kids_open"],
                "tags": person.get("interests", [])[:3],
                "description": person.get("essence", ""),
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
    def __init__(self, cfg: dict, workdir: Path):
        self.cfg = cfg
        self.workdir = workdir
        self.n = int(cfg["agent_id"].split("-")[-1])
        self.url = f"http://127.0.0.1:{cfg['port']}"
        self.log = (workdir / f"process-{self.n}.log").open("a")
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            [sys.executable, str(LAUNCHER), "--config",
             str(self.workdir / f"agent-{self.n}.json"),
             "--headless", "--mode", "deterministic"],
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
            json=body, timeout=10, trust_env=False)
        r.raise_for_status()
        return r.json()

    def state(self) -> dict:
        return self.call("GET", "/owner/state")

    def healthy(self) -> bool:
        if self.proc.poll() is not None:
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


def drive(agents: list, admin: dict, followup_answer: str) -> dict:
    """Auto-owner: answer questions from persona truth, approve proposals."""
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

    answered, approved = set(), set()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        for agent in agents:
            for q in agent.state()["questions"]:
                if q.get("answered") or q["question_id"] in answered:
                    continue
                if q.get("kind") == "additional_requirements":
                    text = followup_answer
                elif q.get("field") == "kids_open":
                    text = "是" if kids_open(people[agent.cfg["agent_id"]]) else "否"
                else:
                    continue
                agent.call("POST", "/owner/answers",
                           {"question_id": q["question_id"], "text": text,
                            "expected_revision": q["revision"]})
                answered.add(q["question_id"])
        for agent in agents:
            for s in agent.state()["sessions"]:
                key = (agent.cfg["agent_id"], s["session_id"])
                if s["state"] == "PENDING_APPROVAL" and s.get("proposal") \
                        and key not in approved:
                    agent.call("POST", "/owner/approvals",
                               {"session_id": s["session_id"], "approve": True,
                                "proposal_digest": s["proposal"]["digest"],
                                "expected_revision": s["revision"]})
                    approved.add(key)
        states = [s["state"] for s in requester.state()["sessions"]]
        if states and all(st in TERMINAL for st in states):
            break
        time.sleep(0.3)
    return {"answered": sorted(answered), "approved": len(approved)}


# ---------------------------------------------------------------- output

def write_transcript(admin: dict, agents: list, workdir: Path) -> dict:
    user = admin["user"]
    snaps = {a.cfg["agent_id"]: a.state() for a in agents}
    req_sessions = {s["peer_id"]: s for s in snaps["agent-1"]["sessions"]}
    result = {"user": user["name"], "ranking": [], "sessions": {},
              "artifacts": {}}
    lines = [f"# 结合演示：{user['name']}的匹配 → 协商全记录", "",
             "## 第一幕 · 管理员视角（匹配引擎 core/match.py）", "",
             "引擎对候选池完成硬门过滤 + 双向契合打分，排名如下：", ""]
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
              "硬条件、补问画像未定的偏好、互发提案；双方本人批准后生成"
              "见面提案。", ""]
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
        lines.append("")
    (workdir / "TRANSCRIPT.md").write_text("\n".join(lines))
    (workdir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2))
    render_dialogue(admin, snaps, workdir)
    return result


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
    args = parser.parse_args()

    admin = admin_ranking(args.user, args.top)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    workdir = ROOT / ".local" / "combined" / f"{args.user}-{stamp}"
    workdir.mkdir(parents=True, exist_ok=True)
    configs = build_configs(admin, workdir)

    print(f"【管理员视角】{admin['user']['name']}的 Top {args.top}：")
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
        return

    agents = [AgentProc(cfg, workdir) for cfg in configs]
    try:
        for a in agents:
            a.start()
        for a in agents:
            wait_for(a.healthy, f"{a.cfg['agent_id']} starts", timeout=15)
        print("【用户视角】4 个 Agent 已上线，开始协商…")
        drive(agents, admin, args.followup_answer)
        result = write_transcript(admin, agents, workdir)
        print("协商结果：")
        for name, state in result["sessions"].items():
            print(f"  {name}: {state}")
        print(f"全记录：{workdir / 'TRANSCRIPT.md'}")
    finally:
        if not args.keep:
            for a in agents:
                a.stop()




# ---------------------------------------------------------------- dialogue

FIELD_LABELS = {"same_city": "同城", "non_smoker": "不抽烟",
                "kids_open": "对要孩子持开放态度"}


def render_dialogue(admin: dict, snaps: dict, workdir: Path) -> None:
    """Render the negotiation as a chat-style dialogue (DIALOGUE.md)."""
    user = admin["user"]
    reqs = demand_requirements(user)
    req_text = "、".join(FIELD_LABELS.get(r["field"], r["field"]) for r in reqs)
    out = [f"# 对话视图：{user['name']}的 Agent × 候选人的 Agent", "",
           "> 自动模式下，标注为「本人」的发言由驱动按画像代答；"
           "现场 TUI 模式下为真人输入。其余皆为 Agent 间真实消息事件。", ""]
    followup_shown = False
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
        seen = set()
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
                        f"{FIELD_LABELS.get(k, k)} ✓" for k in agreed
                        if k != "kids_open") or "硬条件"
                    out.append(f"**{c['name']}的 Agent**：收到，我在本地核对了"
                               f"——{checks}，都符合。")
                elif status == "UNKNOWN":
                    out.append(f"**{c['name']}的 Agent**：硬条件都对上了，"
                               f"但有一项我这里没有记录，我去问一下本人。")
            elif t == "POLICY_DECISION" and side == "req" \
                    and "是否要求" in (e.get("summary") or ""):
                if not followup_shown:
                    out.append(f"**系统** → {user['name']}："
                               f"{e.get('summary')}（这是你画像里没定的偏好）")
                    out.append(f"**{user['name']}**：是，要求对方不排斥。")
                    followup_shown = True
                else:
                    out.append("**系统**：（同一条补问已同步到这条会话）")
            elif t == "QUESTION" and side == "prov":
                out.append(f"**{c['name']}的 Agent** → {c['name']}："
                           f"对方想确认——你对要孩子持开放态度吗？")
            elif t == "ANSWER" and side == "prov":
                val = agreed.get("kids_open")
                out.append(f"**{c['name']}**："
                           f"{'是的，我持开放态度。' if val else '这个我比较确定不要。'}")
            elif t == "PROPOSAL" and side == "req":
                out.append(f"**{user['name']}的 Agent**：条件全部对齐，"
                           f"我正式发出一份「见面提案」。")
            elif t == "PENDING_APPROVAL" and side == "req":
                out.append("（提案已送达双方，等待两位本人确认…）")
            elif t == "APPROVAL" and side == "req" \
                    and "Owner approved" in (e.get("summary") or ""):
                out.append(f"**{user['name']}**：提案我看了，批准 ✅")
            elif t == "APPROVAL" and side == "prov" \
                    and "Owner approved" in (e.get("summary") or ""):
                out.append(f"**{c['name']}**：我也批准 ✅")
            elif t == "CONNECTED" and side == "req":
                out.append(f"🎉 **见面提案达成**——双方 Agent 核对一致、"
                           f"双方本人均已批准，接下来由真人自行联系。")
        out.append("")
    (workdir / "DIALOGUE.md").write_text("\n".join(out))

if __name__ == "__main__":
    main()
