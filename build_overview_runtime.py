#!/usr/bin/env python3
"""Build a Runner runtime copy with independent overview and chase videos."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


OFFICIAL_SOURCE_SHA256 = (
    "6f1e3327c378e9c69785fbbf35147ee1012a382b31d4e13fe49f8c82913006b3"
)


REPLACEMENTS = (
    (
        """args.output = args.output.expanduser().resolve()
args.output.mkdir(parents=True, exist_ok=True)
args.portable_root = args.portable_root.expanduser().resolve()
""",
        """args.output = args.output.expanduser().resolve()
args.output.mkdir(parents=True, exist_ok=True)
# Diagnostic-only sidecar output.  The official Runner publish directory is
# intentionally untouched, so episode.mp4 and submission.hdf5 remain original.
OVERVIEW_OUTPUT_TEXT = os.environ.get("NAV2_OVERVIEW_OUTPUT", "").strip()
OVERVIEW_OUTPUT = (
    Path(OVERVIEW_OUTPUT_TEXT).expanduser().resolve()
    if OVERVIEW_OUTPUT_TEXT
    else None
)
if OVERVIEW_OUTPUT is not None:
    if OVERVIEW_OUTPUT.name != "overview.mp4":
        raise ValueError("NAV2_OVERVIEW_OUTPUT must end with overview.mp4")
    if OVERVIEW_OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite overview video {OVERVIEW_OUTPUT}")
    OVERVIEW_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
CHASE_OUTPUT_TEXT = os.environ.get("NAV2_CHASE_OUTPUT", "").strip()
CHASE_OUTPUT = (
    Path(CHASE_OUTPUT_TEXT).expanduser().resolve()
    if CHASE_OUTPUT_TEXT
    else None
)
if CHASE_OUTPUT is not None:
    if CHASE_OUTPUT.name != "chase.mp4":
        raise ValueError("NAV2_CHASE_OUTPUT must end with chase.mp4")
    if CHASE_OUTPUT.exists():
        raise FileExistsError(f"refusing to overwrite chase video {CHASE_OUTPUT}")
    CHASE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
