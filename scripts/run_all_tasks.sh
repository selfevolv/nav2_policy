#!/usr/bin/env bash
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
SCRIPT_DIR="$PROJECT_DIR/scripts"
BATCH_ID="${BATCH_ID:-nav2_batch_$(date +%Y%m%d_%H%M%S)}"
BATCH_DIR="$PROJECT_DIR/results/batches/$BATCH_ID"
mkdir -p "$BATCH_DIR"

if (( $# > 0 )); then
  TASKS=("$@")
else
  TASKS=()
  for NUMBER in $(seq -w 1 24); do
    TASKS+=("Q$NUMBER")
  done
fi

ACTIVE_TASK=""
cleanup() {
  if [[ -n "$ACTIVE_TASK" ]]; then
    "$SCRIPT_DIR/stop_task_stack.sh" "$ACTIVE_TASK" || true
  fi
}
trap cleanup EXIT INT TERM

printf 'task\trun_id\texecutor_status\tresult_dir\n' >"$BATCH_DIR/runs.tsv"

for TASK_ID in "${TASKS[@]}"; do
  TASK_ID="${TASK_ID^^}"
  if [[ ! "$TASK_ID" =~ ^Q(0[1-9]|1[0-9]|2[0-4])$ ]]; then
    echo "Invalid task id: $TASK_ID" >&2
    continue
  fi

  ACTIVE_TASK="$TASK_ID"
  READY=0
  for START_ATTEMPT in 1 2 3; do
    "$SCRIPT_DIR/stop_task_stack.sh" "$TASK_ID" || true
    "$SCRIPT_DIR/start_task_stack.sh" "$TASK_ID"
    for _ in $(seq 1 30); do
      if ss -ltn | grep -q ':18022 ' && \
        python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); raise SystemExit(0 if d.get("goal_accepted") else 1)' \
          "$PROJECT_DIR/logs/$TASK_ID/navigation_status.json" 2>/dev/null; then
        READY=1
        break
      fi
      sleep 1
    done
    if [[ "$READY" -eq 1 ]]; then
      echo "NAV2_PREFLIGHT_READY=$TASK_ID ATTEMPT=$START_ATTEMPT"
      break
    fi
    echo "NAV2_PREFLIGHT_RETRY=$TASK_ID ATTEMPT=$START_ATTEMPT" >&2
  done

  RUN_ID="${BATCH_ID}_${TASK_ID,,}"
  if [[ "$READY" -eq 1 ]]; then
    "$SCRIPT_DIR/run_runner_task.sh" "$TASK_ID" "$RUN_ID"
    EXECUTOR_STATUS=$?
  else
    echo "Nav2 did not accept the route after three starts for $TASK_ID" \
      >"$PROJECT_DIR/logs/$TASK_ID/runner_startup_error.log"
    # Still invoke the single-task executor: Runner may produce its own failure
    # episode, and otherwise the executor creates a labelled diagnostic video.
    "$SCRIPT_DIR/run_runner_task.sh" "$TASK_ID" "$RUN_ID"
    EXECUTOR_STATUS=$?
  fi

  RESULT_DIR="$PROJECT_DIR/results/$TASK_ID/$RUN_ID"
  printf '%s\t%s\t%s\t%s\n' \
    "$TASK_ID" "$RUN_ID" "$EXECUTOR_STATUS" "$RESULT_DIR" \
    >>"$BATCH_DIR/runs.tsv"

  "$SCRIPT_DIR/stop_task_stack.sh" "$TASK_ID" || true
  ACTIVE_TASK=""
  sleep 2
done

python3 "$PROJECT_DIR/summarize_results.py" \
  --batch-tsv "$BATCH_DIR/runs.tsv" \
  --output-json "$BATCH_DIR/summary.json" \
  --output-markdown "$BATCH_DIR/summary.md"

echo "BATCH_ID=$BATCH_ID"
echo "BATCH_DIR=$BATCH_DIR"
