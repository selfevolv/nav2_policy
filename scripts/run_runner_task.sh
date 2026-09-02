#!/usr/bin/env bash
set -o pipefail

TASK_ID="${1:?usage: run_runner_task.sh Qxx [run-id]}"
PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/logs}"
OUTPUT_ROOT="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/output"
QUESTION_ROOT="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/question_to_player"
PLAYER_RUNTIME="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/player_runtime"
RUNNER_CONFIG="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/config/ubuntu-teleop-runner.json"
RUNNER_IMAGE="safety-embodiment:20260817"
CACHE_ROOT="$PROJECT_DIR/cache"
RUN_TIMESTAMP="$(date +%Y%m%d_%H%M%S_%N)"
RUN_ID="${2:-nav2_${TASK_ID,,}_${RUN_TIMESTAMP}}"

if ! OFFICIAL_LIMITS=$(python3 -c 'import json,sys; task=json.load(open(sys.argv[1]))["tasks"][sys.argv[2].upper()]; print(task["maximum_duration_s"], task["maximum_vla_actions"])' \
    "$PROJECT_DIR/compiled_tasks.json" "$TASK_ID"); then
  echo "Unable to load official limits for $TASK_ID" >&2
  exit 3
fi
read -r DEFAULT_DURATION MAX_ACTIONS <<<"$OFFICIAL_LIMITS"
if ! TASK_CONFIG_VALUES=$(python3 "$PROJECT_DIR/task_config.py" \
    --config-dir "$PROJECT_DIR/config/tasks" \
    resolve "$TASK_ID" --format shell); then
  echo "Task configuration validation failed: $TASK_ID" >&2
  exit 3
fi
IFS=$'\t' read -r TASK_CONFIG NAV2_PARAMS ACTION_HZ TASK_CONFIG_SHA NAV2_PARAMS_SHA NAVIGATION_LOCKED TASK_MAP \
  <<<"$TASK_CONFIG_VALUES"
DURATION="${RUNNER_MAX_DURATION_SECONDS:-$DEFAULT_DURATION}"
RUNNER_TIMEOUT_GRACE_SECONDS="${RUNNER_TIMEOUT_GRACE_SECONDS:-600}"
RUNNER_WALL_TIMEOUT_SECONDS="${RUNNER_WALL_TIMEOUT_SECONDS:-$((DURATION + RUNNER_TIMEOUT_GRACE_SECONDS))}"
RUNNER_TIMEOUT_KILL_AFTER_SECONDS="${RUNNER_TIMEOUT_KILL_AFTER_SECONDS:-60}"
for TIMEOUT_VALUE in \
    "$RUNNER_WALL_TIMEOUT_SECONDS" \
    "$RUNNER_TIMEOUT_KILL_AFTER_SECONDS"; do
  if [[ ! "$TIMEOUT_VALUE" =~ ^[1-9][0-9]*$ ]]; then
    echo "Runner timeout values must be positive integers" >&2
    exit 3
  fi
done

if [[ -z "${RESULT_ROOT:-}" ]]; then
  RESULT_ROOT="$PROJECT_DIR/results_$RUN_TIMESTAMP"
  if ! mkdir "$RESULT_ROOT"; then
    echo "Refusing to reuse result root: $RESULT_ROOT" >&2
    exit 2
  fi
elif [[ ! -d "$RESULT_ROOT" ]]; then
  echo "Batch result root does not exist: $RESULT_ROOT" >&2
  exit 2
fi
if [[ "$(basename -- "$RESULT_ROOT")" != results_[0-9]* ]]; then
  echo "Result root must be named results_<timestamp>: $RESULT_ROOT" >&2
  exit 2
fi

RESULT_DIR="$RESULT_ROOT/$TASK_ID"
if ! mkdir "$RESULT_DIR"; then
  echo "Refusing to mix two runs of $TASK_ID in $RESULT_ROOT" >&2
  exit 2
fi
mkdir -p "$CACHE_ROOT/ov" "$CACHE_ROOT/nvidia"
cp "$TASK_CONFIG" "$RESULT_DIR/task_config.json"
cp "$NAV2_PARAMS" "$RESULT_DIR/nav2_params.yaml"
if [[ "$TASK_MAP" != "-" ]]; then
  cp "$TASK_MAP" "$RESULT_DIR/nav2_map.yaml"
fi
RUN_TOKEN="unknown"
if [[ -s "$RUN_LOG_ROOT/$TASK_ID/run_token" ]]; then
  RUN_TOKEN=$(<"$RUN_LOG_ROOT/$TASK_ID/run_token")
fi

