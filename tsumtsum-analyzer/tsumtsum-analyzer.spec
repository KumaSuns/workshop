# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP_ROOT = Path(SPECPATH).resolve()
ANALYZE_ROOT = APP_ROOT.parent / "tsumtsum-analyze"
APP_NAME = "ツムツム解析"

datas = []
data_dir = APP_ROOT / "data"
if data_dir.is_dir():
    datas.append((str(data_dir), "data"))
icon = APP_ROOT / "app.ico"
if icon.is_file():
    datas.append((str(icon), "."))

binaries = []
hiddenimports = [
    "tsumtsum_analyze",
    "tsumtsum_analyze.extractor",
    "tsumtsum_analyze.roots",
]

for package in ("PySide6", "cv2"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(APP_ROOT / "main.py")],
    pathex=[str(APP_ROOT), str(ANALYZE_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["torch", "torchvision", "torchaudio"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon) if icon.is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
