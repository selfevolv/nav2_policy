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
            pair_dir = result_dir / "submission"
            pair_hdf5 = pair_dir / "episode.hdf5"
            pair_video = pair_dir / "episode.mp4"
            distance = nav.get("minimum_acceptance_distance_m")
            acceptance = nav.get("navigation_acceptance", {})
            fresh_status = bool(
                run.get("run_token")
                and run.get("run_token") == nav.get("run_token")
            )
            artifact_valid = bool(
                run.get("runner_status") == 0
                and run.get("video_kind") == "runner_episode"
                and run.get("submission_ready")
                and pair_hdf5.is_file()
                and pair_hdf5.stat().st_size > 0
                and pair_video.is_file()
                and pair_video.stat().st_size > 0
            )
            navigation_success = bool(
                artifact_valid
                and fresh_status
                and nav.get("navigation_reached", False)
                and isinstance(distance, (int, float))
                and isinstance(acceptance.get("distance_m"), (int, float))
                and distance <= acceptance["distance_m"]
            )
            failure_reasons: list[str] = []
            if not artifact_valid:
                failure_reasons.append("official_pair_invalid")
            if not fresh_status:
                failure_reasons.append("stale_or_missing_navigation_status")
            if not nav.get("navigation_reached", False):
                failure_reasons.append("navigation_threshold_not_reached")
            rows.append(
                {
                    "task": entry["task"],
                    "run_id": entry["run_id"],
                    "executor_status": int(entry["executor_status"]),
                    "runner_status": run.get("runner_status"),
                    "video_saved": video.is_file() and video.stat().st_size > 0,
                    "video_kind": run.get("video_kind", "missing"),
                    "video_bytes": video.stat().st_size if video.is_file() else 0,
                    "artifact_valid": artifact_valid,
                    "navigation_reached": navigation_success,
                    "navigation_success_basis": (
                        "fresh_bridge_task_specific_threshold"
                        if navigation_success
                        else "not_reached"
                    ),
                    "minimum_goal_distance_m": distance,
                    "acceptance_distance_m": acceptance.get("distance_m"),
                    "acceptance_source": acceptance.get("source"),
                    "goal_status": nav.get("goal_status", "missing"),
                    "request_count": nav.get("request_count"),
                    "maximum_vla_actions": run.get("maximum_vla_actions"),
                    "vla_action_hz": run.get("vla_action_hz"),
                    "failure_reasons": failure_reasons,
                    "result_dir": str(result_dir),
                }
            )

    successes = sum(row["navigation_reached"] for row in rows)
    videos = sum(row["video_saved"] for row in rows)
    valid_pairs = sum(row["artifact_valid"] for row in rows)
    summary = {
        "schema": "m20-nav2-batch-summary/v1",
        "result_root": str(args.batch_tsv.parent.resolve()),
        "tasks_run": len(rows),
        "videos_saved": videos,
        "valid_submission_pairs": valid_pairs,
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
        f"- 官方文件对有效：{valid_pairs}/{len(rows)}",
        f"- 导航成功：{successes}/{len(rows)}",
        f"- 达到 50% 目标：{'是' if summary['meets_50_percent_target'] else '否'}",
        "",
        "| 任务 | 导航 | 最小验收距离/阈值 m | 文件对 | Hz | Runner |",
        "| --- | --- | ---: | --- | ---: | ---: |",
    ]
    for row in rows:
        distance = row["minimum_goal_distance_m"]
        distance_text = f"{distance:.3f}" if isinstance(distance, (int, float)) else "—"
        threshold = row["acceptance_distance_m"]
        threshold_text = (
            f"{threshold:.3f}" if isinstance(threshold, (int, float)) else "—"
        )
        lines.append(
            f"| {row['task']} | {'成功' if row['navigation_reached'] else '失败'} | "
            f"{distance_text}/{threshold_text} | "
            f"{'有效' if row['artifact_valid'] else '无效'} | "
            f"{row['vla_action_hz'] or '—'} | {row['runner_status']} |"
        )
    args.output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