args.portable_root = args.portable_root.expanduser().resolve()
""",
    ),
    (
        """def look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    forward = target - eye
    forward /= np.linalg.norm(forward)
    up_hint = np.asarray([0.0, 0.0, 1.0])
    right = np.cross(up_hint, forward)
    if np.linalg.norm(right) < 1.0e-8:
        right = np.asarray([0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    camera_up = np.cross(forward, right)
    camera_up /= np.linalg.norm(camera_up)
    # This is Isaac Sim's verified camera convention: local X is the optical axis.
    return matrix_to_quaternion(np.column_stack((forward, right, camera_up)))


class BaseVisualFollower:
""",
        """def look_at(eye: np.ndarray, target: np.ndarray) -> np.ndarray:
    forward = target - eye
    forward /= np.linalg.norm(forward)
    up_hint = np.asarray([0.0, 0.0, 1.0])
    right = np.cross(up_hint, forward)
    if np.linalg.norm(right) < 1.0e-8:
        right = np.asarray([0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    camera_up = np.cross(forward, right)
    camera_up /= np.linalg.norm(camera_up)
    # This is Isaac Sim's verified camera convention: local X is the optical axis.
    return matrix_to_quaternion(np.column_stack((forward, right, camera_up)))


def overview_camera_pose(stage) -> tuple[np.ndarray, np.ndarray, dict]:
    \"\"\"Place a vertical camera above the render bounds authored by the scene USD.\"\"\"
    default_prim = stage.GetDefaultPrim()
    if not default_prim or not default_prim.IsValid():
        raise RuntimeError("overview camera requires a valid scene default Prim")
    cache = UsdGeom.BBoxCache(
        Usd.TimeCode.Default(),
        [UsdGeom.Tokens.default_, UsdGeom.Tokens.render],
        useExtentsHint=True,
    )
    aligned = cache.ComputeWorldBound(default_prim).ComputeAlignedRange()
    minimum = np.asarray(aligned.GetMin(), dtype=np.float64)
    maximum = np.asarray(aligned.GetMax(), dtype=np.float64)
    if not np.isfinite(minimum).all() or not np.isfinite(maximum).all():
        raise RuntimeError("scene USD produced non-finite overview bounds")
    span = maximum - minimum
    if np.any(span[:2] <= 0.0):
        raise RuntimeError(f"scene USD produced invalid overview bounds: {span}")
    center = 0.5 * (minimum + maximum)
    # Stay just below the authored roof and use an orthographic projection.  A
    # camera above the USD bounds sees only the opaque warehouse roof.
    roof_clearance = max(0.75, 0.08 * float(span[2]))
    camera_z = float(maximum[2] - roof_clearance)
    if camera_z <= float(minimum[2] + 1.0):
        raise RuntimeError("scene USD has no usable interior height for overview camera")
    horizontal_aperture = 1.08 * float(max(span[0], span[1] * (16.0 / 9.0)))
    target = np.asarray([center[0], center[1], minimum[2]], dtype=np.float64)
    eye = np.asarray([center[0], center[1], camera_z], dtype=np.float64)
    return eye, target, {
        "scene_min_xyz": minimum.tolist(),
        "scene_max_xyz": maximum.tolist(),
        "eye_xyz": eye.tolist(),
        "target_xyz": target.tolist(),
        "projection": "orthographic",
        "horizontal_aperture_m": horizontal_aperture,
    }


class BaseVisualFollower:
""",
    ),
    (
        """        if args.record_video:
            follow_resolution = (960, 540) if args.four_view_video else (1280, 720)
            camera_specs.append(("follow", follow_resolution))
        for name, resolution in camera_specs:
""",
        """        if args.record_video:
            follow_resolution = (960, 540) if args.four_view_video else (1280, 720)
            camera_specs.append(("follow", follow_resolution))
            if OVERVIEW_OUTPUT is not None:
                camera_specs.append(("overview", (1280, 720)))
            if CHASE_OUTPUT is not None:
                camera_specs.append(("chase", (1280, 720)))
        for name, resolution in camera_specs:
""",
    ),
    (
        """        self.cameras = cameras
        self.articulation = articulation
""",
        """        self.cameras = cameras
        self.overview_camera_index = None
        self.overview_camera_eye = None
        self.overview_camera_target = None
        if OVERVIEW_OUTPUT is not None:
            self.overview_camera_index = 4
            stage = omni.usd.get_context().get_stage()
            (
                self.overview_camera_eye,
                self.overview_camera_target,
                overview_camera_report,
            ) = overview_camera_pose(stage)
            print(
                "NAV2_OVERVIEW_CAMERA=" + json.dumps(overview_camera_report, sort_keys=True),
                flush=True,
            )
            overview_prim = stage.GetPrimAtPath("/M20PiperVLA/Sensors/overview_camera")
            overview_schema = UsdGeom.Camera(overview_prim)
            if not overview_schema or not overview_schema.GetPrim().IsValid():
                raise RuntimeError("overview camera USD Prim is invalid")
            overview_schema.GetProjectionAttr().Set(UsdGeom.Tokens.orthographic)
            self.cameras[self.overview_camera_index].set_horizontal_aperture(
                float(overview_camera_report["horizontal_aperture_m"])
            )
            self.cameras[self.overview_camera_index].set_clipping_range(
                near_distance=0.05,
                far_distance=max(
                    100.0,
                    float(self.overview_camera_eye[2] - self.overview_camera_target[2] + 10.0),
                ),
            )
        self.chase_camera_index = None
        if CHASE_OUTPUT is not None:
            self.chase_camera_index = 4 + int(OVERVIEW_OUTPUT is not None)
            chase_camera = self.cameras[self.chase_camera_index]
            chase_original_focal_length = float(chase_camera.get_focal_length())
            chase_horizontal_aperture = float(chase_camera.get_horizontal_aperture())
            chase_focal_length = 0.5 * chase_original_focal_length
            chase_camera.set_focal_length(chase_focal_length)
            chase_horizontal_fov_degrees = math.degrees(
                2.0 * math.atan(
                    chase_horizontal_aperture / (2.0 * chase_focal_length)
                )
            )
            print(
                "NAV2_CHASE_CAMERA=" + json.dumps(
                    {
                        "back_distance_m": 6.0,
                        "height_m": 1.2,
                        "target_longitudinal_offset_m": 0.0,
                        "target_height_m": 0.0,
                        "projection": "perspective",
                        "original_focal_length": chase_original_focal_length,
                        "focal_length": chase_focal_length,
                        "focal_length_scale": 0.5,
                        "horizontal_aperture": chase_horizontal_aperture,
                        "horizontal_fov_degrees": chase_horizontal_fov_degrees,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        self.articulation = articulation
""",
    ),
    (
        """        self.video_frame_count = 0
        self.video_frames = args.output / ".video_frames"
        self._direct_command_override: np.ndarray | None = None
""",
        """        self.video_frame_count = 0
        self.video_frames = args.output / ".video_frames"
        self.overview_frames = args.output / ".overview_frames"
        self.chase_frames = args.output / ".chase_frames"
        self._direct_command_override: np.ndarray | None = None
""",
    ),
    (
        """        if args.record_video:
            if self.video_frames.exists():
                raise FileExistsError(f"refusing to reuse video frame directory {self.video_frames}")
            self.video_frames.mkdir(parents=True)

    def link_transform(self, body_index: int) -> tuple[np.ndarray, np.ndarray]:
""",
        """        if args.record_video:
            if self.video_frames.exists():
                raise FileExistsError(f"refusing to reuse video frame directory {self.video_frames}")
            self.video_frames.mkdir(parents=True)
            if OVERVIEW_OUTPUT is not None:
                if self.overview_frames.exists():
                    raise FileExistsError(
                        f"refusing to reuse overview frame directory {self.overview_frames}"
                    )
                self.overview_frames.mkdir(parents=True)
            if CHASE_OUTPUT is not None:
                if self.chase_frames.exists():
                    raise FileExistsError(
                        f"refusing to reuse chase frame directory {self.chase_frames}"
                    )
                self.chase_frames.mkdir(parents=True)

    def link_transform(self, body_index: int) -> tuple[np.ndarray, np.ndarray]:
""",
    ),
    (
        """            self.cameras[3].set_world_pose(
                position=recording_eye,
                orientation=look_at(recording_eye, recording_target),
            )

    @staticmethod
""",
        """            self.cameras[3].set_world_pose(
                position=recording_eye,
                orientation=look_at(recording_eye, recording_target),
            )
            if OVERVIEW_OUTPUT is not None:
                self.cameras[self.overview_camera_index].set_world_pose(
                    position=self.overview_camera_eye,
                    orientation=look_at(
                        self.overview_camera_eye,
                        self.overview_camera_target,
                    ),
                )
            if CHASE_OUTPUT is not None:
                # A simple third-person racing-game camera: retain the robot's
                # rear-follow yaw while increasing distance and visible road.
                chase_eye = base_position - 6.0 * forward
                chase_eye[2] += 1.2
                chase_target = base_position + np.asarray(
                    [0.0 * forward[0], 0.0 * forward[1], 0.0]
                )
                self.cameras[self.chase_camera_index].set_world_pose(
                    position=chase_eye,
                    orientation=look_at(chase_eye, chase_target),
                )

    @staticmethod
""",
    ),
    (
        """            frame.save(
                self.video_frames / f"frame_{self.video_frame_count:06d}.jpg",
                quality=90,
            )
            self.video_frame_count += 1

    def apply_kinematic_targets(
""",
        """            frame.save(
                self.video_frames / f"frame_{self.video_frame_count:06d}.jpg",
                quality=90,
            )
            if OVERVIEW_OUTPUT is not None:
                overview_frame = Image.fromarray(
                    self.recording_rgb(self.cameras[self.overview_camera_index])
                )
                overview_frame.save(
                    self.overview_frames / f"frame_{self.video_frame_count:06d}.jpg",
                    quality=90,
                )
            if CHASE_OUTPUT is not None:
                chase_frame = Image.fromarray(
                    self.recording_rgb(self.cameras[self.chase_camera_index])
                )
                chase_frame.save(
                    self.chase_frames / f"frame_{self.video_frame_count:06d}.jpg",
                    quality=90,
                )
            self.video_frame_count += 1

    def apply_kinematic_targets(
""",
    ),
    (
        """        subprocess.run(command, check=True, timeout=300)
        report = {
""",
        """        subprocess.run(command, check=True, timeout=300)
        if OVERVIEW_OUTPUT is not None:
            temporary_overview = OVERVIEW_OUTPUT.with_name(".overview.partial.mp4")
            if temporary_overview.exists():
                raise FileExistsError(
                    f"refusing to overwrite partial overview video {temporary_overview}"
                )
            overview_command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(args.video_fps),
                "-i",
                str(self.overview_frames / "frame_%06d.jpg"),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(temporary_overview),
            ]
            subprocess.run(overview_command, check=True, timeout=300)
            temporary_overview.replace(OVERVIEW_OUTPUT)
            shutil.rmtree(self.overview_frames)
        if CHASE_OUTPUT is not None:
            temporary_chase = CHASE_OUTPUT.with_name(".chase.partial.mp4")
            if temporary_chase.exists():
                raise FileExistsError(
                    f"refusing to overwrite partial chase video {temporary_chase}"
                )
            chase_command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(args.video_fps),
                "-i",
                str(self.chase_frames / "frame_%06d.jpg"),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(temporary_chase),
            ]
            subprocess.run(chase_command, check=True, timeout=300)
            temporary_chase.replace(CHASE_OUTPUT)
            shutil.rmtree(self.chase_frames)
        report = {
""",
    ),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(source: Path, output: Path) -> None:
    if sha256(source) != OFFICIAL_SOURCE_SHA256:
        raise ValueError(
            "official runtime SHA256 mismatch; refusing to patch an unknown Runner version"
        )
    text = source.read_text(encoding="utf-8")
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            raise ValueError(f"overview runtime patch context count is {count}, expected 1")
        text = text.replace(old, new, 1)
    compile(text, str(output), "exec")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.source.resolve(strict=True), args.output.expanduser().resolve())
    print(f"OVERVIEW_RUNTIME={args.output.expanduser().resolve()}")
    print(f"OVERVIEW_RUNTIME_SHA256={sha256(args.output.expanduser().resolve())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
