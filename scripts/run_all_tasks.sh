#!/usr/bin/env bash
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
SCRIPT_DIR="$PROJECT_DIR/scripts"
RUN_TIMESTAMP="${RUN_TIMESTAMP:-$(date +%Y%m%d_%H%M%S_%N)}"
RESULT_ROOT="${RESULT_ROOT:-$PROJECT_DIR/results_$RUN_TIMESTAMP}"
BATCH_ID="${BATCH_ID:-nav2_$RUN_TIMESTAMP}"

if (( $# > 0 )); then
  TASKS=("$@")
else
  TASKS=()
  for NUMBER in $(seq -w 1 24); do
    TASKS+=("Q$NUMBER")
  done
fi

SEEN_TASKS=" "
for REQUESTED_TASK in "${TASKS[@]}"; do
  REQUESTED_TASK="${REQUESTED_TASK^^}"
  if [[ ! "$REQUESTED_TASK" =~ ^Q(0[1-9]|1[0-9]|2[0-4])$ ]]; then
    echo "Invalid task id: $REQUESTED_TASK" >&2
    exit 2
  fi
  if [[ "$SEEN_TASKS" == *" $REQUESTED_TASK "* ]]; then
    echo "Duplicate task would mix two runs in one directory: $REQUESTED_TASK" >&2
    exit 2
  fi
  SEEN_TASKS+="$REQUESTED_TASK "
  if ! python3 "$PROJECT_DIR/task_config.py" \
      --config-dir "$PROJECT_DIR/config/tasks" \
      resolve "$REQUESTED_TASK" >/dev/null; then
    echo "Task configuration validation failed: $REQUESTED_TASK" >&2
    exit 3
  fi
done

if [[ "$(basename -- "$RESULT_ROOT")" != results_[0-9]* ]]; then
  echo "Result root must be named results_<timestamp>: $RESULT_ROOT" >&2
  exit 2
fi
if [[ -e "$RESULT_ROOT" ]]; then
  echo "Refusing to mix this run with existing results: $RESULT_ROOT" >&2
  exit 2
fi
mkdir "$RESULT_ROOT"
export RESULT_ROOT

ACTIVE_TASK=""
cleanup() {
  if [[ -n "$ACTIVE_TASK" ]]; then
    "$SCRIPT_DIR/stop_task_stack.sh" "$ACTIVE_TASK" || true
  fi
}
trap cleanup EXIT INT TERM

printf 'task\trun_id\texecutor_status\tresult_dir\n' >"$RESULT_ROOT/runs.tsv"

for TASK_ID in "${TASKS[@]}"; do
  TASK_ID="${TASK_ID^^}"
  if [[ ! "$TASK_ID" =~ ^Q(0[1-9]|1[0-9]|2[0-4])$ ]]; then
    echo "Invalid task id: $TASK_ID" >&2
    continue
  fi

  ACTIVE_TASK="$TASK_ID"
  READY=0
  PREFLIGHT_LOG="$PROJECT_DIR/logs/$TASK_ID/preflight.log"
  : >"$PREFLIGHT_LOG"
  for START_ATTEMPT in 1 2 3; do
    "$SCRIPT_DIR/stop_task_stack.sh" "$TASK_ID" || true
    if ! "$SCRIPT_DIR/start_task_stack.sh" "$TASK_ID" \
        >>"$PREFLIGHT_LOG" 2>&1; then
      echo "STACK_START_FAILED=$TASK_ID ATTEMPT=$START_ATTEMPT" \
        | tee -a "$PREFLIGHT_LOG" >&2
      continue
    fi
    if "$SCRIPT_DIR/check_task_stack.sh" "$TASK_ID" 60 \
        >>"$PREFLIGHT_LOG" 2>&1; then
      READY=1
    fi
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

  RESULT_DIR="$RESULT_ROOT/$TASK_ID"
  printf '%s\t%s\t%s\t%s\n' \
    "$TASK_ID" "$RUN_ID" "$EXECUTOR_STATUS" "$RESULT_DIR" \
      >>"$RESULT_ROOT/runs.tsv"

  "$SCRIPT_DIR/stop_task_stack.sh" "$TASK_ID" || true
  ACTIVE_TASK=""
  sleep 2
done

python3 "$PROJECT_DIR/summarize_results.py" \
  --batch-tsv "$RESULT_ROOT/runs.tsv" \
  --output-json "$RESULT_ROOT/summary.json" \
  --output-markdown "$RESULT_ROOT/summary.md"

echo "BATCH_ID=$BATCH_ID"
echo "RESULT_ROOT=$RESULT_ROOT"
