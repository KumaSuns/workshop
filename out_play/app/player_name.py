from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from app.paths import APP_ROOT

PATH = APP_ROOT / "data" / "player.json"

_OCR_SCRIPT = r"""
param($ImagePath, $TextPath)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    })[0]
function Await($WinRtTask, $ResultType) {
    $netTask = $asTask.MakeGenericMethod($ResultType).Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) { return }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
[System.IO.File]::WriteAllText($TextPath, $result.Text, (New-Object System.Text.UTF8Encoding $false))
"""


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x9FFF
        or 0xFF66 <= code <= 0xFF9D
    )


def _clean_name(text: str) -> str:
    raw = " ".join(text.split())
    out = []
    index = 0
    while index < len(raw):
        ch = raw[index]
        if (
            ch == " "
            and out
            and index + 1 < len(raw)
            and _is_cjk(out[-1])
            and _is_cjk(raw[index + 1])
        ):
            index += 1
            continue
        out.append(ch)
        index += 1
    return "".join(out).strip().rstrip(" .。…・")


def _name_image(image: QImage) -> QImage:
    x = min(image.width() - 1, max(0, int(round(220 * image.width() / 576))))
    y = min(image.height() - 1, max(0, int(round(305 * image.height() / 1024))))
    width = max(1, int(round(190 * image.width() / 576)))
    height = max(1, int(round(42 * image.height() / 1024)))
    width = min(width, image.width() - x)
    height = min(height, image.height() - y)
    crop = image.copy(x, y, width, height)
    return crop.scaled(
        width * 4,
        height * 4,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _ocr(image: QImage) -> str:
    if image is None or image.isNull():
        return ""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        png = root / "name.png"
        text_path = root / "name.txt"
        script = root / "ocr.ps1"
        image.save(str(png))
        script.write_text(_OCR_SCRIPT, encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ImagePath",
                str(png.resolve()),
                "-TextPath",
                str(text_path.resolve()),
            ],
            check=False,
            capture_output=True,
            creationflags=flags,
        )
        if not text_path.exists():
            return ""
        return _clean_name(text_path.read_text(encoding="utf-8"))


def read_ranking_name(image: QImage) -> str:
    if image is None or image.isNull():
        return ""
    return _ocr(_name_image(image))


def save_player_name(name: str) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(
        json.dumps({"name": name}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
