#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: start_task_stack.sh Qxx}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
RUN_DIR="$PROJECT_DIR/logs/$TASK_ID"
mkdir -p "$RUN_DIR"

for NAME in nav2 policy; do
  PID_FILE="$RUN_DIR/$NAME.pid"
  if [[ -f "$PID_FILE" ]]; then
    PID=$(<"$PID_FILE")
    if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
      echo "$NAME already running with PID $PID" >&2
      exit 2
    fi
    rm -f "$PID_FILE"
  fi
done

nohup setsid "$SCRIPT_DIR/run_nav2.sh" "$TASK_ID" \
  >"$RUN_DIR/nav2.log" 2>&1 < /dev/null &
NAV2_PID=$!
echo "$NAV2_PID" >"$RUN_DIR/nav2.pid"

nohup setsid "$SCRIPT_DIR/run_policy.sh" "$TASK_ID" \
  >"$RUN_DIR/policy.log" 2>&1 < /dev/null &
POLICY_PID=$!
echo "$POLICY_PID" >"$RUN_DIR/policy.pid"

echo "TASK=$TASK_ID"
echo "NAV2_PID=$NAV2_PID"
echo "POLICY_PID=$POLICY_PID"
echo "LOG_DIR=$RUN_DIR"
