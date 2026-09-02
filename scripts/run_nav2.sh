#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: run_nav2.sh Qxx}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/logs}"

SCENE=$(python -c 'import json,os,sys; p=json.load(open(os.path.join(os.environ["PROJECT_DIR"],"compiled_tasks.json"))); print(p["tasks"][sys.argv[1].upper()]["scene"])' "$TASK_ID")
if ! TASK_CONFIG_VALUES=$(python3 "$PROJECT_DIR/task_config.py" \
    --config-dir "$PROJECT_DIR/config/tasks" \
    resolve "$TASK_ID" --format shell); then
  echo "Task configuration validation failed: $TASK_ID" >&2
  exit 3
fi
IFS=$'\t' read -r TASK_CONFIG PARAMS ACTION_HZ TASK_CONFIG_SHA PARAMS_SHA NAVIGATION_LOCKED TASK_MAP \
  <<<"$TASK_CONFIG_VALUES"
if [[ "$TASK_MAP" == "-" ]]; then
  MAP="$PROJECT_DIR/maps/$SCENE.yaml"
else
  MAP="$TASK_MAP"
fi
mkdir -p "$RUN_LOG_ROOT/$TASK_ID"

echo "TASK_CONFIG=$TASK_CONFIG"
echo "TASK_CONFIG_SHA256=$TASK_CONFIG_SHA"
echo "NAV2_PARAMS=$PARAMS"
echo "NAV2_PARAMS_SHA256=$PARAMS_SHA"
echo "NAV2_MAP=$MAP"
echo "NAVIGATION_LOCKED=$NAVIGATION_LOCKED"

exec ros2 launch "$PROJECT_DIR/launch/m20_nav2.launch.py" \
  map:="$MAP" params_file:="$PARAMS"
