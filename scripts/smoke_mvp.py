"""Isolated four-process acceptance demo; this driver is not part of the runtime."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "run_agent.py"


def free_ports(count):
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


class Cluster:
    def __init__(self, directory, scenario="cofounder", facts=None, mode="deterministic", model_env=None):
        self.directory = directory
        self.scenario = scenario
        self.facts = facts
        self.mode = mode
        self.model_env = model_env or {}
        self.ports = free_ports(4)
        self.processes = {}
        self.logs = []
        self.configs = {}

    def start(self, number):
        config_path = self.directory / f"agent-{number}.json"
        if number not in self.configs:
            cfg = json.loads((ROOT / f"configs/mvp/agent-{number}.json").read_text())
            cfg["scenario"] = json.loads((ROOT / f"configs/mvp/{self.scenario}.json").read_text())
            if self.facts is not None:
                cfg["profile"]["facts"] = self.facts[number]
                cfg["profile"]["public_fields"] = list(cfg["scenario"]["fields"])
                cfg["profile"]["description"] = cfg["scenario"].get("name", self.scenario) + ("需求方" if number == 1 else "供给方")
                cfg["profile"]["tags"] = []
            cfg["port"] = self.ports[number - 1]
            cfg["database"] = str(self.directory / f"agent-{number}.sqlite3")
            cfg["profile"]["facts"]["private_note"] = f"PRIVATE-CANARY-{number}"
            for peer in cfg["peers"]:
                peer_number = int(peer["agent_id"].split("-")[-1])
                peer["url"] = f"http://127.0.0.1:{self.ports[peer_number - 1]}"
            self.configs[number] = cfg
            config_path.write_text(json.dumps(cfg))
        log = (self.directory / f"process-{number}.log").open("a")
        self.logs.append(log)
        self.processes[number] = subprocess.Popen(
            [sys.executable, str(LAUNCHER), "--config", str(config_path), "--headless", "--mode", self.mode],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, **self.model_env},
        )
        self.wait(lambda: self.health(number), f"agent {number} starts", timeout=10)

    def health(self, number):
        process = self.processes[number]
        if process.poll() is not None:
            raise AssertionError((self.directory / f"process-{number}.log").read_text())
        try:
            return httpx.get(self.url(number) + "/health", timeout=.3, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    def url(self, number):
        return f"http://127.0.0.1:{self.ports[number - 1]}"

    def call(self, number, method, path, body=None):
        response = httpx.request(method, self.url(number) + path,
            headers={"Authorization": f"Bearer demo-owner-{number}"},
            json=body, timeout=120 if self.mode == "codex" else 5, trust_env=False)
        assert response.is_success, response.text
        return response.json()

    def state(self, number):
        return self.call(number, "GET", "/owner/state")

    def wait(self, predicate, label, timeout=None):
        timeout = timeout if timeout is not None else (120 if self.mode == "codex" else 12)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(.05)
        logs = "\n".join(p.read_text()[-2000:] for p in self.directory.glob("process-*.log"))
        raise AssertionError(f"Timed out: {label}\n{logs}")

    def pending(self, number):
        return [q for q in self.state(number)["questions"] if not q.get("answered", False)]

    def pair(self, number, peer):
        return next((s for s in self.state(number)["sessions"] if s["peer_id"] == peer), None)

    def answer(self, number, q, text):
        return self.call(number, "POST", "/owner/answers", {
            "question_id": q["question_id"], "text": text,
            "expected_revision": q["revision"],
        })

    def stop(self, number):
        process = self.processes.pop(number, None)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def close(self):
        for number in list(self.processes):
            self.stop(number)
        for log in self.logs:
            log.close()


def run_demo(c, demand="寻找创业合伙人，每周至少15小时"):
    assert len({p.pid for p in c.processes.values()}) == 4
    c.call(1, "POST", "/owner/requests", {"text": demand})
    c.wait(lambda: c.pair(1, "agent-2") and c.pair(1, "agent-2")["state"] == "NO_MATCH", "hard constraint rejection")
    q1 = c.wait(lambda: c.pending(1), "requester followup")[0]
    c.answer(1, q1, "是")
    q3 = c.wait(lambda: c.pending(3), "provider 3 owner question")[0]
    q4 = c.wait(lambda: c.pending(4), "provider 4 owner question")[0]
    session3 = c.pair(3, "agent-1")["session_id"]
    c.stop(3)
    c.answer(4, q4, "否")
    c.wait(lambda: c.pair(1, "agent-4")["state"] == "NO_MATCH", "other candidate progresses while 3 offline")
    c.start(3)
    assert c.pending(3)[0]["question_id"] == q3["question_id"]
    assert c.pair(3, "agent-1")["session_id"] == session3
    c.answer(3, q3, "是")
    c.wait(lambda: c.pair(1, "agent-3")["state"] == "PENDING_APPROVAL", "proposal reaches requester")
    c.wait(lambda: c.pair(3, "agent-1")["state"] == "PENDING_APPROVAL", "proposal reaches provider")
    first = c.pair(1, "agent-3")
    assert first["artifact"] is None
    c.call(1, "POST", "/owner/approvals", {"session_id": first["session_id"], "approve": True,
        "proposal_digest": first["proposal"]["digest"], "expected_revision": first["revision"]})
    c.wait(lambda: len(c.pair(3, "agent-1")["approvals"]) == 1, "first approval delivered")
    assert c.pair(1, "agent-3")["artifact"] is None
    second = c.pair(3, "agent-1")
    c.call(3, "POST", "/owner/approvals", {"session_id": second["session_id"], "approve": True,
        "proposal_digest": second["proposal"]["digest"], "expected_revision": second["revision"]})
    c.wait(lambda: c.pair(1, "agent-3")["state"] == "CONNECTED" and c.pair(3, "agent-1")["state"] == "CONNECTED", "both artifacts")
    assert c.pair(1, "agent-3")["artifact"] == c.pair(3, "agent-1")["artifact"]
    assert c.pair(1, "agent-3")["session_id"] == session3
    for viewer in range(1, 5):
        events = json.dumps(c.state(viewer)["events"])
        for other in range(1, 5):
            if other != viewer:
                assert f"PRIVATE-CANARY-{other}" not in events
    assert len(list(c.directory.glob("agent-*.sqlite3"))) == 4

    return {"scenario": c.scenario, "process_count": 4, "artifact": c.pair(1, "agent-3")["artifact"], "states": {s["peer_id"]: s["state"] for s in c.state(1)["sessions"]}}


def main():
    parser = argparse.ArgumentParser(description="临时端口和数据库上的四进程验收，结束后自动停止")
    parser.add_argument("--scenario", choices=["cofounder", "venue"], default="cofounder")
    parser.add_argument("--mode", choices=["deterministic", "model", "codex"], default="deterministic")
    args = parser.parse_args()
    facts = None if args.scenario == "cofounder" else {
        1: {"capacity": 100}, 2: {"capacity": 10},
        3: {"capacity": 80}, 4: {"capacity": 60},
    }
    demand = "寻找创业合伙人，每周至少15小时" if args.scenario == "cofounder" else "寻找活动场地，容量50"
    with tempfile.TemporaryDirectory(prefix="xagent-smoke-") as directory:
        group = Cluster(Path(directory), args.scenario, facts, mode=args.mode)
        try:
            print(f"启动四个独立进程 · {args.scenario} · 临时端口/数据库", flush=True)
            for number in range(1, 5):
                group.start(number)
            result = run_demo(group, demand)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("PASS: 筛选 → 补问 → 进程重启恢复 → 双方批准 → 一致结果卡")
        finally:
            group.close()


if __name__ == "__main__":
    main()
