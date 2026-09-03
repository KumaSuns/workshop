from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtGui import QImage

from app.paths import APP_ROOT

TRAINER_ROOT = APP_ROOT.parent / "tsumtsum-screen-recognition"


def load_play_tools() -> tuple[object, Callable[[list[dict[str, int]]], list[dict[str, int]]]]:
    hidden = {
        key: sys.modules.pop(key)
        for key in list(sys.modules)
        if key == "app" or key.startswith("app.")
    }
    root = str(TRAINER_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    predictor = None
    chain_fn = None
    keep: dict[str, object] = {}
    try:
        from app.dataset import Dataset
        from app.predictor import Predictor
        from app.tsum_chain import tsum_chain_best_per_group

        models = TRAINER_ROOT / "data" / "models"
        piece_path = models / "pieces.pt"
        if not piece_path.is_file():
            raise FileNotFoundError(
                "ツムの〇モデルがありません。画面認識アプリで学習してください。"
            )
        predictor = Predictor(models)
        chain_fn = tsum_chain_best_per_group
        keep = {
            key: sys.modules[key]
            for key in list(sys.modules)
            if key == "app" or key.startswith("app.")
        }
        predictor._dataset_cls = Dataset
        predictor._trainer_modules = keep
        if getattr(predictor, "scene_model", None) is None:
            raise RuntimeError(
                "TIME UP のモデルがありません。動画フレーム抜き出しで GO / TIME UP を学習してください。"
            )
        return predictor, chain_fn
    finally:
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(hidden)
        if predictor is not None:
            predictor._trainer_modules = keep


PLAY_TRAIN_EPOCHS = 8


def train_play_models(predictor, stop=None) -> list[str]:
    hidden = {
        key: sys.modules.pop(key)
        for key in list(sys.modules)
        if key == "app" or key.startswith("app.")
    }
    root = str(TRAINER_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    keep = dict(getattr(predictor, "_trainer_modules", None) or {})
    sys.modules.update(keep)
    ran: list[str] = []
    try:
        from app.dataset import Dataset
        from app.regions import PIECE_KEYS, SCENE_KEYS
        from app.train_worker import MIN_TRAIN_SAMPLES, TrainingCancelled, TrainWorker

        dataset = Dataset(TRAINER_ROOT / "data")
        jobs = _play_train_jobs(dataset, MIN_TRAIN_SAMPLES, PIECE_KEYS, SCENE_KEYS)
        if not jobs:
            return []
        if getattr(predictor, "release", None) is not None:
            predictor.release()
        worker = TrainWorker(jobs, epochs=PLAY_TRAIN_EPOCHS)
        inner = worker._raise_if_cancelled

        def _raise() -> None:
            if stop is not None and stop.is_set():
                raise TrainingCancelled()
            inner()

        worker._raise_if_cancelled = _raise
        try:
            worker._train()
            ran = [str(item[3] if len(item) > 3 else item[0]) for item in jobs]
        except TrainingCancelled:
            ran = []
        finally:
            worker._release_cuda()
            if getattr(predictor, "reload", None) is not None:
                predictor.reload()
        return ran
    finally:
        keep = {
            key: sys.modules[key]
            for key in list(sys.modules)
            if key == "app" or key.startswith("app.")
        }
        if predictor is not None:
            predictor._trainer_modules = keep
        if added:
            try:
                sys.path.remove(root)
            except ValueError:
                pass
        for key in list(sys.modules):
            if key == "app" or key.startswith("app."):
                del sys.modules[key]
        sys.modules.update(hidden)


def _play_train_jobs(dataset, min_n, piece_keys, scene_keys) -> list[tuple]:
    jobs: list[tuple] = []
    piece_map = {
        sample.id: sample
        for key in piece_keys
        for sample in dataset.labeled_for(key)
    }
    piece_samples = list(piece_map.values())
    if len(piece_samples) >= min_n:
        type_samples = [
            sample
            for sample in piece_samples
            if len(
                {
                    int(piece.get("group") or 1)
                    for piece in sample.pieces
                    if piece.get("kind") == "tsum"
                }
            )
            >= 2
        ]
        if len(type_samples) >= min_n:
            jobs.append(("tsum_types", type_samples, dataset.model_path_for("tsum_types"), "ツムの種類"))
        jobs.append(("pieces", piece_samples, dataset.model_path_for("pieces"), "ツム・ボム"))
    digit_samples = dataset.labeled_digit_samples()
    if len(digit_samples) >= min_n:
        jobs.append(("coin_digits", digit_samples, dataset.model_path_for("coin_digits"), "コインの数字"))
    playable = [sample for sample in dataset.all() if sample.status != "skipped"]
    others = sum(
        1
        for sample in playable
        if not any(key in sample.confirmed for key in scene_keys)
    )
    if (
        all(len(dataset.labeled_for(key)) >= min_n for key in scene_keys)
        and others >= min_n
    ):
        jobs.append(("scene", playable, dataset.model_path_for("scene"), "GO・TIME UP"))
    return jobs


def save_erase_lesson(
    predictor,
    image_path: Path,
    game: dict[str, int] | None,
    pieces: list[dict[str, int]],
) -> bool:
    dataset_cls = getattr(predictor, "_dataset_cls", None)
    if dataset_cls is None:
        return False
    data = Path(image_path).read_bytes()
    dataset = dataset_cls(TRAINER_ROOT / "data")
    sample = dataset._import_bytes(data, Path(image_path).suffix or ".png", "autoplay")
    regions = {}
    if game is not None:
        regions["game"] = {
            "x": int(game["x"]),
            "y": int(game["y"]),
            "w": int(game["w"]),
            "h": int(game["h"]),
        }
    dataset.set_regions(sample.id, regions, status="labeled", pieces=pieces)
    return True


HUD_KEYS = (
    "game",
    "score",
    "coin",
    "result_coin",
    "timer",
    "skill",
    "fan",
    "pause",
    "fever",
)
DIGIT_KEYS = ("coin", "result_coin")
RESULT_KEYS = ("result_coin", "score")


def save_play_board(
    predictor,
    image: QImage,
    game: dict[str, int] | None,
    boxes: dict[str, dict[str, int]] | None = None,
    pieces: list[dict[str, int]] | None = None,
    rgb=None,
) -> bool:
    hud = _hud_boxes(boxes, HUD_KEYS)
    if game is not None and "game" not in hud:
        hud["game"] = {
            "x": int(game["x"]),
            "y": int(game["y"]),
            "w": int(game["w"]),
            "h": int(game["h"]),
        }
    return _save_labeled(
        predictor,
        image,
        hud,
        pieces=pieces or [],
        readings=_digit_readings(predictor, rgb, hud),
        confirm_regions=False,
    )


def save_play_scene(predictor, image: QImage, key: str) -> bool:
    return _save_labeled(predictor, image, {}, pieces=[], scene=key)


def save_play_result(predictor, image: QImage, boxes: dict[str, dict[str, int]] | None, rgb=None) -> bool:
    hud = _hud_boxes(boxes, RESULT_KEYS)
    if not hud:
        return False
    return _save_labeled(
        predictor,
        image,
        hud,
        pieces=[],
        readings=_digit_readings(predictor, rgb, hud),
        confirm_regions=False,
    )


def _hud_boxes(boxes: dict[str, dict[str, int]] | None, keys: tuple[str, ...]) -> dict[str, dict[str, int]]:
    hud: dict[str, dict[str, int]] = {}
    if not boxes:
        return hud
    for key in keys:
        box = boxes.get(key)
        if not box:
            continue
        hud[key] = {
            "x": int(box["x"]),
            "y": int(box["y"]),
            "w": int(box["w"]),
            "h": int(box["h"]),
        }
    return hud


def _digit_readings(predictor, rgb, boxes: dict[str, dict[str, int]]) -> dict[str, str]:
    readings: dict[str, str] = {}
    if rgb is None or not boxes:
        return readings
    for key in DIGIT_KEYS:
        box = boxes.get(key)
        if not box:
            continue
        try:
            crop = rgb.crop(
                (
                    int(box["x"]),
                    int(box["y"]),
                    int(box["x"]) + int(box["w"]),
                    int(box["y"]) + int(box["h"]),
                )
            )
            digits = "".join(
                char for char in str(predictor.predict_coin_digits(crop, key) or "") if char.isdigit()
            )
        except Exception:
            continue
        if digits:
            readings[key] = digits
    return readings


def _save_labeled(
    predictor,
    image: QImage,
    regions: dict[str, dict[str, int]],
    pieces: list[dict[str, int]] | None = None,
    readings: dict[str, str] | None = None,
    scene: str | None = None,
    confirm_regions: bool = True,
) -> bool:
    dataset_cls = getattr(predictor, "_dataset_cls", None)
    if dataset_cls is None or image is None or image.isNull():
        return False
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dataset = dataset_cls(TRAINER_ROOT / "data")
    before = len(dataset.all())
    sample = dataset.import_qimage(
        image,
        source_name=f"bluestacks_{stamp}.png",
        name_prefix="bluestacks_",
    )
    if len(dataset.all()) <= before:
        return False
    status = "labeled" if confirm_regions or scene else "predicted"
    dataset.set_regions(sample.id, regions, status=status, pieces=pieces or [])
    if not confirm_regions and regions:
        sample = dataset.get(sample.id)
        if sample is not None:
            sample.confirmed = [key for key in sample.confirmed if key not in regions]
            sample.status = "predicted" if not scene else sample.status
            dataset.save()
    if readings:
        for key, digits in readings.items():
            try:
                dataset.set_reading(sample.id, key, digits)
            except Exception:
                continue
    if scene:
        dataset.confirm_key(sample.id, scene)
    return True
