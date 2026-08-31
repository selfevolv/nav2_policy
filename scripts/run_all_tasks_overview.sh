#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
RUN_TIMESTAMP="${RUN_TIMESTAMP:-$(date +%Y%m%d_%H%M%S_%N)}"

export PROJECT_DIR RUN_TIMESTAMP
export RUNNER_OVERVIEW=1
export RUNNER_CHASE=1
export RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/cache/overview_logs/$RUN_TIMESTAMP}"
# Two extra 1280x720 render products make simulation slower than wall time.
# Keep the diagnostic run bounded while avoiding false timeouts on full routes.
export RUNNER_TIMEOUT_GRACE_SECONDS="${RUNNER_TIMEOUT_GRACE_SECONDS:-1800}"

mkdir -p "$RUN_LOG_ROOT"
PREPARE_OUTPUT=$("$PROJECT_DIR/scripts/prepare_overview_runtime.sh")
printf '%s\n' "$PREPARE_OUTPUT"
OVERVIEW_RUNTIME_PATH=$(printf '%s\n' "$PREPARE_OUTPUT" \
  | awk -F= '/^OVERVIEW_RUNTIME_COPY=/{print substr($0, index($0, "=") + 1)}')
if [[ ! -s "$OVERVIEW_RUNTIME_PATH" ]]; then
  echo "Unable to resolve prepared diagnostic runtime copy" >&2
  exit 3
fi
export OVERVIEW_RUNTIME_PATH
exec "$PROJECT_DIR/scripts/run_all_tasks.sh" "$@"
