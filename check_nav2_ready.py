#!/usr/bin/env python3
"""Verify one isolated Nav2 stack without sending a navigation goal."""

from __future__ import annotations

import argparse
import json
import socket
import time
from pathlib import Path

import rclpy
from lifecycle_msgs.msg import State
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateThroughPoses
from rclpy.action import ActionClient
from rclpy.node import Node


LIFECYCLE_NODES = (
    "map_server",
    "controller_server",
    "smoother_server",
    "planner_server",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
    "velocity_smoother",
)


def load_status(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--run-token", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18022)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()

    rclpy.init()
    node = Node("m20_nav2_preflight")
    clients = {
        name: node.create_client(GetState, f"/{name}/get_state")
        for name in LIFECYCLE_NODES
    }
    action_client = ActionClient(
        node, NavigateThroughPoses, "/navigate_through_poses"
    )
    deadline = time.monotonic() + args.timeout
    last_states: dict[str, str] = {}
    last_status: dict = {}
    try:
        while time.monotonic() < deadline:
            last_status = load_status(args.status)
            fresh_bridge = (
                last_status.get("run_token") == args.run_token
                and last_status.get("request_count") == 0
                and not last_status.get("goal_sent", False)
            )
            current_states: dict[str, str] = {}
            for name, client in clients.items():
                if not client.wait_for_service(timeout_sec=0.15):
                    current_states[name] = "service_unavailable"
                    continue
                future = client.call_async(GetState.Request())
                rclpy.spin_until_future_complete(node, future, timeout_sec=0.5)
                if not future.done() or future.result() is None:
                    current_states[name] = "no_response"
                    continue
                state = future.result().current_state
                current_states[name] = f"{state.label}:{state.id}"
            last_states = current_states
            lifecycle_active = all(
                value.endswith(f":{State.PRIMARY_STATE_ACTIVE}")
                for value in current_states.values()
            )
            action_ready = action_client.wait_for_server(timeout_sec=0.2)
            if (
                fresh_bridge
                and lifecycle_active
                and action_ready
                and port_open(args.host, args.port)
            ):
                print(
                    json.dumps(
                        {
                            "ready": True,
                            "run_token": args.run_token,
                            "lifecycle": current_states,
                            "action_server": True,
                            "goal_sent": False,
                            "request_count": 0,
                        },
                        ensure_ascii=False,
                    )
                )
                return 0
            time.sleep(0.5)
        print(
            json.dumps(
                {
                    "ready": False,
                    "run_token": args.run_token,
                    "lifecycle": last_states,
                    "bridge_status": last_status,
                    "policy_port": port_open(args.host, args.port),
                    "action_server": action_client.wait_for_server(timeout_sec=0.2),
                },
                ensure_ascii=False,
            )
        )
        return 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
