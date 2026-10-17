"""Loopback demo web server with an authenticated, serialized TUI reset."""
import argparse
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import subprocess
import threading
import time

import httpx

ROOT = Path(__file__).resolve().parent.parent


def restart_demo(args):
    result = subprocess.run(['bash', str(ROOT / 'scripts/demo_tui.sh'), '--reset-existing', *args],
                            cwd=ROOT, capture_output=True, text=True, timeout=30, check=True)
    directory = next(line.removeprefix('配置目录：') for line in result.stdout.splitlines()
                     if line.startswith('配置目录：'))
    configs = [json.loads(path.read_text()) for path in Path(directory).glob('agent-*.json')]
    if len(configs) != 4:
        raise RuntimeError('Expected four agents')
    deadline = time.monotonic() + 20
    with httpx.Client(timeout=1, trust_env=False) as client:
        while time.monotonic() < deadline:
            ready = 0
            for cfg in configs:
                try:
                    if client.get(f"http://127.0.0.1:{cfg['port']}/health").is_success:
                        ready += 1
                except httpx.HTTPError:
                    pass
            if ready == 4:
                return {'ready': True}
            time.sleep(.15)
    raise TimeoutError('Agents did not become ready')


def make_server(port, directory, restart):
    cookie = secrets.token_urlsafe(32)
    lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def end_headers(self):
            self.send_header('X-XAgent-Control', '1')
            self.send_header('Cache-Control', 'no-store')
            if self.command in {'GET', 'HEAD'}:
                self.send_header('Set-Cookie', f'xagent_demo={cookie}; HttpOnly; SameSite=Strict; Path=/')
            super().end_headers()

        def respond(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/api/demo/reset':
                return self.respond(404, {'error': 'Unknown endpoint'})
            auth = SimpleCookie()
            try:
                auth.load(self.headers.get('Cookie', ''))
            except Exception:
                return self.respond(403, {'error': 'Forbidden'})
            token = auth.get('xagent_demo')
            hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            host = self.headers.get('Host')
            origin = self.headers.get('Origin')
            if (host not in hosts or (origin and origin != 'http://' + host)
                    or self.headers.get('X-XAgent-Request') != '1'
                    or not token or not secrets.compare_digest(token.value, cookie)):
                return self.respond(403, {'error': 'Forbidden'})
            if not lock.acquire(blocking=False):
                return self.respond(409, {'error': '正在重置，请稍候'})
            try:
                self.respond(200, restart())
            except Exception as exc:
                # Never echo shell output, configs or credentials to the browser.
                self.log_error('TUI reset failed: %s', type(exc).__name__)
                self.respond(500, {'error': 'TUI 重置失败，请检查终端或重新运行 demo_tui.sh'})
            finally:
                lock.release()

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('demo_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    forwarded = args.demo_args[1:] if args.demo_args[:1] == ['--'] else args.demo_args
    server = make_server(args.port, ROOT / 'demo', lambda: restart_demo(forwarded))
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
