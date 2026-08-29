from __future__ import annotations

import sys
from collections.abc import Callable

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
        from app.predictor import Predictor
        from app.tsum_chain import longest_tsum_chain

        models = TRAINER_ROOT / "data" / "models"
        piece_path = models / "pieces.pt"
        if not piece_path.is_file():
            raise FileNotFoundError(
                "ツムの〇モデルがありません。画面認識アプリで学習してください。"
            )
        predictor = Predictor(models)
        chain_fn = longest_tsum_chain
        keep = {
            key: sys.modules[key]
            for key in list(sys.modules)
            if key == "app" or key.startswith("app.")
        }
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
