#!/usr/bin/env bash
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
SCRIPT_DIR="$PROJECT_DIR/scripts"
RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/logs}"
RUN_TIMESTAMP="${RUN_TIMESTAMP:-$(date +%Y%m%d_%H%M%S_%N)}"
RESULT_ROOT="${RESULT_ROOT:-$PROJECT_DIR/results_$RUN_TIMESTAMP}"
BATCH_ID="${BATCH_ID:-nav2_$RUN_TIMESTAMP}"
INITIAL_TASK_ESTIMATE_SECONDS="${INITIAL_TASK_ESTIMATE_SECONDS:-1800}"
if [[ ! "$INITIAL_TASK_ESTIMATE_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "INITIAL_TASK_ESTIMATE_SECONDS must be a positive integer" >&2
  exit 3
fi

format_duration() {
  local total_seconds="$1"
  printf '%02d:%02d:%02d' \
    "$((total_seconds / 3600))" \
    "$(((total_seconds % 3600) / 60))" \
    "$((total_seconds % 60))"
}

format_timestamp() {
  date --iso-8601=seconds --date="@$1"
}

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
handle_signal() {
  local signal_name="$1"
  local exit_status="$2"
  echo "BATCH_STOP_SIGNAL=$signal_name ACTIVE_TASK=${ACTIVE_TASK:-none}" >&2
  exit "$exit_status"
}
trap cleanup EXIT
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM

printf 'task\trun_id\texecutor_status\tresult_dir\telapsed_s\tcompleted_unix_s\teta_remaining_s\teta_completion_time\n' \
  >"$RESULT_ROOT/runs.tsv"

TOTAL_TASKS="${#TASKS[@]}"
COMPLETED_TASKS=0
TOTAL_TASK_ELAPSED_SECONDS=0
BATCH_STARTED_UNIX=$(date +%s)
INITIAL_ETA_REMAINING_SECONDS=$((TOTAL_TASKS * INITIAL_TASK_ESTIMATE_SECONDS))
INITIAL_ETA_UNIX=$((BATCH_STARTED_UNIX + INITIAL_ETA_REMAINING_SECONDS))
echo "BATCH_TIMING_START STARTED_AT=$(format_timestamp "$BATCH_STARTED_UNIX") TOTAL_TASKS=$TOTAL_TASKS INITIAL_TASK_ESTIMATE_S=$INITIAL_TASK_ESTIMATE_SECONDS ETA_REMAINING_S=$INITIAL_ETA_REMAINING_SECONDS ETA_REMAINING_HMS=$(format_duration "$INITIAL_ETA_REMAINING_SECONDS") ETA_COMPLETION=$(format_timestamp "$INITIAL_ETA_UNIX")"

for TASK_ID in "${TASKS[@]}"; do
  TASK_ID="${TASK_ID^^}"
  if [[ ! "$TASK_ID" =~ ^Q(0[1-9]|1[0-9]|2[0-4])$ ]]; then
    echo "Invalid task id: $TASK_ID" >&2
    continue
  fi

  ACTIVE_TASK="$TASK_ID"
  TASK_INDEX=$((COMPLETED_TASKS + 1))
  TASK_STARTED_UNIX=$(date +%s)
  echo "TASK_TIMING_START TASK=$TASK_ID INDEX=$TASK_INDEX TOTAL=$TOTAL_TASKS STARTED_AT=$(format_timestamp "$TASK_STARTED_UNIX")"
  READY=0
  PREFLIGHT_LOG="$RUN_LOG_ROOT/$TASK_ID/preflight.log"
  mkdir -p "$RUN_LOG_ROOT/$TASK_ID"
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
      >"$RUN_LOG_ROOT/$TASK_ID/runner_startup_error.log"
    # Still invoke the single-task executor: Runner may produce its own failure
    # episode, and otherwise the executor creates a labelled diagnostic video.
    "$SCRIPT_DIR/run_runner_task.sh" "$TASK_ID" "$RUN_ID"
    EXECUTOR_STATUS=$?
  fi

  "$SCRIPT_DIR/stop_task_stack.sh" "$TASK_ID" || true
  ACTIVE_TASK=""
  TASK_COMPLETED_UNIX=$(date +%s)
  TASK_ELAPSED_SECONDS=$((TASK_COMPLETED_UNIX - TASK_STARTED_UNIX))
  COMPLETED_TASKS=$((COMPLETED_TASKS + 1))
  TOTAL_TASK_ELAPSED_SECONDS=$((TOTAL_TASK_ELAPSED_SECONDS + TASK_ELAPSED_SECONDS))
  AVERAGE_TASK_SECONDS=$(((TOTAL_TASK_ELAPSED_SECONDS + COMPLETED_TASKS / 2) / COMPLETED_TASKS))
  REMAINING_TASKS=$((TOTAL_TASKS - COMPLETED_TASKS))
  ETA_REMAINING_SECONDS=$((AVERAGE_TASK_SECONDS * REMAINING_TASKS))
  ETA_COMPLETION_UNIX=$((TASK_COMPLETED_UNIX + ETA_REMAINING_SECONDS))
  RESULT_DIR="$RESULT_ROOT/$TASK_ID"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$TASK_ID" "$RUN_ID" "$EXECUTOR_STATUS" "$RESULT_DIR" \
    "$TASK_ELAPSED_SECONDS" "$TASK_COMPLETED_UNIX" \
    "$ETA_REMAINING_SECONDS" "$(format_timestamp "$ETA_COMPLETION_UNIX")" \
      >>"$RESULT_ROOT/runs.tsv"
  echo "TASK_TIMING_END TASK=$TASK_ID ELAPSED_S=$TASK_ELAPSED_SECONDS ELAPSED_HMS=$(format_duration "$TASK_ELAPSED_SECONDS") EXECUTOR_STATUS=$EXECUTOR_STATUS COMPLETED=$COMPLETED_TASKS TOTAL=$TOTAL_TASKS REMAINING=$REMAINING_TASKS AVG_TASK_S=$AVERAGE_TASK_SECONDS ETA_REMAINING_S=$ETA_REMAINING_SECONDS ETA_REMAINING_HMS=$(format_duration "$ETA_REMAINING_SECONDS") ETA_COMPLETION=$(format_timestamp "$ETA_COMPLETION_UNIX")"
  sleep 2
done

python3 "$PROJECT_DIR/summarize_results.py" \
  --batch-tsv "$RESULT_ROOT/runs.tsv" \
  --output-json "$RESULT_ROOT/summary.json" \
  --output-markdown "$RESULT_ROOT/summary.md"

echo "BATCH_ID=$BATCH_ID"
echo "RESULT_ROOT=$RESULT_ROOT"
echo "BATCH_TIMING_END COMPLETED_AT=$(format_timestamp "$(date +%s)") COMPLETED_TASKS=$COMPLETED_TASKS TOTAL_TASKS=$TOTAL_TASKS"
