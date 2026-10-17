"""The combined driver must outwait a legitimate owner-answer model reply."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from scripts.run_combined import AgentProc


def test_combined_driver_waits_for_slow_natural_answer(tmp_path):
    class SlowOwner(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            time.sleep(11)
            body = b'{"answered":true}'
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), SlowOwner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    agent = AgentProc({'agent_id': 'agent-1', 'port': server.server_port, 'owner_token': 'test'}, tmp_path)
    try:
        assert agent.call('POST', '/owner/answers', {'text': '我希望稳定后能和对方在同一个城市长期生活'}) == {'answered': True}
    finally:
        agent.log.close()
        server.shutdown(); server.server_close(); thread.join()
