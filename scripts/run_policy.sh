#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: run_policy.sh Qxx}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
mkdir -p "$PROJECT_DIR/logs/$TASK_ID"

exec python "$PROJECT_DIR/policy_server.py" \
  --task "$TASK_ID" \
  --compiled-tasks "$PROJECT_DIR/compiled_tasks.json" \
  --status "$PROJECT_DIR/logs/$TASK_ID/navigation_status.json" \
  --run-token "${NAV2_RUN_TOKEN:-manual}" \
  --host 127.0.0.1 \
  --port 18022
