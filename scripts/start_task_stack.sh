#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: start_task_stack.sh Qxx}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/logs}"
RUN_DIR="$RUN_LOG_ROOT/$TASK_ID"
mkdir -p "$RUN_DIR"
STATUS_FILE="$RUN_DIR/navigation_status.json"

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

TASK_NUMBER=$((10#${TASK_ID#Q}))
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-$((100 + (TASK_NUMBER * 17 + $$ + $(date +%s)) % 100))}"
RUN_TOKEN="${TASK_ID}_$(date +%s%N)_$$"
printf '%s\n' "$ROS_DOMAIN_ID" >"$RUN_DIR/ros_domain_id"
printf '%s\n' "$RUN_TOKEN" >"$RUN_DIR/run_token"
date +%s >"$RUN_DIR/stack_started_unix_s"
rm -f "$STATUS_FILE"

nohup setsid env \
  ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  ROS_LOG_DIR="$RUN_DIR/ros_policy" \
  NAV2_RUN_TOKEN="$RUN_TOKEN" \
  "$SCRIPT_DIR/run_policy.sh" "$TASK_ID" \
  >"$RUN_DIR/policy.log" 2>&1 < /dev/null &
POLICY_PID=$!
echo "$POLICY_PID" >"$RUN_DIR/policy.pid"

POLICY_READY=0
for _ in $(seq 1 15); do
  if ! kill -0 "$POLICY_PID" 2>/dev/null; then
    break
  fi
  if python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); raise SystemExit(0 if d.get("run_token") == sys.argv[2] and d.get("request_count") == 0 and not d.get("goal_sent") else 1)' \
      "$STATUS_FILE" "$RUN_TOKEN" 2>/dev/null; then
    POLICY_READY=1
    break
  fi
  sleep 1
done
if [[ "$POLICY_READY" -ne 1 ]]; then
  echo "Policy bridge failed to publish a fresh preflight status" >&2
  kill -TERM -- "-$POLICY_PID" 2>/dev/null || true
  sleep 1
  kill -KILL -- "-$POLICY_PID" 2>/dev/null || true
  exit 4
fi

nohup setsid env \
  ROS_DOMAIN_ID="$ROS_DOMAIN_ID" \
  ROS_LOG_DIR="$RUN_DIR/ros_nav2" \
  "$SCRIPT_DIR/run_nav2.sh" "$TASK_ID" \
  >"$RUN_DIR/nav2.log" 2>&1 < /dev/null &
NAV2_PID=$!
echo "$NAV2_PID" >"$RUN_DIR/nav2.pid"

echo "TASK=$TASK_ID"
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo "RUN_TOKEN=$RUN_TOKEN"
echo "NAV2_PID=$NAV2_PID"
echo "POLICY_PID=$POLICY_PID"
echo "LOG_DIR=$RUN_DIR"
