#!/usr/bin/env bash
# One-command two-act demo.
#   Act 1 (admin view): the web demo (demo/) auto-plays in the browser —
#     ranking, then the 「太安静了」 feedback that moves the red thread.
#   Act 2 (user view): four agent TUIs in one tmux window; the driver waits
#     for Enter, then negotiates. At the 3-pick-1, 阿哲's window (focused
#     automatically) picks who to chat with in a dropdown and just types;
#     their agents answer from their own persona via the real model.
#     「选定」 asks that candidate, whose window takes the keyboard and pops
#     「阿哲 选择了你 · 是否接受？」; on decline, 阿哲 picks again.
# Each run gets fresh configs and ports. The model key comes from Keychain
# (see scripts/with_llm_env.sh).
#
#   bash scripts/demo_tui.sh              # 1.5s pause per step, 阿哲 chats by hand
#   bash scripts/demo_tui.sh --auto-chat  # hands-free: preset questions, picks #1
#   bash scripts/demo_tui.sh --delay 3    # extra args go to run_combined.py
#
# Leave: Ctrl+B then D (detach), or: tmux kill-session -t xagent-demo
set -euo pipefail
cd "$(dirname "$0")/.."
RESET=false
if [ "${1:-}" = --reset-existing ]; then RESET=true; shift; fi

SESSION=xagent-demo
PY=.venv/bin/python
command -v tmux >/dev/null || { echo "需要 tmux：brew install tmux" >&2; exit 1; }
bash scripts/with_llm_env.sh true   # fail early if the model key is missing

# Act 1 data: same engine run the web page reads.
if ! $RESET; then "$PY" scripts/build_demo_data.py >/dev/null; fi
WEB_PORT=$("$PY" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
WEB_URL="http://127.0.0.1:$WEB_PORT/?auto"

DIR=$("$PY" scripts/run_combined.py --configs-only "$@" | sed -n 's/^配置目录：//p')
[ -n "$DIR" ] || { echo "生成配置失败" >&2; exit 1; }

# Candidates (2-4) answer chat with the real model; 阿哲 (1) only asks.
agent() {
  if [ "$1" = 1 ]; then
    echo "bash scripts/with_llm_env.sh $PY scripts/run_agent.py --config $DIR/agent-1.json --answer-model"
  else
    echo "bash scripts/with_llm_env.sh $PY scripts/run_agent.py --config $DIR/agent-$1.json --chat-model --answer-model"
  fi
}
choice="--owner-choice --tmux-target $SESSION:agents"
for arg in "$@"; do [ "$arg" = --auto-chat ] && choice=""; done
driver="clear; read -p '4 个 Agent 已上线。讲完网页第一幕后，按 Enter 开始第二幕…' _"
# Hand the keyboard to 阿哲's window so he can chat and /choose.
[ -n "$choice" ] && driver+="; tmux select-pane -t $SESSION:agents.0"
driver+="; $PY scripts/run_combined.py --attach $DIR $choice"
[ $# -gt 0 ] && driver+=" $(printf '%q ' "$@")"
driver+="; echo; echo '演示结束。退出：Ctrl+B 再按 D，或 tmux kill-session -t $SESSION'; read"

if $RESET; then
  panes=()
  while IFS= read -r pane; do panes+=("$pane"); done < <(tmux list-panes -t "$SESSION:agents" -F '#{pane_id}')
  [ "${#panes[@]}" = 5 ] || { echo '演示终端布局不完整，请重新运行 demo_tui.sh' >&2; exit 1; }
  # Stop the old driver first; then replace each TUI in place. The web server
  # and attached terminal client survive. Fresh configs isolate all old data.
  tmux respawn-pane -k -t "${panes[4]}" "bash -c $(printf %q "$driver")"
  for n in 1 2 3 4; do
    tmux respawn-pane -k -t "${panes[$((n-1))]}" "$(agent "$n")"
  done
  tmux select-pane -t "${panes[4]}"
  echo "配置目录：$DIR"
  exit 0
fi

tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -n agents -x 220 -y 60 "$(agent 1)"
tmux set -t "$SESSION" mouse on
for n in 2 3 4; do
  tmux split-window -t "$SESSION:agents" "$(agent "$n")"
done
# 2x2 grid, equal windows: 阿哲 | 陈语桐 on top, 方糖 | 林小满 below.
# Pane n-1 still shows agent-n, which the driver relies on to move focus.
tmux select-layout -t "$SESSION:agents" tiled
# Full-width strip along the bottom for the driver; it gets the keyboard
# so Enter starts act 2.
# Explicit bash: tmux runs commands in the user shell (zsh here), where
# `read -p` means "read from coprocess" and would not wait for Enter.
tmux split-window -t "$SESSION:agents" -v -f -l 8 "bash -c $(printf %q "$driver")"
# Web server lives in a background window and dies with the session.
web="$PY scripts/demo_control.py --port $WEB_PORT --"
[ $# -gt 0 ] && web+=" $(printf '%q ' "$@")"
tmux new-window -d -t "$SESSION" -n web "$web"

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
