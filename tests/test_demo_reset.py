import threading

import httpx


def test_reset_requires_local_cookie_and_returns_restart_result(tmp_path):
    from scripts.demo_control import make_server

    (tmp_path / 'index.html').write_text('demo')
    calls = []
    def restart():
        calls.append(True)
        return {'ready': True}
    server = make_server(0, tmp_path, restart)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', trust_env=False) as client:
            assert client.post('/api/demo/reset', headers={'X-XAgent-Request': '1'}).status_code == 403
            assert client.get('/').headers['X-XAgent-Control'] == '1'
            assert client.post('/api/demo/reset').status_code == 403
            assert client.post('/api/demo/reset', headers={'X-XAgent-Request': '1', 'Origin': 'https://example.org'}).status_code == 403
            assert not calls
            response = client.post('/api/demo/reset', headers={'X-XAgent-Request': '1'})
            assert response.status_code == 200
            assert response.json() == {'ready': True}
            assert len(calls) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_new_runs_never_reuse_a_database_directory():
    from scripts.run_combined import new_workdir
    assert new_workdir('azhe') != new_workdir('azhe')


def test_browser_reset_restarts_all_real_tuis_in_same_panes(tmp_path):
    import json
    import os
    from pathlib import Path
    import re
    import shlex
    import shutil
    import subprocess
    import time
    import uuid
    import pytest
    from scripts.run_combined import ROOT, AgentProc, wait_for

    binary = shutil.which('tmux')
    if not binary:
        pytest.skip('tmux required for demo terminal integration')
    socket = 'xagent-reset-test-' + uuid.uuid4().hex[:8]
    wrapper = tmp_path / 'tmux'
    wrapper.write_text(f'#!/bin/sh\nexec {shlex.quote(binary)} -L {socket} "$@"\n')
    wrapper.chmod(0o700)
    env = {**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH'],
           'LLM_API_KEY': 'local-test-only', 'LLM_BASE_URL': 'http://127.0.0.1:1', 'LLM_MODEL': 'test'}
    def tmux(*args):
        return subprocess.check_output([str(wrapper), *args], env=env, text=True)
    agents = []
    try:
        output = subprocess.check_output(['bash', 'scripts/demo_tui.sh'], cwd=ROOT, env=env, text=True, timeout=20)
        old_dir = Path(re.search(r'配置目录：(.+)', output)[1])
        url = re.search(r'第一幕网页：(\S+)', output)[1]
        configs = [json.loads((old_dir / f'agent-{n}.json').read_text()) for n in range(1, 5)]
        agents = [AgentProc(cfg, old_dir) for cfg in configs]
        for agent in agents:
            wait_for(agent.healthy, 'TUI starts', timeout=15)
        agents[0].call('POST', '/owner/requests', {'text': '开始测试需求'})
        wait_for(lambda: agents[0].state()['sessions'], 'old sessions created')
        panes = tmux('list-panes', '-t', 'xagent-demo:agents', '-F', '#{pane_id}')
        pids = tmux('list-panes', '-t', 'xagent-demo:agents', '-F', '#{pane_pid}')
        with httpx.Client(timeout=55, trust_env=False) as client:
            wait_for(lambda: httpx.get(url, trust_env=False).is_success, 'web starts')
            client.get(url).raise_for_status()
            response = client.post(url.split('/?')[0] + '/api/demo/reset', headers={'X-XAgent-Request': '1'})
            assert response.status_code == 200, response.text
        assert tmux('list-panes', '-t', 'xagent-demo:agents', '-F', '#{pane_id}') == panes
        assert tmux('list-panes', '-t', 'xagent-demo:agents', '-F', '#{pane_pid}') != pids
        command = tmux('display-message', '-p', '-t', 'xagent-demo:agents.0', '#{pane_start_command}')
        new_dir = Path(re.search(r'--config (.+)/agent-1.json', command)[1])
        assert new_dir != old_dir and old_dir.exists()
        for n in range(1, 5):
            cfg = json.loads((new_dir / f'agent-{n}.json').read_text())
            agent = AgentProc(cfg, new_dir); agents.append(agent)
            state = agent.state()
            assert state['brain']['answer_model'] == 'test'
            assert not state['requests'] and not state['sessions'] and not state['questions']
        wait_for(lambda: all(not a.healthy() for a in agents[:4]), 'old processes stopped')
        screen = tmux('capture-pane', '-p', '-t', 'xagent-demo:agents.4')
        assert '按 Enter 开始第二幕' in screen
    finally:
        subprocess.run([str(wrapper), 'kill-server'], env=env, capture_output=True)
        for agent in agents:
            agent.log.close()
