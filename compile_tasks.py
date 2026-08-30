#!/usr/bin/env python3
"""Compile the public Q01-Q24 task metadata into one deterministic route table."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def scene_key(scene_usd: str) -> str:
    lowered = scene_usd.lower()
    if "warehouse" in lowered:
        return "warehouse"
    if "kitchen" in lowered:
        return "kitchen"
    if "market" in lowered:
        return "market"
    raise ValueError(f"unknown scene path: {scene_usd}")


def normalized_prompt(value: str) -> str:
    return " ".join(value.strip().split())


def waypoint_yaws(points: list[list[float]], final_yaw: float) -> list[float]:
    yaws: list[float] = []
    for index, point in enumerate(points):
        if index + 1 < len(points):
            nxt = points[index + 1]
            yaws.append(math.atan2(nxt[1] - point[1], nxt[0] - point[0]))
        else:
            yaws.append(float(final_yaw))
    return yaws


def navigation_acceptance(
    task: dict[str, Any], route: dict[str, Any], points: list[list[float]]
) -> dict[str, Any]:
    """Return the public navigation-only condition or the route controller gate."""
    route_tolerance = float(
        route.get("controller", {}).get("arrival_tolerance_m", 0.25)
    )
    if task.get("execution_mode") == "navigation_only":
        conditions = task.get("termination", {}).get("success", {}).get("conditions", [])
        for condition in conditions:
            params = condition.get("params", {})
            if condition.get("evaluator") != "robot_near_target":
                continue
            target = params.get("target_xyz")
            distance = params.get("distance_m")
            if not isinstance(target, list) or len(target) < 2 or distance is None:
                continue
            return {
                "source": "task_success_condition",
                "target_xyz": [float(value) for value in target],
                "axes": str(params.get("axes", "xy")),
                "distance_m": float(distance),
                "stable_steps": int(condition.get("stable_steps", 1)),
                "condition_id": condition.get("id"),
            }
    return {
        "source": "route_controller",
        "target_xyz": [float(points[-1][0]), float(points[-1][1])],
        "axes": "xy",
        "distance_m": route_tolerance,
        "stable_steps": 1,
        "condition_id": "route_arrival",
    }


def compile_one(question_dir: Path) -> dict[str, Any]:
    route_path = question_dir / "data/env/route.json"
    task_path = question_dir / "data/task/task.json"
    environment_path = question_dir / "data/env/environment.json"
    route = json.loads(route_path.read_text(encoding="utf-8"))
    task = json.loads(task_path.read_text(encoding="utf-8"))
    environment = json.loads(environment_path.read_text(encoding="utf-8"))

    points = [[float(p[0]), float(p[1])] for p in route.get("waypoints", [])]
    if not points:
        raise ValueError(f"{question_dir.name}: route contains no waypoints")
    spawn_xyz = [float(v) for v in route["spawn"]["xyz"]]
    spawn_yaw = float(route["spawn"].get("yaw_rad", 0.0))
    station = task.get("operation_station", {})
    final_yaw = float(station.get("yaw_rad", waypoint_yaws(points, 0.0)[-1]))
    prompt = normalized_prompt(task.get("policy_instruction") or task["instruction"])
    scene_usd = str((question_dir / environment["scene_usd"]).resolve())

    question_id = question_dir.name.upper()
    acceptance = navigation_acceptance(task, route, points)
    return {
        "question_id": question_id,
        "task_id": task["task_id"],
        "execution_mode": task["execution_mode"],
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "scene": scene_key(environment["scene_usd"]),
        "scene_usd": scene_usd,
        "spawn_xyz": spawn_xyz,
        "spawn_yaw": spawn_yaw,
        "waypoints_xy": points,
        "waypoint_yaws": waypoint_yaws(points, final_yaw),
        "navigation_goal_xy": points[-1],
        "operation_station_xyz": station.get("base_xyz"),
        "operation_station_yaw": station.get("yaw_rad"),
        "route_arrival_tolerance_m": float(
            route.get("controller", {}).get("arrival_tolerance_m", 0.25)
        ),
        "navigation_acceptance": acceptance,
        "maximum_duration_s": int(route.get("maximum_duration_s", 300)),
        "maximum_vla_actions": int(task.get("maximum_vla_actions", 600)),
        "source": {
            "route": str(route_path),
            "task": str(task_path),
            "environment": str(environment_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--question-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    question_dirs = sorted(
        args.question_root.glob("Q[0-9][0-9]"), key=lambda path: int(path.name[1:])
    )
    tasks = [compile_one(path) for path in question_dirs]
    if len(tasks) != 24:
        raise RuntimeError(f"expected 24 tasks, found {len(tasks)}")
    payload = {
        "schema": "m20-nav2-compiled-tasks/v1",
        "question_root": str(args.question_root.resolve()),
        "tasks": {task["question_id"]: task for task in tasks},
        "prompt_to_question": {task["prompt"]: task["question_id"] for task in tasks},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"COMPILED_TASKS={len(tasks)}")
    print(f"OUTPUT={args.output}")
    for task in tasks:
        print(
            f"{task['question_id']}|{task['scene']}|"
            f"waypoints={len(task['waypoints_xy'])}|goal={task['navigation_goal_xy']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
