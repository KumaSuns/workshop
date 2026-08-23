from __future__ import annotations

from pathlib import Path

import cv2
import torch
from PIL import Image
from torch import nn
from torchvision import transforms
from torchvision.models import ResNet18_Weights, resnet18

from app.extractor import SamplePoint, VideoInfo, format_timecode, write_image
from app.paths import kind_dir
from app.scene_labels import OTHER_KEY, SceneLabels, scene_model_path, scene_model_ready

SCENE_INPUT = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)
KIND_THRESHOLD = 0.18
RAREDY_KEY = "raredy"
GO_KEY = "go"
RAREDY_CUE_THRESHOLD = 0.35
GO_AFTER_RAREDY_SEC = 2.5
GO_AFTER_RAREDY_THRESHOLD = 0.22
REJECT_HASH_SIZE = 8
REJECT_HASH_LIMIT = 12


class SceneNet(nn.Module):
    def __init__(self, pretrained: bool = False, num_classes: int = 3) -> None:
        super().__init__()
        weights = ResNet18_Weights.DEFAULT if pretrained else None
        backbone = resnet18(weights=weights)
        self.features = nn.Sequential(*list(backbone.children())[:-1])
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(512, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(0.25),
            nn.Linear(128, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(x))

    def freeze_backbone(self, train_last_block: bool = True) -> None:
        for parameter in self.features.parameters():
            parameter.requires_grad = False
        if train_last_block:
            last_block = self.features[-2]
            for parameter in last_block.parameters():
                parameter.requires_grad = True


def scene_ahash(image: Image.Image, size: int = REJECT_HASH_SIZE) -> int:
    small = image.convert("L").resize((size, size), Image.Resampling.BILINEAR)
    pixels = list(small.getdata())
    avg = sum(pixels) / max(len(pixels), 1)
    bits = 0
    for value in pixels:
        bits = (bits << 1) | int(value >= avg)
    return bits


def scene_ahash_path(path: Path) -> int | None:
    try:
        with Image.open(path) as image:
            return scene_ahash(image)
    except Exception:
        return None


def hashes_too_close(left: int, right: int, limit: int = REJECT_HASH_LIMIT) -> bool:
    return (left ^ right).bit_count() <= limit


def load_scene_checkpoint(device: torch.device) -> tuple[SceneNet, tuple[str, ...]]:
    checkpoint = torch.load(scene_model_path(), map_location=device, weights_only=False)
    classes = tuple(checkpoint.get("classes") or (OTHER_KEY, "go", "timeup"))
    model = SceneNet(num_classes=len(classes))
    state = (
        checkpoint["state_dict"]
        if isinstance(checkpoint, dict) and "state_dict" in checkpoint
        else checkpoint
    )
    model.load_state_dict(state)
    model.to(device)
    model.eval()
    return model, classes


def _group_hits(hits: list[tuple[str, int, float, float]], gap_frames: int) -> list[tuple[str, int, float, float]]:
    if not hits:
        return []
    by_kind: dict[str, list[tuple[str, int, float, float]]] = {}
    for item in hits:
        by_kind.setdefault(item[0], []).append(item)
    picked: list[tuple[str, int, float, float]] = []
    for rows in by_kind.values():
        rows.sort(key=lambda row: row[1])
        groups: list[list[tuple[str, int, float, float]]] = [[rows[0]]]
        for item in rows[1:]:
            if item[1] - groups[-1][-1][1] <= gap_frames:
                groups[-1].append(item)
            else:
                groups.append([item])
        picked.extend(max(group, key=lambda row: row[3]) for group in groups)
    picked.sort(key=lambda row: row[1])
    return picked


def _class_score(probs: torch.Tensor, classes: tuple[str, ...], key: str) -> float:
    try:
        return float(probs[classes.index(key)].item())
    except ValueError:
        return 0.0


def _wanted(kind: str, want_kinds: set[str] | None) -> bool:
    return want_kinds is None or kind in want_kinds


def _best_wanted(probs: torch.Tensor, classes: tuple[str, ...], want_kinds: set[str] | None) -> tuple[str, float]:
    best_kind = OTHER_KEY
    best_score = -1.0
    for index, key in enumerate(classes):
        if key == OTHER_KEY:
            continue
        if not _wanted(key, want_kinds):
            continue
        score = float(probs[index].item())
        if score > best_score:
            best_kind = key
            best_score = score
    return best_kind, best_score


def find_scene_points(
    info: VideoInfo,
    progress=None,
    want_kinds: set[str] | None = None,
) -> list[SamplePoint]:
    if not scene_model_ready():
        raise ValueError("画面のモデルがありません。画像を教えて学習してください。")
    if want_kinds is None:
        labels = SceneLabels()
        want_kinds = set(labels.extract_keys()) | set(labels.hidden_keys())
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, classes = load_scene_checkpoint(device)
    transform = transforms.Compose(
        [
            transforms.Resize((SCENE_INPUT, SCENE_INPUT)),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )
    coarse_step = max(1, int(round(info.fps * 0.1)))
    window_frames = max(1, int(round(info.fps * GO_AFTER_RAREDY_SEC)))
    cap = cv2.VideoCapture(str(info.path))
    if not cap.isOpened():
        raise ValueError(f"動画を開けませんでした: {info.path.name}")
    hits: list[tuple[str, int, float, float]] = []
    frame_index = 0
    total = max(info.frame_count, 1)
    last_raredy_frame = -1
    hunt_until = -1
    try:
        while True:
            hunting = frame_index <= hunt_until
            step_now = 1 if hunting else coarse_step
            if hunting or frame_index % step_now == 0:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                tensor = transform(image).unsqueeze(0).to(device)
                with torch.no_grad():
                    probs = torch.softmax(model(tensor), dim=1)[0]
                raredy_score = _class_score(probs, classes, RAREDY_KEY)
                go_score = _class_score(probs, classes, GO_KEY)
                if raredy_score >= RAREDY_CUE_THRESHOLD and raredy_score >= go_score:
                    last_raredy_frame = frame_index
                    hunt_until = frame_index + window_frames
                after_raredy = last_raredy_frame >= 0 and last_raredy_frame < frame_index <= hunt_until
                if (
                    after_raredy
                    and _wanted(GO_KEY, want_kinds)
                    and go_score >= GO_AFTER_RAREDY_THRESHOLD
                    and go_score >= raredy_score
                ):
                    hits.append((GO_KEY, frame_index, frame_index / info.fps, go_score))
                for key in classes:
                    if key == OTHER_KEY or not _wanted(key, want_kinds):
                        continue
                    score = _class_score(probs, classes, key)
                    if score < KIND_THRESHOLD:
                        continue
                    hits.append((key, frame_index, frame_index / info.fps, score))
                kind, score = _best_wanted(probs, classes, want_kinds)
                if progress is not None:
                    progress(frame_index + 1, total, f"{kind} {score:.2f}")
            elif not cap.grab():
                break
            frame_index += 1
    finally:
        cap.release()
        if device.type == "cuda":
            torch.cuda.empty_cache()
    last_frame = max(info.frame_count - 1, 0)
    gap_frames = max(int(round(info.fps * 2.5)), coarse_step * 3)
    points: list[SamplePoint] = []
    for i, (kind, frame, seconds, score) in enumerate(_group_hits(hits, gap_frames), start=1):
        points.append(
            SamplePoint(
                index=i,
                percent=(frame / last_frame) if last_frame else 0.0,
                seconds=seconds,
                frame=frame,
                kind=kind,
                score=score,
            )
        )
    return points


def extract_scene_frames(
    info: VideoInfo,
    points: list[SamplePoint],
    output_dir: Path,
    progress=None,
) -> list[Path]:
    from app.extractor import grab_frame

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
            stamp = format_timecode(point.seconds).replace(":", "-")
            dest = kind_dir(output_dir, point.kind) / f"{stem}_{point.index:03d}_{stamp}.png"
            write_image(dest, image)
            saved.append(dest)
            if progress is not None:
                progress(i, len(points), dest.name)
    finally:
        cap.release()
    return saved
