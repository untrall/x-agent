#!/usr/bin/env bash
# One-command two-act demo.
#   Act 1 (admin view): the web demo (demo/) auto-plays in the browser —
#     ranking, then the 「太安静了」 feedback that moves the red thread.
#   Act 2 (user view): four agent TUIs in one tmux window; the driver waits
#     for Enter, then negotiates and only the #1 candidate is met.
# Each run gets fresh configs and ports.
#
#   bash scripts/demo_tui.sh              # 1.5s pause per step
#   bash scripts/demo_tui.sh --delay 3    # extra args go to run_combined.py
#
# Leave: Ctrl+B then D (detach), or: tmux kill-session -t xagent-demo
set -euo pipefail
cd "$(dirname "$0")/.."

SESSION=xagent-demo
PY=.venv/bin/python
command -v tmux >/dev/null || { echo "需要 tmux：brew install tmux" >&2; exit 1; }

# Act 1 data: same engine run the web page reads.
"$PY" scripts/build_demo_data.py >/dev/null
WEB_PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
WEB_URL="http://127.0.0.1:$WEB_PORT/?auto"

DIR=$("$PY" scripts/run_combined.py --configs-only "$@" | sed -n 's/^配置目录：//p')
[ -n "$DIR" ] || { echo "生成配置失败" >&2; exit 1; }

agent() { echo "$PY scripts/run_agent.py --config $DIR/agent-$1.json"; }
driver="$PY scripts/run_combined.py --attach $DIR --wait-enter"
[ $# -gt 0 ] && driver+=" $(printf '%q ' "$@")"
driver+="; echo; echo '演示结束。退出：Ctrl+B 再按 D，或 tmux kill-session -t $SESSION'; read"

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -n agents -x 220 -y 60 "$(agent 1)"
tmux set -t "$SESSION" mouse on
for n in 2 3 4; do
  tmux split-window -t "$SESSION:agents" "$(agent "$n")"
  tmux select-layout -t "$SESSION:agents" tiled
done
# Full-width strip along the bottom for the driver; it gets the keyboard
# so Enter starts act 2.
tmux split-window -t "$SESSION:agents" -v -f -l 12 "$driver"
# Web server lives in a background window and dies with the session.
tmux new-window -d -t "$SESSION" -n web \
  "$PY -m http.server $WEB_PORT --bind 127.0.0.1 --directory demo"

echo "配置目录：$DIR"
echo "第一幕网页：$WEB_URL"
if [ -t 1 ]; then
  sleep 0.5
  open "$WEB_URL" 2>/dev/null || true
  if [ -n "${TMUX:-}" ]; then
    tmux switch-client -t "$SESSION:agents"
  else
    tmux attach -t "$SESSION:agents"
  fi
else
  echo "已在后台启动，查看：tmux attach -t $SESSION"
fi
