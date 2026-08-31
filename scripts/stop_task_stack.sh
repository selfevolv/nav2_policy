#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: stop_task_stack.sh Qxx}"
PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/logs}"
RUN_DIR="$RUN_LOG_ROOT/$TASK_ID"

for NAME in policy nav2; do
  PID_FILE="$RUN_DIR/$NAME.pid"
  [[ -f "$PID_FILE" ]] || continue
  PID=$(<"$PID_FILE")
  if [[ ! "$PID" =~ ^[0-9]+$ ]]; then
    echo "Ignoring invalid PID file: $PID_FILE" >&2
    continue
  fi
  if kill -0 "$PID" 2>/dev/null; then
    CMDLINE=$(tr '\0' ' ' <"/proc/$PID/cmdline" 2>/dev/null || true)
    if [[ "$CMDLINE" != *"$PROJECT_DIR"* ]]; then
      echo "Refusing to stop unrelated PID $PID: $CMDLINE" >&2
      exit 3
    fi
    kill -INT -- "-$PID"
    for _ in 1 2 3 4 5; do
      kill -0 -- "-$PID" 2>/dev/null || break
      sleep 1
    done
    if kill -0 -- "-$PID" 2>/dev/null; then
      kill -TERM -- "-$PID"
      sleep 1
    fi
    if kill -0 -- "-$PID" 2>/dev/null; then
      kill -KILL -- "-$PID"
    fi
  fi
  rm -f "$PID_FILE"
done

echo "STOPPED_TASK_STACK=$TASK_ID"
