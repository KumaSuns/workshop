from __future__ import annotations

from pathlib import Path

OUT_ROOT = Path(__file__).resolve().parents[3]
WORKSHOP_ROOT = OUT_ROOT

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
    return OUT_ROOT / "bundled" / "screen" / "data"


def assets_dir() -> Path:
    if _assets_dir is not None:
        return _assets_dir
    return OUT_ROOT / "bundled" / "assets"


def extractor_root() -> Path:
    return OUT_ROOT / "bundled" / "assets"


def readers_dir() -> Path:
    bundled = Path(__file__).resolve().parent / "readers"
    if (bundled / "hud_number.py").is_file():
        return bundled
    return OUT_ROOT / "bundled" / "screen" / "app"
