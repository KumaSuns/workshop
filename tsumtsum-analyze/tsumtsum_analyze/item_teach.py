from __future__ import annotations

import colorsys
import json
import math
import re
from hashlib import sha256
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QThread, Signal

from tsumtsum_analyze.item_slots import crop_box
from tsumtsum_analyze.roots import assets_dir

MIN_TSUM_SAMPLES = 1
TSUM_EPOCHS = 1
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_BAD_DIR = re.compile(r'[<>:"/\\|?*]+')
# Analyzer の item 画面 use_tsum 範囲。フル画面の見本だけ切る。
_SCREEN_TSUM_RECT = (0.7791, 0.7704, 0.1163, 0.0511)


def use_tsums_root() -> Path:
    return assets_dir() / "images" / "use_tsums"


def _models_root() -> Path:
    return assets_dir() / "models" / "use_tsum"


def _registry_path() -> Path:
    return _models_root() / "registry.json"


def _name_only(text: str) -> str:
    return " ".join((text or "").split())


def _dir_name(name: str) -> str:
    cleaned = _BAD_DIR.sub("", _name_only(name)).strip(" .")
    return cleaned or "tsum"


def _load_registry() -> dict[str, str]:
    path = _registry_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def _save_registry(registry: dict[str, str]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def tsum_image_count() -> int:
    root = use_tsums_root()
    if not root.is_dir():
        return 0
    total = 0
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        total += sum(1 for child in folder.iterdir() if child.is_file() and child.suffix.lower() in _IMAGE_EXTS)
    return total


def tsum_teaching_count() -> int:
    return tsum_image_count()


def tsum_class_names() -> list[str]:
    registry = _load_registry()
    names = list(registry.values())
    root = use_tsums_root()
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir() and folder.name not in registry:
                names.append(folder.name)
    return sorted(set(names), key=lambda value: value.casefold())


def tsum_id_for_name(name: str) -> str | None:
    cleaned = _name_only(name)
    if not cleaned:
        return None
    registry = _load_registry()
    for dir_id, display in registry.items():
        if display == cleaned or dir_id == cleaned:
            return dir_id
    wanted = _dir_name(cleaned)
    root = use_tsums_root()
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir() and folder.name in {cleaned, wanted}:
                return folder.name
    return None


def tsum_display_name(tsum_id: str) -> str:
    return _load_registry().get(tsum_id, tsum_id)


def shown_tsum_name(name: str) -> str:
    tid = tsum_id_for_name(name)
    if tid:
        return tsum_display_name(tid)
    return name


def tsum_folder_entries() -> list[tuple[str, str]]:
    registry = _load_registry()
    ids = set(registry.keys())
    root = use_tsums_root()
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir():
                ids.add(folder.name)
    return sorted(((tid, registry.get(tid, tid)) for tid in ids), key=lambda row: row[1].casefold())


def set_tsum_display_name(tsum_id: str, display: str) -> str:
    folder = _dir_name(tsum_id)
    cleaned = _name_only(display)
    if not folder:
        raise ValueError("フォルダ名がありません")
    if not cleaned:
        raise ValueError("表示名を入力してください")
    registry = _load_registry()
    registry[folder] = cleaned
    _save_registry(registry)
    return cleaned


def _ensure_gitkeep(folder: Path) -> None:
    gitkeep = folder / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.write_text("", encoding="utf-8")


def save_tsum_teaching(
    image_path: Path,
    box: dict[str, int],
    name: str,
    source_video: Path | str | None = None,
    source_frame: int | None = None,
) -> tuple[int, str]:
    cleaned_name = _name_only(name)
    if not cleaned_name:
        raise ValueError("ツムの名前を入力してください")
    if not image_path.is_file():
        raise ValueError("画像がありません")
    tsum_id = tsum_id_for_name(cleaned_name) or _dir_name(cleaned_name)
    folder = use_tsums_root() / tsum_id
    folder.mkdir(parents=True, exist_ok=True)
    _ensure_gitkeep(folder)
    with Image.open(image_path) as image:
        crop = crop_box(image.convert("RGB"), box)
    digest = sha256(image_path.read_bytes() + str(box).encode("utf-8")).hexdigest()[:12]
    dest = folder / f"{digest}.png"
    crop.save(dest, format="PNG")
    registry = _load_registry()
    if tsum_id not in registry:
        registry[tsum_id] = cleaned_name
    _save_registry(registry)
    _rebuild_tsum_model(tsum_id)
    return tsum_image_count(), tsum_display_name(tsum_id)


def save_tsum_screen(
    image_path: Path,
    name: str,
    source_video: Path | str | None = None,
    source_frame: int | None = None,
    folder_id: str | None = None,
) -> tuple[int, str]:
    cleaned_name = _name_only(name)
    if not cleaned_name:
        raise ValueError("ツムの名前を入力してください")
    if not image_path.is_file():
        raise ValueError("画像がありません")
    tsum_id = _dir_name(folder_id) if folder_id else (tsum_id_for_name(cleaned_name) or _dir_name(cleaned_name))
    folder = use_tsums_root() / tsum_id
    folder.mkdir(parents=True, exist_ok=True)
    _ensure_gitkeep(folder)
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
    digest = sha256(image_path.read_bytes()).hexdigest()[:12]
    dest = folder / f"{digest}.png"
    rgb.save(dest, format="PNG")
    registry = _load_registry()
    registry[tsum_id] = cleaned_name
    _save_registry(registry)
    _rebuild_tsum_model(tsum_id)
    return tsum_image_count(), tsum_display_name(tsum_id)


def _crop_screen_tsum(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width < 400 or height < 700:
        return image
    nx, ny, nw, nh = _SCREEN_TSUM_RECT
    left = max(0, min(int(nx * width), width - 1))
    top = max(0, min(int(ny * height), height - 1))
    right = max(left + 1, min(int((nx + nw) * width), width))
    bottom = max(top + 1, min(int((ny + nh) * height), height))
    return image.crop((left, top, right, bottom))


def _image_to_feature(crop: Image.Image) -> list[float]:
    rgb = crop.convert("RGB")
    color_small = rgb.resize((18, 18), Image.Resampling.BILINEAR)
    h_bins = [0.0] * 18
    s_bins = [0.0] * 8
    v_bins = [0.0] * 8
    pixels = list(color_small.getdata())
    for red, green, blue in pixels:
        hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
        h_bins[min(17, max(0, int(hue * 18)))] += 1.0
        s_bins[min(7, max(0, int(sat * 8)))] += 1.0
        v_bins[min(7, max(0, int(val * 8)))] += 1.0
    total = max(float(len(pixels)), 1.0)
    h_bins = [value / total for value in h_bins]
    s_bins = [value / total for value in s_bins]
    v_bins = [value / total for value in v_bins]
    gray_small = crop.convert("L").resize((14, 14), Image.Resampling.BILINEAR)
    gray_values = [pixel / 255.0 for pixel in gray_small.getdata()]
    if gray_values:
        mean = sum(gray_values) / len(gray_values)
        gray_values = [value - mean for value in gray_values]
    return h_bins + s_bins + v_bins + gray_values


def _l1_distance(left: list[float], right: list[float]) -> float:
    count = min(len(left), len(right))
    if count <= 0:
        return math.inf
    return sum(abs(left[index] - right[index]) for index in range(count)) / count


def _rebuild_tsum_model(tsum_id: str) -> int:
    folder = use_tsums_root() / tsum_id
    feats: list[list[float]] = []
    if folder.is_dir():
        for image_file in sorted(
            path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in _IMAGE_EXTS
        ):
            try:
                with Image.open(image_file) as image:
                    feat = _image_to_feature(_crop_screen_tsum(image.convert("RGB")))
            except Exception:
                continue
            if feat:
                feats.append(feat)
    out_dir = _models_root() / tsum_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "model.json").write_text(
        json.dumps(
            {"tsum_id": tsum_id, "sample_count": len(feats), "prototypes": feats},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return len(feats)


def build_tsum_models() -> dict[str, int]:
    images_root = use_tsums_root()
    _models_root().mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    if not images_root.is_dir():
        return counts
    for tsum_dir in sorted(path for path in images_root.iterdir() if path.is_dir()):
        counts[tsum_dir.name] = _rebuild_tsum_model(tsum_dir.name)
    return counts


class TsumTrainWorker(QThread):
    progress = Signal(int, int, str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.progress.emit(0, 1, "使用ツムの見本を読み込んでいます")
            counts = build_tsum_models()
            samples = sum(counts.values())
            if samples < MIN_TSUM_SAMPLES:
                raise ValueError(
                    f"使用ツムの学習には画像が必要です。app/assets/images/use_tsums に切り抜きを入れてください。"
                    f"いま {samples} 枚です。"
                )
            self.progress.emit(1, 1, "使用ツムの見本を保存しました")
            self.finished_ok.emit(
                {
                    "acc": 1.0,
                    "samples": samples,
                    "classes": list(counts.keys()),
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class TsumReader:
    def __init__(self) -> None:
        self._display: dict[str, str] = {}
        self._prototypes: dict[str, list[list[float]]] = {}
        self.reload()

    def reload(self) -> None:
        self._display = _load_registry()
        self._prototypes = {}
        root = _models_root()
        if not root.is_dir():
            return
        for tsum_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            model_file = tsum_dir / "model.json"
            if not model_file.is_file():
                continue
            try:
                payload = json.loads(model_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            raw = payload.get("prototypes") or []
            feats = [list(map(float, row)) for row in raw if isinstance(row, list)]
            if feats:
                self._prototypes[tsum_dir.name] = feats

    def read_crop(self, crop: Image.Image) -> str:
        if not self._prototypes:
            return ""
        target = _image_to_feature(crop.convert("RGB"))
        best_id = ""
        best_dist = math.inf
        for tsum_id, proto_list in self._prototypes.items():
            dist = min(_l1_distance(target, proto) for proto in proto_list)
            if dist < best_dist:
                best_dist = dist
                best_id = tsum_id
        if not best_id:
            return ""
        return self._display.get(best_id, best_id)

    def read_screen(self, image: Image.Image) -> str:
        return self.read_crop(_crop_screen_tsum(image.convert("RGB")))
