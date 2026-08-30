from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compile_tasks import navigation_acceptance, recommended_vla_action_hz
from summarize_results import main as summarize_main


class CompileTaskTests(unittest.TestCase):
    def test_navigation_only_uses_public_success_radius(self) -> None:
        task = {
            "execution_mode": "navigation_only",
            "termination": {
                "success": {
                    "conditions": [
                        {
                            "id": "arrived",
                            "evaluator": "robot_near_target",
                            "stable_steps": 10,
                            "params": {
                                "target_xyz": [1.0, 2.0, 0.58],
                                "axes": "xy",
                                "distance_m": 0.6,
                            },
                        }
                    ]
                }
            },
        }
        result = navigation_acceptance(
            task,
            {"controller": {"arrival_tolerance_m": 0.25}},
            [[0.0, 0.0], [1.0, 2.0]],
        )
        self.assertEqual(result["source"], "task_success_condition")
        self.assertEqual(result["distance_m"], 0.6)

    def test_manipulation_task_uses_route_gate(self) -> None:
        result = navigation_acceptance(
            {"execution_mode": "navigation_and_manipulation"},
            {"controller": {"arrival_tolerance_m": 0.2}},
            [[0.0, 0.0], [3.0, 4.0]],
        )
        self.assertEqual(result["source"], "route_controller")
        self.assertEqual(result["target_xyz"], [3.0, 4.0])
        self.assertEqual(result["distance_m"], 0.2)

    def test_action_frequency_table(self) -> None:
        self.assertEqual(recommended_vla_action_hz("Q04"), 2)
        self.assertEqual(recommended_vla_action_hz("Q05"), 1)
        self.assertEqual(recommended_vla_action_hz("Q14"), 5)


class SummaryTests(unittest.TestCase):
    def test_requires_fresh_status_and_official_pair(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = root / "result"
            pair = result / "submission"
            pair.mkdir(parents=True)
            (result / "episode.mp4").write_bytes(b"video")
            (pair / "episode.mp4").write_bytes(b"video")
            (pair / "episode.hdf5").write_bytes(b"hdf5")
            (result / "run_summary.json").write_text(
                json.dumps(
                    {
                        "run_token": "token-1",
                        "runner_status": 0,
                        "video_kind": "runner_episode",
                        "submission_ready": 1,
                        "vla_action_hz": 2,
                        "maximum_vla_actions": 400,
                    }
                ),
                encoding="utf-8",
            )
            (result / "navigation_status.json").write_text(
                json.dumps(
                    {
                        "run_token": "token-1",
                        "navigation_reached": True,
                        "minimum_acceptance_distance_m": 0.3,
                        "navigation_acceptance": {
                            "distance_m": 0.6,
                            "source": "task_success_condition",
                        },
                    }
                ),
                encoding="utf-8",
            )
            batch = root / "runs.tsv"
            with batch.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle, delimiter="\t")
                writer.writerow(["task", "run_id", "executor_status", "result_dir"])
                writer.writerow(["Q04", "run", "0", str(result)])
            output_json = root / "summary.json"
            output_markdown = root / "summary.md"
            argv = [
                "summarize_results.py",
                "--batch-tsv",
                str(batch),
                "--output-json",
                str(output_json),
                "--output-markdown",
                str(output_markdown),
            ]
            with patch.object(sys, "argv", argv):
                self.assertEqual(summarize_main(), 0)
            summary = json.loads(output_json.read_text(encoding="utf-8"))
            self.assertEqual(summary["navigation_successes"], 1)
            self.assertEqual(summary["valid_submission_pairs"], 1)


if __name__ == "__main__":
    unittest.main()
