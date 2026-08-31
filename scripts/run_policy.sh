#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: run_policy.sh Qxx}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/logs}"
mkdir -p "$RUN_LOG_ROOT/$TASK_ID"

exec python "$PROJECT_DIR/policy_server.py" \
  --task "$TASK_ID" \
  --compiled-tasks "$PROJECT_DIR/compiled_tasks.json" \
  --status "$RUN_LOG_ROOT/$TASK_ID/navigation_status.json" \
  --run-token "${NAV2_RUN_TOKEN:-manual}" \
  --host 127.0.0.1 \
  --port 18022
