from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compile_tasks import apply_route_override, navigation_acceptance
from build_overview_runtime import REPLACEMENTS, build as build_overview_runtime
from summarize_results import main as summarize_main
from task_config import load_task_config


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


class TaskConfigTests(unittest.TestCase):
    config_dir = Path(__file__).resolve().parents[1] / "config/tasks"

    def test_all_tasks_have_valid_independent_manifests(self) -> None:
        for number in range(1, 25):
            task_id = f"Q{number:02d}"
            payload = load_task_config(self.config_dir, task_id)
            self.assertEqual(payload["task_id"], task_id)
            self.assertEqual(Path(payload["manifest_path"]).name, f"{task_id}.json")

    def test_task_specific_frequency_and_navigation_locks(self) -> None:
        self.assertEqual(
            load_task_config(self.config_dir, "Q04")["runner"]["vla_action_hz"], 2
        )
        self.assertEqual(
            load_task_config(self.config_dir, "Q05")["runner"]["vla_action_hz"], 1
        )
        self.assertTrue(
            load_task_config(self.config_dir, "Q04")["regression"][
                "navigation_locked"
            ]
        )
        self.assertTrue(
            load_task_config(self.config_dir, "Q05")["regression"][
                "navigation_locked"
            ]
        )

    def test_forward_profile_is_limited_to_previously_failing_tasks(self) -> None:
        forward_tasks = {"Q02", "Q05", "Q06", "Q07"}
        for number in range(1, 25):
            task_id = f"Q{number:02d}"
            profile = Path(load_task_config(self.config_dir, task_id)["nav2_params_file"])
            expected = (
                "nav2_forward_v1.yaml"
                if task_id in forward_tasks
                else "nav2_default_v1.yaml"
            )
            self.assertEqual(profile.name, expected)

    def test_q09_uses_hash_locked_task_map_and_route(self) -> None:
        config = load_task_config(self.config_dir, "Q09")
        self.assertEqual(Path(config["nav2_map_file"]).name, "q09.yaml")
        self.assertEqual(Path(config["nav2_map_image_file"]).name, "q09.pgm")
        self.assertEqual(Path(config["route_override_file"]).name, "route_override.json")
        project = Path(__file__).resolve().parents[1]
        official = json.loads((project / "compiled_tasks.json").read_text(encoding="utf-8"))["tasks"]["Q09"]
        modified = apply_route_override(official, config)
        self.assertEqual(modified["waypoints_xy"][-1], official["navigation_goal_xy"])
        self.assertEqual(
            modified["route_override_sha256"], config["route_override_sha256"]
        )

    def test_q05_uses_hash_locked_usd_map_and_detour(self) -> None:
        config = load_task_config(self.config_dir, "Q05")
        self.assertEqual(Path(config["nav2_map_file"]).name, "q05.yaml")
        self.assertEqual(Path(config["nav2_map_image_file"]).name, "q05.pgm")
        self.assertEqual(Path(config["route_override_file"]).name, "route_override.json")
        project = Path(__file__).resolve().parents[1]
        official = json.loads((project / "compiled_tasks.json").read_text(encoding="utf-8"))["tasks"]["Q05"]
        modified = apply_route_override(official, config)
        self.assertEqual(modified["waypoints_xy"][-1], official["navigation_goal_xy"])
        self.assertEqual(
            modified["route_override_sha256"], config["route_override_sha256"]
        )
        metadata = json.loads(
            (project / "config/tasks/Q05/q05.json").read_text(encoding="utf-8")
        )
        self.assertTrue(metadata["route_corridor_cleared"])
        self.assertEqual(metadata["corridor_radius_m"], 1.1)
        self.assertEqual(metadata["tasks"], ["Q05"])

    def test_profile_hash_blocks_silent_shared_parameter_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied_config = Path(temporary) / "config"
            shutil.copytree(self.config_dir.parent, copied_config)
            profile = copied_config / "profiles/nav2_default_v1.yaml"
            profile.write_text(
                profile.read_text(encoding="utf-8") + "# changed\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "profile hash mismatch"):
                load_task_config(copied_config / "tasks", "Q04")

    def test_result_layout_has_one_task_directory_per_run_root(self) -> None:
        project = Path(__file__).resolve().parents[1]
        single_runner = (project / "scripts/run_runner_task.sh").read_text(
            encoding="utf-8"
        )
        batch_runner = (project / "scripts/run_all_tasks.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('RESULT_DIR="$RESULT_ROOT/$TASK_ID"', single_runner)
        self.assertIn('RESULT_ROOT/$TASK_ID', batch_runner)
        self.assertNotIn('results/$TASK_ID/$RUN_ID', single_runner)

    def test_batch_log_records_task_duration_and_rolling_eta(self) -> None:
        project = Path(__file__).resolve().parents[1]
        batch_runner = (project / "scripts/run_all_tasks.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("TASK_TIMING_START", batch_runner)
        self.assertIn("TASK_TIMING_END", batch_runner)
        self.assertIn("ELAPSED_S=", batch_runner)
        self.assertIn("ETA_REMAINING_S=", batch_runner)
        self.assertIn("ETA_COMPLETION=", batch_runner)
        self.assertIn("INITIAL_TASK_ESTIMATE_SECONDS", batch_runner)
        self.assertIn("eta_completion_time", batch_runner)
        self.assertIn("trap cleanup EXIT", batch_runner)
        self.assertIn("handle_signal TERM 143", batch_runner)
        self.assertNotIn("trap cleanup EXIT INT TERM", batch_runner)

    def test_runner_wall_timeout_has_exact_container_cleanup(self) -> None:
        project = Path(__file__).resolve().parents[1]
        runner = (project / "scripts/run_runner_task.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('RUNNER_TIMEOUT_GRACE_SECONDS="${RUNNER_TIMEOUT_GRACE_SECONDS:-600}"', runner)
        self.assertIn('--kill-after="${RUNNER_TIMEOUT_KILL_AFTER_SECONDS}s"', runner)
        self.assertIn('--cidfile "$CID_FILE"', runner)
        self.assertIn('docker stop --time 30 "$RUNNER_CID"', runner)
        self.assertIn('"runner_timed_out": $RUNNER_TIMED_OUT', runner)
        self.assertIn("NAVIGATION_LOCKED TASK_MAP", runner)
        self.assertIn('cp "$TASK_MAP" "$RESULT_DIR/nav2_map.yaml"', runner)

    def test_debug_views_are_sidecars_only_and_never_enter_submission(self) -> None:
        project = Path(__file__).resolve().parents[1]
        runner = (project / "scripts/run_runner_task.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("RUNNER_OVERVIEW", runner)
        self.assertIn("NAV2_OVERVIEW_OUTPUT", runner)
        self.assertIn('cp "$OVERVIEW_SOURCE" "$RESULT_DIR/overview.mp4"', runner)
        self.assertIn("NAV2_CHASE_OUTPUT", runner)
        self.assertIn('cp "$CHASE_SOURCE" "$RESULT_DIR/chase.mp4"', runner)
        self.assertNotIn("$RESULT_DIR/submission/overview.mp4", runner)
        self.assertNotIn("$RESULT_DIR/submission/chase.mp4", runner)
        self.assertIn('RUN_LOG_ROOT="${RUN_LOG_ROOT:-$PROJECT_DIR/logs}"', runner)

        wrapper = (project / "scripts/run_all_tasks_overview.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("export RUNNER_OVERVIEW=1", wrapper)
        self.assertIn("export RUNNER_CHASE=1", wrapper)
        self.assertIn("OVERVIEW_RUNTIME_PATH=", wrapper)

        preparer = (project / "scripts/prepare_overview_runtime.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('overview_runtime/$RUNTIME_SHA', preparer)

    def test_overview_runtime_builder_requires_exact_context(self) -> None:
        synthetic_source = "\n".join(old for old, _ in REPLACEMENTS)
        digest = hashlib.sha256(synthetic_source.encode()).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "official.py"
            output = Path(temporary) / "overview.py"
            source.write_text(synthetic_source, encoding="utf-8")
            with patch(
                "build_overview_runtime.OFFICIAL_SOURCE_SHA256", digest
            ), patch("builtins.compile"):
                build_overview_runtime(source, output)
            patched = output.read_text(encoding="utf-8")
            self.assertIn("NAV2_OVERVIEW_OUTPUT", patched)
            self.assertIn("overview_camera_pose", patched)
            self.assertIn(".overview.partial.mp4", patched)
            self.assertIn("NAV2_CHASE_OUTPUT", patched)
            self.assertIn('camera_specs.append(("chase", (1280, 720)))', patched)
            self.assertIn("chase_eye = base_position - 6.0 * forward", patched)
            self.assertIn("0.0 * forward[0]", patched)
            self.assertIn("chase_camera.set_focal_length(chase_focal_length)", patched)
            self.assertIn('"focal_length_scale": 0.5', patched)
            self.assertIn(".chase.partial.mp4", patched)

    def test_single_runner_creates_new_transaction_root(self) -> None:
        source_project = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "policy"
            project.mkdir()
            shutil.copy2(source_project / "task_config.py", project)
            shutil.copytree(source_project / "config", project / "config")
            (project / "compiled_tasks.json").write_text(
                json.dumps(
                    {
                        "tasks": {
                            "Q04": {
                                "maximum_duration_s": 240,
                                "maximum_vla_actions": 400,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            fake_bin = Path(temporary) / "bin"
            fake_bin.mkdir()
            fake_docker = fake_bin / "docker"
            fake_docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            fake_docker.chmod(0o755)
            environment = os.environ.copy()
            environment["PROJECT_DIR"] = str(project)
            environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
            process = subprocess.run(
                [
                    "bash",
                    str(source_project / "scripts/run_runner_task.sh"),
                    "Q04",
                    "internal_runner_id",
                ],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(process.returncode, 0)
            roots = list(project.glob("results_*"))
            self.assertEqual(len(roots), 1)
            task_result = roots[0] / "Q04"
            self.assertTrue((task_result / "task_config.json").is_file())
            self.assertTrue((task_result / "nav2_params.yaml").is_file())
            self.assertFalse((task_result / "internal_runner_id").exists())


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
