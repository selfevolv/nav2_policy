"""ROS 2 bridge between Runner observations and a Nav2 navigation stack."""

from __future__ import annotations

import json
import math
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import rclpy
from geometry_msgs.msg import PoseStamped, TransformStamped, Twist
from nav2_msgs.action import NavigateThroughPoses
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.node import Node
from tf2_ros import StaticTransformBroadcaster, TransformBroadcaster


def yaw_quaternion(yaw: float) -> tuple[float, float, float, float]:
    half = yaw * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


class NavigationBridge(Node):
    """Publish ground-truth odometry, submit the public route, and sample cmd_vel."""

    def __init__(
        self, task: dict[str, Any], status_path: Path, run_token: str = "manual"
    ) -> None:
        super().__init__("m20_nav2_policy_bridge")
        self.task = task
        self.status_path = status_path
        self.run_token = run_token
        self.started_unix_s = time.time()
        self._lock = threading.RLock()
        self._status_write_lock = threading.Lock()
        # Seed TF from the public spawn pose so Nav2 can finish its lifecycle
        # before Isaac Sim starts. Safety still requires a fresh real observation
        # before any command is returned to Runner.
        self._state: np.ndarray | None = np.zeros(25, dtype=np.float32)
        self._state[0:3] = np.asarray(task["spawn_xyz"], dtype=np.float32)
        self._state[5] = np.float32(task["spawn_yaw"])
        self._observation_monotonic: float | None = None
        self._last_cmd = np.zeros(3, dtype=np.float64)
        self._last_cmd_monotonic: float | None = None
        self._goal_sent = False
        self._goal_attempts = 0
        self._goal_accepted = False
        self._goal_status = "waiting_for_runner_observation"
        self._goal_result_code: int | None = None
        self._stable_goal_observations = 0
        self._navigation_reached = False
        self._navigation_stop_requested = False
        self._minimum_goal_distance = float("inf")
        self._minimum_acceptance_distance = float("inf")
        self._request_count = 0
        self._maximum_goal_attempts = 3
        self._goal_terminal_failure = False
        self._next_goal_attempt_monotonic = 0.0
        self._route_tolerance = float(task["route_arrival_tolerance_m"])
        self._acceptance = task.get(
            "navigation_acceptance",
            {
                "source": "route_controller",
                "target_xyz": task["navigation_goal_xy"],
                "axes": "xy",
                "distance_m": self._route_tolerance,
                "stable_steps": 1,
            },
        )

        self.odom_publisher = self.create_publisher(Odometry, "/odom", 20)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.static_tf_broadcaster = StaticTransformBroadcaster(self)
        self.cmd_subscription = self.create_subscription(
            Twist, "/cmd_vel", self._on_cmd_vel, 20
        )
        self.action_client = ActionClient(
            self, NavigateThroughPoses, "/navigate_through_poses"
        )
        self.create_timer(0.05, self._publish_latest_pose)
        self.create_timer(0.5, self._try_send_goal)
        self._publish_map_to_odom()
        self.write_status()

    def _publish_map_to_odom(self) -> None:
        transform = TransformStamped()
        transform.header.stamp = self.get_clock().now().to_msg()
        transform.header.frame_id = "map"
        transform.child_frame_id = "odom"
        transform.transform.rotation.w = 1.0
        self.static_tf_broadcaster.sendTransform(transform)

    def update_observation(self, state: np.ndarray) -> None:
        state = np.asarray(state, dtype=np.float32)
        if state.shape != (25,) or not np.isfinite(state).all():
            raise ValueError(f"state must be finite float32[25], got {state.shape}")
        goal_x, goal_y = self.task["navigation_goal_xy"]
        route_distance = math.hypot(
            float(state[0]) - goal_x, float(state[1]) - goal_y
        )
        target = self._acceptance["target_xyz"]
        axes = str(self._acceptance.get("axes", "xy"))
        dimensions = 3 if axes == "xyz" and len(target) >= 3 else 2
        acceptance_distance = math.sqrt(
            sum(
                (float(state[index]) - float(target[index])) ** 2
                for index in range(dimensions)
            )
        )
        acceptance_radius = float(self._acceptance["distance_m"])
        with self._lock:
            self._state = state.copy()
            self._observation_monotonic = time.monotonic()
            self._request_count += 1
            self._minimum_goal_distance = min(
                self._minimum_goal_distance, route_distance
            )
            self._minimum_acceptance_distance = min(
                self._minimum_acceptance_distance, acceptance_distance
            )
            if acceptance_distance <= acceptance_radius:
                self._navigation_reached = True
            if route_distance <= self._route_tolerance:
                self._stable_goal_observations += 1
            else:
                self._stable_goal_observations = 0
            if self._stable_goal_observations >= 10:
                self._navigation_stop_requested = True
                self._goal_status = "navigation_reached"
        self.write_status()

    def _publish_latest_pose(self) -> None:
        with self._lock:
            if self._state is None:
                return
            state = self._state.copy()
        stamp = self.get_clock().now().to_msg()
        qx, qy, qz, qw = yaw_quaternion(float(state[5]))

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = "odom"
        odom.child_frame_id = "base_link"
        odom.pose.pose.position.x = float(state[0])
        odom.pose.pose.position.y = float(state[1])
        odom.pose.pose.position.z = 0.0
        odom.pose.pose.orientation.x = qx
        odom.pose.pose.orientation.y = qy
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.twist.twist.linear.x = float(state[6])
        odom.twist.twist.linear.y = float(state[7])
        odom.twist.twist.angular.z = float(state[11])
        self.odom_publisher.publish(odom)

        transform = TransformStamped()
        transform.header.stamp = stamp
        transform.header.frame_id = "odom"
        transform.child_frame_id = "base_link"
        transform.transform.translation.x = float(state[0])
        transform.transform.translation.y = float(state[1])
        transform.transform.translation.z = 0.0
        transform.transform.rotation.x = qx
        transform.transform.rotation.y = qy
        transform.transform.rotation.z = qz
        transform.transform.rotation.w = qw
        self.tf_broadcaster.sendTransform(transform)

    def _try_send_goal(self) -> None:
        now = time.monotonic()
        with self._lock:
            observation_fresh = (
                self._observation_monotonic is not None
                and now - self._observation_monotonic <= 0.75
            )
            if not observation_fresh:
                if self._observation_monotonic is None:
                    self._goal_status = "waiting_for_runner_observation"
                return
            if (
                self._goal_sent
                or self._state is None
                or self._goal_terminal_failure
                or now < self._next_goal_attempt_monotonic
            ):
                return
        if not self.action_client.wait_for_server(timeout_sec=0.0):
            with self._lock:
                self._goal_status = "waiting_for_nav2"
            return

        goal = NavigateThroughPoses.Goal()
        yaws = self.task["waypoint_yaws"]
        for index, (x, y) in enumerate(self.task["waypoints_xy"]):
            pose = PoseStamped()
            pose.header.frame_id = "map"
            pose.header.stamp = self.get_clock().now().to_msg()
            pose.pose.position.x = float(x)
            pose.pose.position.y = float(y)
            qx, qy, qz, qw = yaw_quaternion(float(yaws[index]))
            pose.pose.orientation.x = qx
            pose.pose.orientation.y = qy
            pose.pose.orientation.z = qz
            pose.pose.orientation.w = qw
            goal.poses.append(pose)

        with self._lock:
            self._goal_sent = True
            self._goal_attempts += 1
            self._goal_status = "goal_sending"
        future = self.action_client.send_goal_async(goal)
        future.add_done_callback(self._goal_response)
        self.get_logger().info(
            f"Submitted {len(goal.poses)} poses for {self.task['question_id']}"
        )

    def _schedule_goal_retry_locked(self, reason: str) -> None:
        """Retry a failed action at most twice after the initial request."""
        self._goal_sent = False
        self._goal_accepted = False
        self._last_cmd[:] = 0.0
        if self._goal_attempts >= self._maximum_goal_attempts:
            self._goal_terminal_failure = True
            self._goal_status = f"{reason}_attempts_exhausted"
            return
        delay_s = min(4.0, float(2 ** max(0, self._goal_attempts - 1)))
        self._next_goal_attempt_monotonic = time.monotonic() + delay_s
        self._goal_status = f"{reason}_retrying"

    def _goal_response(self, future: Any) -> None:
        try:
            handle = future.result()
        except Exception as error:
            self.get_logger().warning(f"Goal request failed; retrying: {error}")
            with self._lock:
                self._schedule_goal_retry_locked("goal_request_failed")
            self.write_status()
            return
        if handle is None or not handle.accepted:
            with self._lock:
                self._schedule_goal_retry_locked("goal_rejected")
            self.write_status()
            return
        with self._lock:
            self._goal_accepted = True
            self._goal_status = "navigating"
        result_future = handle.get_result_async()
        result_future.add_done_callback(self._goal_result)
        self.write_status()

    def _goal_result(self, future: Any) -> None:
        try:
            wrapped = future.result()
        except Exception as error:
            self.get_logger().warning(f"Goal result failed: {error}")
            with self._lock:
                self._schedule_goal_retry_locked("goal_result_failed")
            self.write_status()
            return
        code = None if wrapped is None else int(wrapped.status)
        with self._lock:
            self._goal_result_code = code
            if code == 4:
                self._goal_status = "nav2_succeeded"
                self._navigation_reached = True
                self._navigation_stop_requested = True
            elif self._navigation_reached:
                self._goal_status = f"navigation_reached_nav2_finished_{code}"
                self._navigation_stop_requested = True
            else:
                self._schedule_goal_retry_locked(f"nav2_finished_{code}")
            if self._navigation_stop_requested:
                self._last_cmd[:] = 0.0
        self.write_status()

    def _on_cmd_vel(self, message: Twist) -> None:
        command = np.asarray(
            [message.linear.x, message.linear.y, message.angular.z], dtype=np.float64
        )
        if not np.isfinite(command).all():
            self.get_logger().error("Rejected non-finite cmd_vel")
            return
        command[0] = np.clip(command[0], -0.25, 0.25)
        command[1] = np.clip(command[1], -0.12, 0.12)
        command[2] = np.clip(command[2], -0.30, 0.30)
        with self._lock:
            self._last_cmd = command
            self._last_cmd_monotonic = time.monotonic()

    def action(self) -> np.ndarray:
        action = np.zeros((1, 10), dtype=np.float32)
        now = time.monotonic()
        with self._lock:
            observation_age = (
                None
                if self._observation_monotonic is None
                else now - self._observation_monotonic
            )
            command_age = (
                None
                if self._last_cmd_monotonic is None
                else now - self._last_cmd_monotonic
            )
            safe = (
                not self._navigation_stop_requested
                and observation_age is not None
                and observation_age <= 0.75
                and command_age is not None
                and command_age <= 0.50
            )
            if safe:
                action[0, :3] = self._last_cmd.astype(np.float32)
        return action

    def status(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            state = None if self._state is None else self._state.tolist()
            observation_age = (
                None
                if self._observation_monotonic is None
                else now - self._observation_monotonic
            )
            command_age = (
                None
                if self._last_cmd_monotonic is None
                else now - self._last_cmd_monotonic
            )
            return {
                "schema": "m20-nav2-policy-status/v1",
                "run_token": self.run_token,
                "started_unix_s": self.started_unix_s,
                "question_id": self.task["question_id"],
                "scene": self.task["scene"],
                "goal_xy": self.task["navigation_goal_xy"],
                "goal_status": self._goal_status,
                "goal_sent": self._goal_sent,
                "goal_attempts": self._goal_attempts,
                "maximum_goal_attempts": self._maximum_goal_attempts,
                "goal_accepted": self._goal_accepted,
                "goal_terminal_failure": self._goal_terminal_failure,
                "goal_result_code": self._goal_result_code,
                "navigation_reached": self._navigation_reached,
                "navigation_stop_requested": self._navigation_stop_requested,
                "navigation_acceptance": self._acceptance,
                "route_arrival_tolerance_m": self._route_tolerance,
                "stable_goal_observations": self._stable_goal_observations,
                "minimum_goal_distance_m": (
                    None
                    if not math.isfinite(self._minimum_goal_distance)
                    else self._minimum_goal_distance
                ),
                "minimum_acceptance_distance_m": (
                    None
                    if not math.isfinite(self._minimum_acceptance_distance)
                    else self._minimum_acceptance_distance
                ),
                "request_count": self._request_count,
                "observation_age_s": observation_age,
                "command_age_s": command_age,
                "last_cmd_vel": self._last_cmd.tolist(),
                "last_state": state,
                "updated_unix_s": time.time(),
            }

    def write_status(self) -> None:
        payload = self.status()
        with self._status_write_lock:
            self.status_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.status_path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.status_path)
