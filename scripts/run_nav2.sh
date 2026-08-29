#!/usr/bin/env bash
set -eo pipefail

TASK_ID="${1:?usage: run_nav2.sh Qxx}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

SCENE=$(python -c 'import json,os,sys; p=json.load(open(os.path.join(os.environ["PROJECT_DIR"],"compiled_tasks.json"))); print(p["tasks"][sys.argv[1].upper()]["scene"])' "$TASK_ID")
MAP="$PROJECT_DIR/maps/$SCENE.yaml"
PARAMS="$PROJECT_DIR/config/nav2_params.yaml"
mkdir -p "$PROJECT_DIR/logs/$TASK_ID"

exec ros2 launch "$PROJECT_DIR/launch/m20_nav2.launch.py" \
  map:="$MAP" params_file:="$PARAMS"
