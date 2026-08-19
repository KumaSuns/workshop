from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv"}
RANGE_START = 0.10
RANGE_END = 0.80


@dataclass
class VideoInfo:
    path: Path
    width: int
    height: int
    fps: float
    frame_count: int
    duration: float

    def format_duration(self) -> str:
        return format_timecode(self.duration)


@dataclass
class SamplePoint:
    index: int
    percent: float
    seconds: float
    frame: int


def format_timecode(seconds: float) -> str:
    total = max(0.0, seconds)
    minutes = int(total // 60)
    secs = total - minutes * 60
    return f"{minutes:02d}:{secs:05.2f}"


def read_video_info(path: Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"動画を開けませんでした: {path.name}")
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if fps <= 1e-3:
            fps = 30.0
        if frame_count <= 0:
            raise ValueError("フレーム数を取得できませんでした")
        duration = frame_count / fps
        return VideoInfo(
            path=path,
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            duration=duration,
        )
    finally:
        cap.release()


def sample_points(info: VideoInfo, count: int) -> list[SamplePoint]:
    if count < 1:
        raise ValueError("枚数は 1 以上にしてください")
    last_frame = max(info.frame_count - 1, 0)
    if count == 1:
        percents = np.array([0.5], dtype=float)
    else:
        percents = np.linspace(RANGE_START, RANGE_END, count)
    percents = np.clip(percents, RANGE_START, RANGE_END)
    points: list[SamplePoint] = []
    used: set[int] = set()
    for i, percent in enumerate(percents, start=1):
        frame = int(round(float(percent) * last_frame))
        frame = min(max(frame, 0), last_frame)
        while frame in used and frame < last_frame:
            frame += 1
        used.add(frame)
        seconds = frame / info.fps
        actual_percent = frame / last_frame if last_frame else 0.0
        points.append(
            SamplePoint(index=i, percent=actual_percent, seconds=seconds, frame=frame)
        )
    return points


def grab_frame(cap: cv2.VideoCapture, frame_index: int, fps: float | None = None) -> np.ndarray | None:
    target = max(int(frame_index), 0)
    if fps is not None and fps > 1e-3:
        cap.set(cv2.CAP_PROP_POS_MSEC, target / fps * 1000.0)
        ok, image = cap.read()
        if ok and image is not None:
            return image
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(target))
    ok, image = cap.read()
    if ok and image is not None:
        return image
    start = max(target - 60, 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(start))
    last = None
    current = start
    while current <= target:
        ok, image = cap.read()
        if not ok:
            break
        last = image
        if current >= target:
            return image
        current += 1
    return last


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix or ".png"
    ok, buffer = cv2.imencode(suffix, image)
    if not ok:
        raise ValueError(f"{path.name} を書き出せませんでした")
    path.write_bytes(buffer.tobytes())


def extracted_file_for(output_dir: Path, stem: str, index: int) -> Path | None:
    if not output_dir.exists():
        return None
    marker = f"_{index:03d}_"
    matches = [path for path in output_dir.glob("*.png") if marker in path.name]
    return sorted(matches)[-1] if matches else None


def extract_frames(
    info: VideoInfo,
    points: list[SamplePoint],
    output_dir: Path,
    progress=None,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(info.path))
    if not cap.isOpened():
        raise ValueError(f"動画を開けませんでした: {info.path.name}")
    saved: list[Path] = []
    stem = info.path.stem
    try:
        for i, point in enumerate(points, start=1):
            image = grab_frame(cap, point.frame, info.fps)
            if image is None:
                raise ValueError(f"{format_timecode(point.seconds)} のフレームを取得できませんでした")
            name = f"{stem}_{point.index:03d}_{format_timecode(point.seconds).replace(':', '-')}_{int(point.percent * 100):02d}pct.png"
            dest = output_dir / name
            write_image(dest, image)
            saved.append(dest)
            if progress is not None:
                progress(i, len(points), dest.name)
    finally:
        cap.release()
    return saved