RUNNER_OVERVIEW="${RUNNER_OVERVIEW:-0}"
if [[ "$RUNNER_OVERVIEW" != "0" && "$RUNNER_OVERVIEW" != "1" ]]; then
  echo "RUNNER_OVERVIEW must be 0 or 1" >&2
  exit 3
fi
RUNNER_CHASE="${RUNNER_CHASE:-0}"
if [[ "$RUNNER_CHASE" != "0" && "$RUNNER_CHASE" != "1" ]]; then
  echo "RUNNER_CHASE must be 0 or 1" >&2
  exit 3
fi
DOCKER_OVERVIEW_ARGS=()
OVERVIEW_SPOOL_DIR=""
if [[ "$RUNNER_OVERVIEW" == "1" || "$RUNNER_CHASE" == "1" ]]; then
  OVERVIEW_RUNTIME="${OVERVIEW_RUNTIME_PATH:-$CACHE_ROOT/overview_runtime/m20_fourview_runner.py}"
  OVERVIEW_SPOOL_ROOT="$CACHE_ROOT/overview_spool"
  OVERVIEW_SPOOL_DIR="$OVERVIEW_SPOOL_ROOT/$RUN_ID"
  if [[ ! -s "$OVERVIEW_RUNTIME" ]]; then
    echo "Overview runtime copy is missing: $OVERVIEW_RUNTIME" >&2
    exit 3
  fi
  mkdir -p "$OVERVIEW_SPOOL_ROOT"
  if ! mkdir "$OVERVIEW_SPOOL_DIR"; then
    echo "Refusing to reuse overview spool: $OVERVIEW_SPOOL_DIR" >&2
    exit 2
  fi
  DOCKER_OVERVIEW_ARGS=(
    -v "$OVERVIEW_RUNTIME:/opt/safety_embodiment/competition_runner/runner/m20_runtime/runners/m20_fourview_runner.py:ro"
    -v "$OVERVIEW_SPOOL_ROOT:/opt/safety_embodiment/overview"
  )
  if [[ "$RUNNER_OVERVIEW" == "1" ]]; then
    DOCKER_OVERVIEW_ARGS+=(
      -e "NAV2_OVERVIEW_OUTPUT=/opt/safety_embodiment/overview/$RUN_ID/overview.mp4"
    )
  fi
  if [[ "$RUNNER_CHASE" == "1" ]]; then
    DOCKER_OVERVIEW_ARGS+=(
      -e "NAV2_CHASE_OUTPUT=/opt/safety_embodiment/overview/$RUN_ID/chase.mp4"
    )
  fi
fi

START_UNIX=$(date +%s)
CID_FILE="$RESULT_DIR/runner.cid"
RUNNER_TIMED_OUT=0
timeout \
  --signal=TERM \
  --kill-after="${RUNNER_TIMEOUT_KILL_AFTER_SECONDS}s" \
  "${RUNNER_WALL_TIMEOUT_SECONDS}s" \
  docker run --rm \
  --cidfile "$CID_FILE" \
  --device nvidia.com/gpu=0 \
  --network host \
  --ipc=host \
  -e ACCEPT_EULA=Y \
  -e PRIVACY_CONSENT=Y \
  -e NO_PROXY=127.0.0.1,localhost \
  -e no_proxy=127.0.0.1,localhost \
  -v "$PLAYER_RUNTIME:/opt/safety_embodiment/player_runtime:ro" \
  -v "$OUTPUT_ROOT:/opt/safety_embodiment/output" \
  -v "$RUNNER_CONFIG:/opt/safety_embodiment/config/ubuntu-teleop-runner.json:ro" \
  -v "$QUESTION_ROOT:/opt/safety_embodiment/question/unified_q01_q24_20260813:ro" \
  -v "$CACHE_ROOT/ov:/root/.cache/ov" \
  -v "$CACHE_ROOT/nvidia:/root/.cache/nvidia" \
  "${DOCKER_OVERVIEW_ARGS[@]}" \
  "$RUNNER_IMAGE" \
  --config /opt/safety_embodiment/config/ubuntu-teleop-runner.json \
  run \
  --task "$TASK_ID" \
  --run-id "$RUN_ID" \
  --policy-endpoint ws://127.0.0.1:18022 \
  --attack-mode off \
  --navigation-mode vla \
  --base-mode kinematic \
  --capture-hz 5 \
  --vla-action-hz "$ACTION_HZ" \
  --maximum-vla-actions "$MAX_ACTIONS" \
  --maximum-duration-seconds "$DURATION" \
  2>&1 | tee "$RESULT_DIR/runner.log"
