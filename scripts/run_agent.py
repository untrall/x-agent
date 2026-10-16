"""Run one independent Agent: its TUI and HTTP listener share a runtime."""

import argparse
import asyncio
from contextlib import contextmanager
import ipaddress
import json
from pathlib import Path
import socket
import signal

import uvicorn


class AgentServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # This app owns runtime/CLI cleanup after serve() returns. Uvicorn's
        # default signal replay would terminate the process before that finally.
        originals = {sig: signal.signal(sig, self.handle_exit) for sig in (signal.SIGINT, signal.SIGTERM)}
        try:
            yield
        finally:
            for sig, handler in originals.items():
                signal.signal(sig, handler)


def load_config(path):
    source = Path(path).resolve()
    config = json.loads(source.read_text())
    if isinstance(config.get("scenario"), str):
        config["scenario"] = json.loads((source.parent / config["scenario"]).read_text())
    database = Path(config["database"])
    if not database.is_absolute():
        database = source.parent / database
    config["database"] = str(database.resolve())
    host = config.get("host", "127.0.0.1")
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("本地演示仅允许监听 loopback 地址。")
    return config


async def run(config, headless, mode):
    from xagent.mvp.policy import DeterministicPolicy, ModelPolicy
    from xagent.mvp.runtime import AgentRuntime
    from xagent.mvp.server import create_peer_app

    if mode == "codex":
        from xagent.mvp.codex_policy import CodexPolicy
        policy = CodexPolicy()
    else:
        policy = ModelPolicy.from_env() if mode == "model" else DeterministicPolicy()
    runtime = AgentRuntime(config, policy=policy)
    server = AgentServer(uvicorn.Config(
        create_peer_app(runtime), host=config.get("host", "127.0.0.1"), port=config["port"],
        log_level="warning", access_log=False,
        timeout_graceful_shutdown=1,
    ))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind((config.get("host", "127.0.0.1"), config["port"]))
        await runtime.start()
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        ui_task = None
        try:
            if headless:
                print(f"{config['name']} ({config['agent_id']}) · {mode} · http://127.0.0.1:{config['port']}", flush=True)
                await server_task
            else:
                from xagent.mvp.tui import AgentApp
                ui_task = asyncio.create_task(AgentApp(runtime).run_async())
                done, _ = await asyncio.wait([ui_task, server_task], return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    await task
        finally:
            server.should_exit = True
            if ui_task and not ui_task.done():
                ui_task.cancel()
                await asyncio.gather(ui_task, return_exceptions=True)
            try:
                await asyncio.wait_for(asyncio.shield(server_task), timeout=5)
            except asyncio.TimeoutError:
                server_task.cancel()
                await asyncio.gather(server_task, return_exceptions=True)
            requests = list(server.server_state.tasks)
            for task in requests:
                task.cancel()
            if requests:
                await asyncio.gather(*requests, return_exceptions=True)
            await runtime.stop()
    finally:
        listener.close()


def main():
    parser = argparse.ArgumentParser(description="启动一份独立 X-Agent TUI 和 HTTP 服务")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--headless", action="store_true", help="仅启动 HTTP 服务，供脚本和自动化验收")
    parser.add_argument("--mode", choices=["deterministic", "model", "codex"], default="deterministic")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        asyncio.run(run(config, args.headless, args.mode))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError) as exc:
        parser.exit(2, f"启动失败：{exc}\n")


if __name__ == "__main__":
    main()
