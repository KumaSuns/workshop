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
SCENE_THRESHOLD = 0.55
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


def other_scene_hashes() -> list[int]:
    hashes: list[int] = []
    for item in SceneLabels().items():
        if item.get("kind") != OTHER_KEY:
            continue
        path = Path(str(item.get("path") or ""))
        digest = scene_ahash_path(path)
        if digest is not None:
            hashes.append(digest)
    return hashes


def _looks_rejected(image: Image.Image, rejected: list[int]) -> bool:
    if not rejected:
        return False
    current = scene_ahash(image)
    return any(hashes_too_close(current, other) for other in rejected)


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
    groups: list[list[tuple[str, int, float, float]]] = [[hits[0]]]
    for item in hits[1:]:
        last = groups[-1][-1]
        if item[0] == last[0] and item[1] - last[1] <= gap_frames:
            groups[-1].append(item)
        else:
            groups.append([item])
    return [max(group, key=lambda row: row[3]) for group in groups]


def find_scene_points(
    info: VideoInfo,
    progress=None,
    want_kinds: set[str] | None = None,
) -> list[SamplePoint]:
    if not scene_model_ready():
        raise ValueError("画面のモデルがありません。画像を教えて学習してください。")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model, classes = load_scene_checkpoint(device)
    rejected = other_scene_hashes()
    transform = transforms.Compose(
        [
            transforms.Resize((SCENE_INPUT, SCENE_INPUT)),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )
    step = max(1, int(round(info.fps * 0.2)))
    cap = cv2.VideoCapture(str(info.path))
    if not cap.isOpened():
        raise ValueError(f"動画を開けませんでした: {info.path.name}")
    hits: list[tuple[str, int, float, float]] = []
    frame_index = 0
    total = max(info.frame_count, 1)
    try:
        while True:
            if frame_index % step == 0:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                tensor = transform(image).unsqueeze(0).to(device)
                with torch.no_grad():
                    probs = torch.softmax(model(tensor), dim=1)[0]
                score, index = float(probs.max().item()), int(probs.argmax().item())
                kind = classes[index] if 0 <= index < len(classes) else OTHER_KEY
                if (
                    kind != OTHER_KEY
                    and score >= SCENE_THRESHOLD
                    and (want_kinds is None or kind in want_kinds)
                    and not _looks_rejected(image, rejected)
                ):
                    hits.append((kind, frame_index, frame_index / info.fps, score))
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
    points: list[SamplePoint] = []
    for i, (kind, frame, seconds, score) in enumerate(_group_hits(hits, max(step * 3, 1)), start=1):
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
