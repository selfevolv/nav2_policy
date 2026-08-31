#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/mnt/data/samba/tianchi/2026-具身安全应用挑战赛/runner-runtime/policy/nav2_policy}"
RUNNER_IMAGE="${RUNNER_IMAGE:-safety-embodiment:20260817}"
CACHE_ROOT="$PROJECT_DIR/cache"
RUNTIME_DIR="$CACHE_ROOT/overview_runtime"
RUNTIME_PATH="$RUNTIME_DIR/m20_fourview_runner.py"
INTERNAL_RUNTIME="/opt/safety_embodiment/competition_runner/runner/m20_runtime/runners/m20_fourview_runner.py"

mkdir -p "$CACHE_ROOT"
BUILD_DIR=$(mktemp -d "$CACHE_ROOT/overview-runtime-build.XXXXXX")
SOURCE_PATH="$BUILD_DIR/m20_fourview_runner.official.py"
BUILT_PATH="$BUILD_DIR/m20_fourview_runner.py"
CONTAINER_ID=""

cleanup() {
  if [[ -n "$CONTAINER_ID" ]]; then
    docker rm -f "$CONTAINER_ID" >/dev/null 2>&1 || true
  fi
  rm -f "$SOURCE_PATH" "$BUILT_PATH"
  rmdir "$BUILD_DIR" 2>/dev/null || true
}
trap cleanup EXIT

CONTAINER_ID=$(docker create "$RUNNER_IMAGE")
docker cp "$CONTAINER_ID:$INTERNAL_RUNTIME" "$SOURCE_PATH"
docker rm "$CONTAINER_ID" >/dev/null
CONTAINER_ID=""

python3 "$PROJECT_DIR/build_overview_runtime.py" \
  --source "$SOURCE_PATH" \
  --output "$BUILT_PATH"

mkdir -p "$RUNTIME_DIR"
if [[ -e "$RUNTIME_PATH" ]]; then
  if ! cmp -s "$BUILT_PATH" "$RUNTIME_PATH"; then
    echo "Refusing to overwrite a different overview runtime copy: $RUNTIME_PATH" >&2
    exit 2
  fi
else
  mv "$BUILT_PATH" "$RUNTIME_PATH"
fi
python3 -m py_compile "$RUNTIME_PATH"

echo "OFFICIAL_RUNNER_IMAGE=$RUNNER_IMAGE"
echo "OVERVIEW_RUNTIME_COPY=$RUNTIME_PATH"
sha256sum "$RUNTIME_PATH"
