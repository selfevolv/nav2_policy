#!/usr/bin/env python3
"""Build machine-readable and Markdown navigation acceptance summaries."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-tsv", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-markdown", required=True, type=Path)
    args = parser.parse_args()

    rows: list[dict] = []
    with args.batch_tsv.open(encoding="utf-8", newline="") as handle:
        for entry in csv.DictReader(handle, delimiter="\t"):
            result_dir = Path(entry["result_dir"])
            run = load_json(result_dir / "run_summary.json")
            nav = load_json(result_dir / "navigation_status.json")
            video = result_dir / "episode.mp4"
            distance = nav.get("minimum_goal_distance_m")
            explicit_success = bool(nav.get("navigation_reached", False))
            runner_route_success = (
                run.get("runner_status") == 0
                and run.get("video_kind") == "runner_episode"
                and isinstance(distance, (int, float))
                and distance <= 0.5
                and nav.get("request_count", 0) < run.get("maximum_vla_actions", 0)
            )
            rows.append(
                {
                    "task": entry["task"],
                    "run_id": entry["run_id"],
                    "executor_status": int(entry["executor_status"]),
                    "runner_status": run.get("runner_status"),
                    "video_saved": video.is_file() and video.stat().st_size > 0,
                    "video_kind": run.get("video_kind", "missing"),
                    "video_bytes": video.stat().st_size if video.is_file() else 0,
                    "navigation_reached": explicit_success or runner_route_success,
                    "navigation_success_basis": (
                        "bridge_reached"
                        if explicit_success
                        else "runner_completed_within_0.5m"
                        if runner_route_success
                        else "not_reached"
                    ),
                    "minimum_goal_distance_m": distance,
                    "goal_status": nav.get("goal_status", "missing"),
                    "result_dir": str(result_dir),
                }
            )

    successes = sum(row["navigation_reached"] for row in rows)
    videos = sum(row["video_saved"] for row in rows)
    summary = {
        "schema": "m20-nav2-batch-summary/v1",
        "tasks_run": len(rows),
        "videos_saved": videos,
        "navigation_successes": successes,
        "navigation_success_rate": successes / len(rows) if rows else 0.0,
        "meets_50_percent_target": len(rows) > 0 and successes * 2 >= len(rows),
        "tasks": rows,
    }
    args.output_json.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Nav2 导航批次报告",
        "",
        f"- 运行任务：{len(rows)}",
        f"- 视频完整：{videos}/{len(rows)}",
        f"- 导航成功：{successes}/{len(rows)}",
        f"- 达到 50% 目标：{'是' if summary['meets_50_percent_target'] else '否'}",
        "",
        "| 任务 | 导航 | 最小终点距离/m | 视频 | Runner |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for row in rows:
        distance = row["minimum_goal_distance_m"]
        distance_text = f"{distance:.3f}" if isinstance(distance, (int, float)) else "—"
        lines.append(
            f"| {row['task']} | {'成功' if row['navigation_reached'] else '失败'} | "
            f"{distance_text} | {row['video_kind']} | {row['runner_status']} |"
        )
    args.output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
