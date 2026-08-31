#!/usr/bin/env bash
set -o pipefail

TASK_ID="${1:?usage: run_runner_task.sh Qxx [run-id]}"
PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
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
IFS=$'\t' read -r TASK_CONFIG NAV2_PARAMS ACTION_HZ TASK_CONFIG_SHA NAV2_PARAMS_SHA NAVIGATION_LOCKED \
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
RUN_TOKEN="unknown"
if [[ -s "$PROJECT_DIR/logs/$TASK_ID/run_token" ]]; then
  RUN_TOKEN=$(<"$PROJECT_DIR/logs/$TASK_ID/run_token")
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
if [[ -s "$VIDEO_SOURCE" ]]; then
  cp "$VIDEO_SOURCE" "$RESULT_DIR/episode.mp4"
  VIDEO_SAVED=1
  VIDEO_KIND="runner_episode"
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
if [[ -s "$PROJECT_DIR/logs/$TASK_ID/navigation_status.json" ]]; then
  cp "$PROJECT_DIR/logs/$TASK_ID/navigation_status.json" "$RESULT_DIR/navigation_status.json"
fi
for LOG_NAME in nav2 policy preflight; do
  if [[ -s "$PROJECT_DIR/logs/$TASK_ID/$LOG_NAME.log" ]]; then
    cp "$PROJECT_DIR/logs/$TASK_ID/$LOG_NAME.log" "$RESULT_DIR/$LOG_NAME.log"
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
echo "SUBMISSION_READY=$SUBMISSION_READY"
echo "RESULT_ROOT=$RESULT_ROOT"
echo "RESULT_DIR=$RESULT_DIR"

# Batch execution continues after task failures. A missing video after the
# diagnostic fallback is a separate artifact failure surfaced with status 20.
if [[ "$VIDEO_SAVED" -ne 1 ]]; then
  exit 20
fi
if [[ "$RUNNER_STATUS" -ne 0 ]]; then
  exit "$RUNNER_STATUS"
fi
if [[ "$SUBMISSION_READY" -ne 1 ]]; then
  exit 21
fi
exit 0
