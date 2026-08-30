#!/usr/bin/env bash
set -eo pipefail

PAIR_DIR="${1:?usage: validate_submission_pair.sh submission-dir [runner-image]}"
RUNNER_IMAGE="${2:-safety-embodiment:20260817}"

[[ -s "$PAIR_DIR/episode.hdf5" ]]
[[ -s "$PAIR_DIR/episode.mp4" ]]

docker run --rm \
  -v "$PAIR_DIR:/submission:ro" \
  --entrypoint /opt/robolab-env/bin/python \
  "$RUNNER_IMAGE" \
  -c 'import h5py; p="/submission/episode.hdf5"; f=h5py.File(p,"r"); assert set(f.keys()) == {"metadata", "data"}, sorted(f.keys()); assert list(f["data"].keys()) == ["demo_0"], list(f["data"].keys()); assert f["metadata"].attrs.get("complete") in (True, 1); print("SUBMISSION_PAIR_VALID=1")'
