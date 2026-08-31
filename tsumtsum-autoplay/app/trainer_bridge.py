from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from app.paths import APP_ROOT

TRAINER_ROOT = APP_ROOT.parent / "tsumtsum-screen-recognition"
EXTRACTOR_ROOT = APP_ROOT.parent / "video-frame-extractor"


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
        if "coin" not in getattr(predictor, "digit_models", {}):
            raise RuntimeError("コインの数字モデルがありません。画面認識アプリで学習してください。")
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
            _attach_coin_scene(predictor)
            _attach_coin_reader(predictor)


def _attach_coin_scene(predictor) -> None:
    predictor.coin_scene_model = None
    predictor.coin_scene_classes = ()
    path = TRAINER_ROOT / "data" / "extractor" / "scene.pt"
    if not path.is_file():
        return
    mods = getattr(predictor, "_trainer_modules", {}) or {}
    scene_mod = mods.get("app.scene_model")
    if scene_mod is None:
        return
    import torch

    checkpoint = torch.load(path, map_location=predictor.device, weights_only=False)
    classes = (
        tuple(checkpoint.get("classes") or ())
        if isinstance(checkpoint, dict)
        else ()
    )
    if "coin" not in classes:
        return
    model = scene_mod.SceneNet(pretrained=False, num_classes=len(classes))
    state = (
        checkpoint["state_dict"]
        if isinstance(checkpoint, dict) and "state_dict" in checkpoint
        else checkpoint
    )
    try:
        model.load_state_dict(state)
    except Exception:
        return
    model.to(predictor.device)
    model.eval()
    predictor.coin_scene_model = model
    predictor.coin_scene_classes = classes


def _attach_coin_reader(predictor) -> None:
    predictor.coin_reader = None
    hidden = {
        key: sys.modules.pop(key)
        for key in list(sys.modules)
        if key == "app" or key.startswith("app.")
    }
    root = str(EXTRACTOR_ROOT)
    added = root not in sys.path
    if added:
        sys.path.insert(0, root)
    try:
        from app.coin_read import CoinReader

        predictor.coin_reader = CoinReader()
        keep = {
            key: sys.modules[key]
            for key in list(sys.modules)
            if key == "app" or key.startswith("app.")
        }
        predictor.coin_reader._extractor_modules = keep
    except Exception:
        predictor.coin_reader = None
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
