#!/usr/bin/env bash
set -o pipefail

TASK_ID="${1:?usage: run_runner_task.sh Qxx [run-id]}"
RUN_ID="${2:-nav2_${TASK_ID,,}_$(date +%Y%m%d_%H%M%S)}"
PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
OUTPUT_ROOT="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/output"
QUESTION_ROOT="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/question_to_player"
PLAYER_RUNTIME="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/player_runtime"
RUNNER_CONFIG="/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/config/ubuntu-teleop-runner.json"
RUNNER_IMAGE="safety-embodiment:20260817"
CACHE_ROOT="$PROJECT_DIR/cache"

read -r DEFAULT_DURATION MAX_ACTIONS ACTION_HZ < <(
  python3 -c 'import json,sys; task=json.load(open(sys.argv[1]))["tasks"][sys.argv[2].upper()]; print(task["maximum_duration_s"], task["maximum_vla_actions"], task.get("recommended_vla_action_hz", 5))' \
    "$PROJECT_DIR/compiled_tasks.json" "$TASK_ID"
)
DURATION="${RUNNER_MAX_DURATION_SECONDS:-$DEFAULT_DURATION}"
RESULT_DIR="$PROJECT_DIR/results/$TASK_ID/$RUN_ID"
mkdir -p "$RESULT_DIR" "$CACHE_ROOT/ov" "$CACHE_ROOT/nvidia"
RUN_TOKEN="unknown"
if [[ -s "$PROJECT_DIR/logs/$TASK_ID/run_token" ]]; then
  RUN_TOKEN=$(<"$PROJECT_DIR/logs/$TASK_ID/run_token")
fi

START_UNIX=$(date +%s)
docker run --rm \
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
  "run_token": "$RUN_TOKEN",
  "attack_mode": "off",
  "navigation_mode": "vla",
  "runner_status": $RUNNER_STATUS,
  "video_saved": $VIDEO_SAVED,
  "video_kind": "$VIDEO_KIND",
  "submission_ready": $SUBMISSION_READY,
  "started_unix_s": $START_UNIX,
  "ended_unix_s": $END_UNIX,
  "maximum_duration_s": $DURATION,
  "maximum_vla_actions": $MAX_ACTIONS,
  "vla_action_hz": $ACTION_HZ,
  "uses_official_duration": $([[ "$DURATION" == "$DEFAULT_DURATION" ]] && echo true || echo false),
  "uses_official_action_limit": true
}
EOF

echo "TASK=$TASK_ID"
echo "RUN_ID=$RUN_ID"
echo "RUNNER_STATUS=$RUNNER_STATUS"
echo "VIDEO_SAVED=$VIDEO_SAVED"
echo "SUBMISSION_READY=$SUBMISSION_READY"
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
