#!/usr/bin/env python3
"""Generate simple Nav2 occupancy maps from Isaac Sim USD collision geometry.

The script must be run with Isaac Sim's python.sh so that pxr and asset resolvers
match the simulator. Static collision bounds are projected into XY. Shared maps
can clear a narrow route corridor; task maps may disable that clearing so Nav2
continues to see furniture and other USD collision geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np
# Isaac Sim 5.1 requires a SimulationApp before importing bundled pxr modules.
from isaacsim import SimulationApp

SIMULATION_APP = SimulationApp({"headless": True, "multi_gpu": False})
from pxr import Usd, UsdGeom, UsdPhysics


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def disk_cells(radius_cells: int) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    squared = radius_cells * radius_cells
    for dy in range(-radius_cells, radius_cells + 1):
        for dx in range(-radius_cells, radius_cells + 1):
            if dx * dx + dy * dy <= squared:
                result.append((dx, dy))
    return result


def route_samples(points: list[list[float]], spacing: float) -> Iterable[tuple[float, float]]:
    for start, end in zip(points, points[1:]):
        distance = math.hypot(end[0] - start[0], end[1] - start[1])
        count = max(1, int(math.ceil(distance / spacing)))
        for step in range(count + 1):
            ratio = step / count
            yield (
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            )


def collision_bounds(stage: Usd.Stage, minimum_z: float, maximum_z: float):
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render]
    )
    for prim in stage.Traverse():
        if not prim.IsActive() or not prim.IsA(UsdGeom.Boundable):
            continue
        collision_attr = prim.GetAttribute("physics:collisionEnabled")
        collision_enabled = bool(collision_attr and collision_attr.Get())
        if not collision_enabled and not prim.HasAPI(UsdPhysics.CollisionAPI):
            continue
        path_text = str(prim.GetPath()).lower()
        if any(token in path_text for token in ("m20piper", "m20_piper", "/robot")):
            continue
        world_range = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        lower = world_range.GetMin()
        upper = world_range.GetMax()
        values = [float(lower[i]) for i in range(3)] + [float(upper[i]) for i in range(3)]
        if not np.isfinite(values).all():
            continue
        if values[5] < minimum_z or values[2] > maximum_z:
            continue
        if values[3] - values[0] < 0.015 or values[4] - values[1] < 0.015:
            continue
        yield str(prim.GetPath()), values


def write_pgm(path: Path, occupancy: np.ndarray) -> None:
    # map_server: black=occupied, white=free. Flip so PGM top row is maximum Y.
    pixels = np.where(occupancy, 0, 254).astype(np.uint8)
    pixels = np.flipud(pixels)
    with path.open("wb") as stream:
        stream.write(f"P5\n{pixels.shape[1]} {pixels.shape[0]}\n255\n".encode("ascii"))
        stream.write(pixels.tobytes())


def generate_scene_map(
    scene: str,
    tasks: list[dict],
    output_dir: Path,
    resolution: float,
    margin: float,
    corridor_radius: float,
    endpoint_clear_radius: float = 0.0,
    output_name: str | None = None,
) -> None:
    source = Path(tasks[0]["scene_usd"])
    if any(Path(task["scene_usd"]) != source for task in tasks):
        raise ValueError(f"{scene}: tasks reference different USD files")
    points: list[list[float]] = []
    routes: list[list[list[float]]] = []
    for task in tasks:
        spawn = task["spawn_xyz"][:2]
        route = [spawn] + task["waypoints_xy"]
        routes.append(route)
        points.extend(route)
    minimum_x = math.floor((min(p[0] for p in points) - margin) / resolution) * resolution
    minimum_y = math.floor((min(p[1] for p in points) - margin) / resolution) * resolution
    maximum_x = math.ceil((max(p[0] for p in points) + margin) / resolution) * resolution
    maximum_y = math.ceil((max(p[1] for p in points) + margin) / resolution) * resolution
    width = int(round((maximum_x - minimum_x) / resolution))
    height = int(round((maximum_y - minimum_y) / resolution))
    occupancy = np.zeros((height, width), dtype=bool)

    print(f"OPEN_STAGE={source}", flush=True)
    stage = Usd.Stage.Open(str(source))
    if stage is None:
        raise RuntimeError(f"failed to open USD stage: {source}")

    projected = 0
    projected_paths: list[str] = []
    for prim_path, bounds in collision_bounds(stage, minimum_z=0.18, maximum_z=1.35):
        x0, y0, _, x1, y1, _ = bounds
        if x1 < minimum_x or x0 > maximum_x or y1 < minimum_y or y0 > maximum_y:
            continue
        col0 = max(0, int(math.floor((x0 - minimum_x) / resolution)))
        col1 = min(width - 1, int(math.ceil((x1 - minimum_x) / resolution)))
        row0 = max(0, int(math.floor((y0 - minimum_y) / resolution)))
        row1 = min(height - 1, int(math.ceil((y1 - minimum_y) / resolution)))
        occupancy[row0 : row1 + 1, col0 : col1 + 1] = True
        projected += 1
        if len(projected_paths) < 200:
            projected_paths.append(prim_path)

    if corridor_radius > 0.0:
        radius_cells = max(1, int(math.ceil(corridor_radius / resolution)))
        clearing_disk = disk_cells(radius_cells)
        for route in routes:
            for x, y in route_samples(route, spacing=resolution * 0.5):
                center_col = int(round((x - minimum_x) / resolution))
                center_row = int(round((y - minimum_y) / resolution))
                for dx, dy in clearing_disk:
                    col = center_col + dx
                    row = center_row + dy
                    if 0 <= col < width and 0 <= row < height:
                        occupancy[row, col] = False

    if endpoint_clear_radius > 0.0:
        endpoint_radius_cells = max(
            1, int(math.ceil(endpoint_clear_radius / resolution))
        )
        endpoint_disk = disk_cells(endpoint_radius_cells)
        for route in routes:
            for x, y in (route[0], route[-1]):
                center_col = int(round((x - minimum_x) / resolution))
                center_row = int(round((y - minimum_y) / resolution))
                for dx, dy in endpoint_disk:
                    col = center_col + dx
                    row = center_row + dy
                    if 0 <= col < width and 0 <= row < height:
                        occupancy[row, col] = False

    occupancy[0, :] = True
    occupancy[-1, :] = True
    occupancy[:, 0] = True
    occupancy[:, -1] = True
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = output_name or scene
    pgm_path = output_dir / f"{artifact_name}.pgm"
    yaml_path = output_dir / f"{artifact_name}.yaml"
    metadata_path = output_dir / f"{artifact_name}.json"
    write_pgm(pgm_path, occupancy)
    yaml_path.write_text(
        "\n".join(
            [
                f"image: {pgm_path.name}",
                "mode: trinary",
                f"resolution: {resolution}",
                f"origin: [{minimum_x}, {minimum_y}, 0.0]",
                "negate: 0",
                "occupied_thresh: 0.65",
                "free_thresh: 0.25",
                "",
            ]
        ),
        encoding="utf-8",
    )
    metadata = {
        "schema": "m20-nav2-usd-map/v1",
        "scene": scene,
        "source_usd": str(source),
        "source_usd_sha256": sha256_file(source),
        "resolution": resolution,
        "origin": [minimum_x, minimum_y, 0.0],
        "width": width,
        "height": height,
        "projected_collision_prims": projected,
        "occupied_cell_ratio": float(occupancy.mean()),
        "corridor_radius_m": corridor_radius,
        "route_corridor_cleared": corridor_radius > 0.0,
        "endpoint_clear_radius_m": endpoint_clear_radius,
        "tasks": [task["question_id"] for task in tasks],
        "sample_collision_prims": projected_paths,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"MAP={artifact_name}|scene={scene}|size={width}x{height}|collisions={projected}|"
        f"occupied={occupancy.mean():.4f}|yaml={yaml_path}",
        flush=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiled-tasks", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--resolution", type=float, default=0.10)
    parser.add_argument("--margin", type=float, default=3.0)
    parser.add_argument("--corridor-radius", type=float, default=0.65)
    parser.add_argument("--endpoint-clear-radius", type=float, default=0.0)
    parser.add_argument(
        "--task",
        help="generate only one Qxx task map instead of all shared scene maps",
    )
    parser.add_argument(
        "--output-name",
        help="artifact basename for --task (defaults to the lower-case task id)",
    )
    args = parser.parse_args()
    payload = json.loads(args.compiled_tasks.read_text(encoding="utf-8"))
    if args.task:
        task_id = args.task.upper()
        try:
            task = payload["tasks"][task_id]
        except KeyError as error:
            raise ValueError(f"unknown task: {task_id}") from error
        generate_scene_map(
            task["scene"],
            [task],
            args.output_dir,
            args.resolution,
            args.margin,
            args.corridor_radius,
            args.endpoint_clear_radius,
            args.output_name or task_id.lower(),
        )
        return 0
    grouped: dict[str, list[dict]] = {}
    for task in payload["tasks"].values():
        grouped.setdefault(task["scene"], []).append(task)
    if set(grouped) != {"warehouse", "kitchen", "market"}:
        raise RuntimeError(f"expected three scenes, found {sorted(grouped)}")
    for scene, tasks in sorted(grouped.items()):
        generate_scene_map(
            scene,
            tasks,
            args.output_dir,
            args.resolution,
            args.margin,
            args.corridor_radius,
            args.endpoint_clear_radius,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        SIMULATION_APP.close()
