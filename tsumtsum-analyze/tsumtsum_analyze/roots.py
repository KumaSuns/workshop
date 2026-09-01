from __future__ import annotations

from pathlib import Path

WORKSHOP_ROOT = Path(__file__).resolve().parents[2]

_data_dir: Path | None = None
_assets_dir: Path | None = None


def set_roots(*, data_dir: Path | None = None, assets_dir: Path | None = None) -> None:
    global _data_dir, _assets_dir
    if data_dir is not None:
        _data_dir = Path(data_dir)
    if assets_dir is not None:
        _assets_dir = Path(assets_dir)


def data_dir() -> Path:
    if _data_dir is not None:
        return _data_dir
    return WORKSHOP_ROOT / "tsumtsum-screen-recognition" / "data"


def assets_dir() -> Path:
    if _assets_dir is not None:
        return _assets_dir
    return WORKSHOP_ROOT / "video-frame-extractor" / "app" / "assets"


def extractor_root() -> Path:
    return WORKSHOP_ROOT / "video-frame-extractor"


def readers_dir() -> Path:
    bundled = Path(__file__).resolve().parent / "readers"
    if (bundled / "hud_number.py").is_file():
        return bundled
    return WORKSHOP_ROOT / "tsumtsum-screen-recognition" / "app"
