#!/usr/bin/env python3
"""Official Runner-compatible Policy server backed by an external Nav2 stack."""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import rclpy
from rclpy.executors import MultiThreadedExecutor
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import serve

import msgpack_numpy
from navigation_bridge import NavigationBridge


LOGGER = logging.getLogger("m20_nav2_policy")
METADATA = {
    "policy_type": "m20-nav2-smac-mppi-navigation",
    "protocol": "openpi-websocket/pi0.5",
    "action_dim": 10,
    "state_dim": 25,
    "action_semantics": [
        "base_vx_mps",
        "base_vy_mps",
        "base_yaw_rate_rps",
        "tcp_dx_m",
        "tcp_dy_m",
        "tcp_dz_m",
        "tcp_droll_rad",
        "tcp_dpitch_rad",
        "tcp_dyaw_rad",
        "gripper_close_0_to_1",
    ],
}


def load_task(path: Path, question_id: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    key = question_id.upper()
    if key not in payload["tasks"]:
        raise KeyError(f"unknown task: {question_id}")
    return payload["tasks"][key]


def validate_state(observation: Any) -> np.ndarray:
    if not isinstance(observation, dict):
        raise ValueError("Policy observation must be a map")
    state = np.asarray(observation.get("observation/state"))
    if state.shape != (25,) or not np.isfinite(state).all():
        raise ValueError(f"observation/state must be finite [25], got {state.shape}")
    return np.ascontiguousarray(state, dtype=np.float32)


def make_handler(bridge: NavigationBridge):
    packer = msgpack_numpy.Packer()

    def handler(connection: Any) -> None:
        LOGGER.info("Runner connected: %s", connection.remote_address)
        connection.send(packer.pack(METADATA))
        try:
            for raw in connection:
                started = time.perf_counter()
                if not isinstance(raw, bytes):
                    raise ValueError("Policy request must be binary MessagePack")
                observation = msgpack_numpy.unpackb(raw)
                bridge.update_observation(validate_state(observation))
                actions = bridge.action()
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                status = bridge.status()
                response = {
                    "actions": actions,
                    "policy_info": {
                        "source": "nav2-smac-mppi",
                        "question_id": bridge.task["question_id"],
                        "goal_status": status["goal_status"],
                        "navigation_reached": status["navigation_reached"],
                        "inference_ms": elapsed_ms,
                    },
                }
                connection.send(packer.pack(response))
        except ConnectionClosed as error:
            LOGGER.info("Runner disconnected: %s", error)
        except Exception:
            LOGGER.exception("Policy connection failed")

    return handler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--compiled-tasks", required=True, type=Path)
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18022)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    task = load_task(args.compiled_tasks, args.task)
    rclpy.init()
    bridge = NavigationBridge(task, args.status)
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(bridge)
    ros_thread = threading.Thread(target=executor.spin, daemon=True, name="rclpy-executor")
    ros_thread.start()
    LOGGER.info(
        "Policy task=%s scene=%s goal=%s",
        task["question_id"],
        task["scene"],
        task["navigation_goal_xy"],
    )
    try:
        with serve(
            make_handler(bridge), args.host, args.port, compression=None, max_size=None
        ) as server:
            LOGGER.info("Listening on ws://%s:%d", args.host, args.port)
            server.serve_forever()
    finally:
        executor.shutdown()
        bridge.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