RUNNER_STATUS=${PIPESTATUS[0]}
if [[ "$RUNNER_STATUS" -eq 124 ]]; then
  RUNNER_TIMED_OUT=1
  echo "RUNNER_WALL_TIMEOUT=$RUNNER_WALL_TIMEOUT_SECONDS" \
    | tee -a "$RESULT_DIR/runner.log" >&2
  if [[ -s "$CID_FILE" ]]; then
    RUNNER_CID=$(tr -d '[:space:]' <"$CID_FILE")
    if [[ "$RUNNER_CID" =~ ^[0-9a-f]{12,64}$ ]] \
        && docker inspect "$RUNNER_CID" >/dev/null 2>&1; then
      docker stop --time 30 "$RUNNER_CID" \
        >"$RESULT_DIR/runner_timeout_cleanup.log" 2>&1 \
        || docker kill "$RUNNER_CID" \
          >>"$RESULT_DIR/runner_timeout_cleanup.log" 2>&1 \
        || true
      docker rm -f "$RUNNER_CID" \
        >>"$RESULT_DIR/runner_timeout_cleanup.log" 2>&1 \
        || true
    fi
  fi
fi
END_UNIX=$(date +%s)

SOURCE_DIR="$OUTPUT_ROOT/$RUN_ID"
if [[ -d "$SOURCE_DIR" ]]; then
  docker run --rm \
    -v "$OUTPUT_ROOT:/output" \
    --entrypoint /bin/chown \
    "$RUNNER_IMAGE" \
    -R 1000:1000 "/output/$RUN_ID"
  chmod -R u+rwX "$SOURCE_DIR"
fi
VIDEO_SOURCE="$SOURCE_DIR/episode.mp4"
HDF5_SOURCE="$SOURCE_DIR/submission.hdf5"
VIDEO_SAVED=0
VIDEO_KIND="missing"
SUBMISSION_READY=0
OVERVIEW_SAVED=0
OVERVIEW_KIND="disabled"
CHASE_SAVED=0
CHASE_KIND="disabled"
if [[ -s "$VIDEO_SOURCE" ]]; then
  cp "$VIDEO_SOURCE" "$RESULT_DIR/episode.mp4"
  VIDEO_SAVED=1
  VIDEO_KIND="runner_episode"
fi

if [[ "$RUNNER_OVERVIEW" == "1" ]]; then
  OVERVIEW_SOURCE="$OVERVIEW_SPOOL_DIR/overview.mp4"
  OVERVIEW_KIND="missing"
  if [[ -s "$OVERVIEW_SOURCE" ]]; then
    cp "$OVERVIEW_SOURCE" "$RESULT_DIR/overview.mp4"
    OVERVIEW_SAVED=1
    OVERVIEW_KIND="isaac_global_overhead"
  elif command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -v error -y \
      -f lavfi -i "color=c=0x202020:s=1280x720:r=5" \
      -t 5 -c:v libx264 -pix_fmt yuv420p \
      -metadata title="$TASK_ID overview unavailable" \
      -metadata comment="No Isaac overview frames were produced; inspect runner.log" \
      "$RESULT_DIR/overview.mp4"
    if [[ -s "$RESULT_DIR/overview.mp4" ]]; then
      OVERVIEW_SAVED=1
      OVERVIEW_KIND="diagnostic_placeholder"
    fi
  fi
  rm -f "$OVERVIEW_SOURCE"
fi
if [[ "$RUNNER_CHASE" == "1" ]]; then
  CHASE_SOURCE="$OVERVIEW_SPOOL_DIR/chase.mp4"
  CHASE_KIND="missing"
  if [[ -s "$CHASE_SOURCE" ]]; then
    cp "$CHASE_SOURCE" "$RESULT_DIR/chase.mp4"
    CHASE_SAVED=1
    CHASE_KIND="isaac_third_person_chase"
  elif command -v ffmpeg >/dev/null 2>&1; then
    ffmpeg -v error -y \
      -f lavfi -i "color=c=0x202020:s=1280x720:r=5" \
      -t 5 -c:v libx264 -pix_fmt yuv420p \
      -metadata title="$TASK_ID chase view unavailable" \
      -metadata comment="No Isaac chase frames were produced; inspect runner.log" \
      "$RESULT_DIR/chase.mp4"
    if [[ -s "$RESULT_DIR/chase.mp4" ]]; then
      CHASE_SAVED=1
      CHASE_KIND="diagnostic_placeholder"
    fi
  fi
  rm -f "$CHASE_SOURCE"
fi
if [[ "$RUNNER_OVERVIEW" == "1" || "$RUNNER_CHASE" == "1" ]]; then
  rmdir "$OVERVIEW_SPOOL_DIR" 2>/dev/null || true
