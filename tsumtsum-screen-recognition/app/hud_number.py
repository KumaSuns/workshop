from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

_OCR_SCRIPT = r"""
param($ImagePath)
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
$result.Text
"""


def crop_box(image_path: Path, box: dict[str, int]) -> Image.Image:
    with Image.open(image_path) as image:
        rgb = image.convert("RGB")
        left = max(0, int(box["x"]))
        top = max(0, int(box["y"]))
        right = min(rgb.width, left + max(1, int(box["w"])))
        bottom = min(rgb.height, top + max(1, int(box["h"])))
        return rgb.crop((left, top, right, bottom))


def enhance_digits(image: Image.Image) -> Image.Image:
    width, height = image.size
    scale = max(3, int(56 / max(height, 1)))
    large = image.resize((max(1, width * scale), max(1, height * scale)), Image.Resampling.LANCZOS)
    pixels = large.load()
    for y in range(large.height):
        for x in range(large.width):
            red, green, blue = pixels[x, y]
            gold = red > 150 and green > 110 and blue < 200 and red >= green - 10
            white = red > 200 and green > 200 and blue > 180
            pixels[x, y] = (0, 0, 0) if gold or white else (255, 255, 255)
    return large


def digits_from_text(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def format_coin_number(text: str) -> str:
    digits = digits_from_text(text)
    if not digits:
        return ""
    return f"{int(digits):,}"


def _ocr_image(image: Image.Image) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        temp = Path(handle.name)
    try:
        image.save(temp, format="PNG")
        script = temp.with_suffix(".ps1")
        script.write_text(_OCR_SCRIPT, encoding="utf-8")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ImagePath",
                str(temp.resolve()),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=flags,
        )
        if result.returncode != 0:
            return ""
        return (result.stdout or "").strip()
    finally:
        temp.unlink(missing_ok=True)
        temp.with_suffix(".ps1").unlink(missing_ok=True)


def read_coin_number(
    image_path: Path,
    box: dict[str, int],
    predict_fn: Callable[[Image.Image], str] | None = None,
) -> tuple[Image.Image, str]:
    crop = crop_box(image_path, box)
    number = ""
    if predict_fn is not None:
        try:
            number = format_coin_number(predict_fn(crop) or "")
        except Exception:
            number = ""
    if not number:
        enhanced = enhance_digits(crop)
        number = format_coin_number(_ocr_image(enhanced))
    if not number:
        number = format_coin_number(_ocr_image(crop))
    return crop, number


def pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    data = rgb.tobytes()
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


class CoinNumberDialog(QDialog):
    def __init__(self, crop: Image.Image, number: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("コインの数字")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        preview = QLabel()
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = pil_to_pixmap(crop)
        preview.setPixmap(
            pixmap.scaled(320, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        layout.addWidget(preview)
        hint = QLabel(
            "違っていたら直して「この数字を教える」。直すときは 1234 でも 1,234 でも構いません。"
            "教えた数字は次の学習に使います。"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.edit = QLineEdit(number)
        self.edit.setPlaceholderText("数字を読めませんでした")
        self.edit.editingFinished.connect(self._normalize)
        layout.addWidget(self.edit)
        self.taught = False
        row = QHBoxLayout()
        teach_btn = QPushButton("この数字を教える")
        teach_btn.clicked.connect(self._teach)
        row.addWidget(teach_btn)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        row.addWidget(buttons)
        layout.addLayout(row)
        if number:
            self.edit.selectAll()

    def number(self) -> str:
        return format_coin_number(self.edit.text())

    def _normalize(self) -> None:
        formatted = self.number()
        if formatted and formatted != self.edit.text():
            self.edit.setText(formatted)

    def _teach(self) -> None:
        if not self.number():
            return
        self.taught = True
        self.accept()
