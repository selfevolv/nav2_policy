#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: check_task_stack.sh Qxx [timeout-seconds]}"
TIMEOUT_SECONDS="${2:-45}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
RUN_DIR="$PROJECT_DIR/logs/$TASK_ID"

ROS_DOMAIN_ID=$(<"$RUN_DIR/ros_domain_id")
RUN_TOKEN=$(<"$RUN_DIR/run_token")
export ROS_DOMAIN_ID PROJECT_DIR
source "$SCRIPT_DIR/env.sh"

exec python "$PROJECT_DIR/check_nav2_ready.py" \
  --status "$RUN_DIR/navigation_status.json" \
  --run-token "$RUN_TOKEN" \
  --timeout "$TIMEOUT_SECONDS"