fi
if [[ -s "$HDF5_SOURCE" && "$VIDEO_KIND" == "runner_episode" ]]; then
  mkdir -p "$RESULT_DIR/submission"
  cp "$HDF5_SOURCE" "$RESULT_DIR/submission/episode.hdf5"
  cp "$VIDEO_SOURCE" "$RESULT_DIR/submission/episode.mp4"
  if "$PROJECT_DIR/scripts/validate_submission_pair.sh" \
      "$RESULT_DIR/submission" "$RUNNER_IMAGE" \
      >"$RESULT_DIR/submission_validation.log" 2>&1; then
    SUBMISSION_READY=1
  fi
fi
if [[ -s "$RUN_LOG_ROOT/$TASK_ID/navigation_status.json" ]]; then
  cp "$RUN_LOG_ROOT/$TASK_ID/navigation_status.json" "$RESULT_DIR/navigation_status.json"
fi
for LOG_NAME in nav2 policy preflight; do
  if [[ -s "$RUN_LOG_ROOT/$TASK_ID/$LOG_NAME.log" ]]; then
    cp "$RUN_LOG_ROOT/$TASK_ID/$LOG_NAME.log" "$RESULT_DIR/$LOG_NAME.log"
  fi
done

# An Isaac/Runner startup failure can happen before the official recorder opens.
# Preserve that failure as a valid, explicitly labelled video artifact so every
# batch entry remains reviewable. It is never counted as navigation success.
if [[ "$VIDEO_SAVED" -ne 1 ]] && command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -v error -y \
    -f lavfi -i "color=c=0x202020:s=1280x720:r=5" \
    -t 5 -c:v libx264 -pix_fmt yuv420p \
    -metadata title="$TASK_ID Runner startup failure" \
    -metadata comment="No official episode was produced; inspect runner.log" \
    "$RESULT_DIR/episode.mp4"
  if [[ -s "$RESULT_DIR/episode.mp4" ]]; then
    VIDEO_SAVED=1
    VIDEO_KIND="diagnostic_placeholder"
  fi
fi

cat >"$RESULT_DIR/run_summary.json" <<EOF
{
  "task": "$TASK_ID",
  "run_id": "$RUN_ID",
  "result_root": "$RESULT_ROOT",
  "run_token": "$RUN_TOKEN",
  "attack_mode": "off",
  "navigation_mode": "vla",
  "runner_status": $RUNNER_STATUS,
  "runner_timed_out": $RUNNER_TIMED_OUT,
  "runner_wall_timeout_s": $RUNNER_WALL_TIMEOUT_SECONDS,
  "video_saved": $VIDEO_SAVED,
  "video_kind": "$VIDEO_KIND",
  "submission_ready": $SUBMISSION_READY,
  "started_unix_s": $START_UNIX,
  "ended_unix_s": $END_UNIX,
  "maximum_duration_s": $DURATION,
  "maximum_vla_actions": $MAX_ACTIONS,
  "vla_action_hz": $ACTION_HZ,
  "task_config_sha256": "$TASK_CONFIG_SHA",
  "nav2_params_sha256": "$NAV2_PARAMS_SHA",
  "navigation_config_locked": $NAVIGATION_LOCKED,
  "uses_official_duration": $([[ "$DURATION" == "$DEFAULT_DURATION" ]] && echo true || echo false),
  "uses_official_action_limit": true
}
EOF

echo "TASK=$TASK_ID"
echo "RUN_ID=$RUN_ID"
echo "RUNNER_STATUS=$RUNNER_STATUS"
echo "RUNNER_TIMED_OUT=$RUNNER_TIMED_OUT"
echo "RUNNER_WALL_TIMEOUT_S=$RUNNER_WALL_TIMEOUT_SECONDS"
echo "VIDEO_SAVED=$VIDEO_SAVED"
echo "OVERVIEW_SAVED=$OVERVIEW_SAVED"
echo "OVERVIEW_KIND=$OVERVIEW_KIND"
echo "CHASE_SAVED=$CHASE_SAVED"
echo "CHASE_KIND=$CHASE_KIND"
echo "SUBMISSION_READY=$SUBMISSION_READY"
echo "RESULT_ROOT=$RESULT_ROOT"
echo "RESULT_DIR=$RESULT_DIR"

# Batch execution continues after task failures. A missing video after the
# diagnostic fallback is a separate artifact failure surfaced with status 20.
if [[ "$VIDEO_SAVED" -ne 1 ]]; then
  exit 20
fi
if [[ "$RUNNER_OVERVIEW" == "1" && "$OVERVIEW_SAVED" -ne 1 ]]; then
  exit 22
fi
if [[ "$RUNNER_CHASE" == "1" && "$CHASE_SAVED" -ne 1 ]]; then
  exit 23
fi
if [[ "$RUNNER_STATUS" -ne 0 ]]; then
  exit "$RUNNER_STATUS"
fi
if [[ "$SUBMISSION_READY" -ne 1 ]]; then
  exit 21
fi
exit 0
