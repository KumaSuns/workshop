from __future__ import annotations

from pathlib import Path

import cv2
from PIL import Image

from tsumtsum_analyze.extractor import VideoInfo
from tsumtsum_analyze.item_teach import _IMAGE_EXTS, _image_to_feature, _l1_distance
from tsumtsum_analyze.roots import assets_dir

SKILL_MATCH_MAX = 0.04
SKILL_SAMPLE_SEC = 0.1
SKILL_HIT_STREAK = 3
SKILL_OFF_STREAK = 3
SKILL_MIN_GAP_SEC = 2.5


def skills_root() -> Path:
    return assets_dir() / "images" / "skills"


def skill_image_paths(tsum_id: str) -> list[Path]:
    folder = skills_root() / tsum_id
    if not folder.is_dir():
        return []
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in _IMAGE_EXTS
    )


def has_skill_images(tsum_id: str) -> bool:
    return bool(skill_image_paths(tsum_id))


def _prototypes_for(tsum_id: str) -> list[list[float]]:
    feats: list[list[float]] = []
    for path in skill_image_paths(tsum_id):
        try:
            with Image.open(path) as image:
                feat = _image_to_feature(image.convert("RGB"))
        except Exception:
            continue
        if feat:
            feats.append(feat)
    return feats


def _match_limit(prototypes: list[list[float]]) -> float:
    if len(prototypes) < 2:
        return SKILL_MATCH_MAX
    worst = 0.0
    for i, left in enumerate(prototypes):
        for j, right in enumerate(prototypes):
            if i == j:
                continue
            worst = max(worst, _l1_distance(left, right))
    return min(SKILL_MATCH_MAX, max(0.028, worst * 1.05))


def _hits_skill(image: Image.Image, prototypes: list[list[float]], limit: float) -> bool:
    feat = _image_to_feature(image.convert("RGB"))
    if not feat:
        return False
    dist = min(_l1_distance(feat, proto) for proto in prototypes)
    return dist <= limit


def count_skill_uses(
    info: VideoInfo,
    windows: list[tuple[float, float, str]],
    progress=None,
) -> int | None:
    needed = list(dict.fromkeys(tsum_id for _start, _end, tsum_id in windows if tsum_id))
    models = {tsum_id: _prototypes_for(tsum_id) for tsum_id in needed}
    models = {tsum_id: feats for tsum_id, feats in models.items() if feats}
    if not models:
        return None
    limits = {tsum_id: _match_limit(feats) for tsum_id, feats in models.items()}
    usable = [
        (start, end, tsum_id)
        for start, end, tsum_id in windows
        if tsum_id in models and end > start
    ]
    if not usable:
        return None
    step = max(1, int(round(info.fps * SKILL_SAMPLE_SEC)))
    states = []
    for start, end, tsum_id in usable:
        states.append(
            {
                "start": max(0, int(start * info.fps)),
                "end": min(info.frame_count - 1, int(end * info.fps)),
                "tsum_id": tsum_id,
                "raw": 0,
                "off": 0,
                "episode": False,
                "last_frame": None,
            }
        )
    begin = min(item["start"] for item in states)
    finish = max(item["end"] for item in states)
    cap = cv2.VideoCapture(str(info.path))
    if not cap.isOpened():
        return None
    total = 0
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(begin))
        frame_index = begin
        while frame_index <= finish:
            active = [item for item in states if item["start"] <= frame_index <= item["end"]]
            if not active:
                nxt = min(
                    (item["start"] for item in states if item["start"] > frame_index),
                    default=None,
                )
                if nxt is None:
                    break
                cap.set(cv2.CAP_PROP_POS_FRAMES, float(nxt))
                frame_index = nxt
                continue
            if progress is not None:
                progress(frame_index - begin + 1, max(finish - begin, 1), "skill")
            if frame_index % step == 0:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                for item in active:
                    prototypes = models[item["tsum_id"]]
                    limit = limits[item["tsum_id"]]
                    if _hits_skill(image, prototypes, limit):
                        item["raw"] = min(item["raw"] + 1, 30)
                        item["off"] = 0
                        if item["raw"] >= SKILL_HIT_STREAK and not item["episode"]:
                            item["episode"] = True
                            last = item["last_frame"]
                            if last is None or (frame_index - last) / max(info.fps, 1e-6) >= SKILL_MIN_GAP_SEC:
                                total += 1
                                item["last_frame"] = frame_index
                    else:
                        item["raw"] = 0
                        item["off"] += 1
                        if item["off"] >= SKILL_OFF_STREAK:
                            item["episode"] = False
            elif not cap.grab():
                break
            frame_index += 1
    finally:
        cap.release()
    return total
