#!/usr/bin/env python3
"""Load and validate one isolated Q01-Q24 policy configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SCHEMA = "m20-nav2-task-config/v1"
TASK_PATTERN = re.compile(r"Q(?:0[1-9]|1[0-9]|2[0-4])")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_config_file(
    manifest_path: Path,
    config_root: Path,
    value: Any,
    expected_hash: Any,
    label: str,
) -> tuple[Path, str]:
    """Resolve and hash-check one file that must remain under config/."""
    if not isinstance(value, str) or not isinstance(expected_hash, str):
        raise ValueError(f"{manifest_path}: incomplete {label} reference")
    path = (manifest_path.parent / value).resolve()
    try:
        path.relative_to(config_root)
    except ValueError as error:
        raise ValueError(f"{manifest_path}: {label} escapes config directory") from error
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise ValueError(
            f"{manifest_path}: {label} hash mismatch; expected {expected_hash}, "
            f"got {actual_hash}"
        )
    return path, actual_hash


def load_task_config(config_dir: Path, task_id: str) -> dict[str, Any]:
    task_id = task_id.upper()
    if not TASK_PATTERN.fullmatch(task_id):
        raise ValueError(f"invalid task id: {task_id}")

    config_dir = config_dir.resolve()
    manifest_path = config_dir / f"{task_id}.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"{manifest_path}: unsupported schema")
    if payload.get("task_id") != task_id:
        raise ValueError(f"{manifest_path}: task_id mismatch")

    nav2 = payload.get("nav2", {})
    profile_value = nav2.get("params_file")
    expected_hash = nav2.get("params_sha256")
    if not isinstance(profile_value, str) or not isinstance(expected_hash, str):
        raise ValueError(f"{manifest_path}: incomplete nav2 profile reference")
    profile_path, actual_hash = resolve_config_file(
        manifest_path,
        config_dir.parent,
        profile_value,
        expected_hash,
        "profile",
    )

    action_hz = payload.get("runner", {}).get("vla_action_hz")
    if not isinstance(action_hz, int) or action_hz <= 0 or 50 % action_hz:
        raise ValueError(f"{manifest_path}: vla_action_hz must divide 50")

    payload["manifest_path"] = str(manifest_path)
    payload["manifest_sha256"] = sha256_file(manifest_path)
    payload["nav2_params_file"] = str(profile_path)
    payload["nav2_params_sha256"] = actual_hash

    map_config = nav2.get("map")
    if map_config is not None:
        if not isinstance(map_config, dict):
            raise ValueError(f"{manifest_path}: nav2.map must be an object")
        map_path, map_hash = resolve_config_file(
            manifest_path,
            config_dir.parent,
            map_config.get("yaml_file"),
            map_config.get("yaml_sha256"),
            "Nav2 map YAML",
        )
        image_path, image_hash = resolve_config_file(
            manifest_path,
            config_dir.parent,
            map_config.get("image_file"),
            map_config.get("image_sha256"),
            "Nav2 map image",
        )
        image_line = next(
            (
                line.split(":", 1)[1].strip().strip('"\'')
                for line in map_path.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("image:")
            ),
            None,
        )
        if image_line is None or (map_path.parent / image_line).resolve() != image_path:
            raise ValueError(
                f"{manifest_path}: Nav2 map YAML image does not match image_file"
            )
        payload["nav2_map_file"] = str(map_path)
        payload["nav2_map_sha256"] = map_hash
        payload["nav2_map_image_file"] = str(image_path)
        payload["nav2_map_image_sha256"] = image_hash

    navigation = payload.get("navigation", {})
    if not isinstance(navigation, dict):
        raise ValueError(f"{manifest_path}: navigation must be an object")
    route_value = navigation.get("route_override_file")
    route_hash_value = navigation.get("route_override_sha256")
    if route_value is not None or route_hash_value is not None:
        route_path, route_hash = resolve_config_file(
            manifest_path,
            config_dir.parent,
            route_value,
            route_hash_value,
            "route override",
        )
        payload["route_override_file"] = str(route_path)
        payload["route_override_sha256"] = route_hash
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "config/tasks",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    resolve = subparsers.add_parser("resolve")
    resolve.add_argument("task")
    resolve.add_argument(
        "--format", choices=("json", "shell"), default="json"
    )
    subparsers.add_parser("validate-all")
    args = parser.parse_args()

    if args.command == "resolve":
        payload = load_task_config(args.config_dir, args.task)
        if args.format == "shell":
            regression = payload.get("regression", {})
            print(
                "\t".join(
                    [
                        payload["manifest_path"],
                        payload["nav2_params_file"],
                        str(payload["runner"]["vla_action_hz"]),
                        payload["manifest_sha256"],
                        payload["nav2_params_sha256"],
                        "true" if regression.get("navigation_locked") else "false",
                        payload.get("nav2_map_file", "-"),
                    ]
                )
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0

    task_ids = [f"Q{number:02d}" for number in range(1, 25)]
    for task_id in task_ids:
        load_task_config(args.config_dir, task_id)
        print(f"VALID={task_id}")
    print("VALID_TASK_CONFIGS=24")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
