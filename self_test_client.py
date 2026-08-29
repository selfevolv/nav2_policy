#!/usr/bin/env python3
"""Send fixed synthetic Runner observations and verify Nav2 produces base commands."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from websockets.sync.client import connect

import msgpack_numpy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", default="Q04")
    parser.add_argument("--compiled-tasks", required=True, type=Path)
    parser.add_argument("--endpoint", default="ws://127.0.0.1:18022")
    parser.add_argument("--requests", type=int, default=40)
    args = parser.parse_args()
    task = json.loads(args.compiled_tasks.read_text(encoding="utf-8"))["tasks"][
        args.task.upper()
    ]
    state = np.zeros(25, dtype=np.float32)
    state[:3] = np.asarray(task["spawn_xyz"], dtype=np.float32)
    state[5] = np.float32(task["spawn_yaw"])
    observation = {
        "observation/state": state,
        "prompt": task["prompt"],
    }
    commands: list[np.ndarray] = []
    with connect(args.endpoint, compression=None, max_size=None) as connection:
        metadata = msgpack_numpy.unpackb(connection.recv())
        print(f"METADATA={metadata}")
        for index in range(args.requests):
            connection.send(msgpack_numpy.packb(observation))
            response = msgpack_numpy.unpackb(connection.recv())
            command = np.asarray(response["actions"], dtype=np.float32)[0, :3]
            commands.append(command)
            print(
                f"REQUEST={index + 1}|CMD={command.tolist()}|"
                f"INFO={response.get('policy_info')}"
            )
            time.sleep(0.2)
    peak = float(np.max(np.abs(np.asarray(commands))))
    print(f"PEAK_COMMAND={peak:.6f}")
    if peak <= 0.001:
        print("SELF_TEST_FAILED=no non-zero Nav2 command")
        return 2
    print("SELF_TEST_OK=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
