from __future__ import annotations

import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageOps
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


def _tight_ink(crop: Image.Image) -> Image.Image:
    gray = crop.convert("L")
    width, height = gray.size
    limit = max(48, int(gray.getextrema()[1] * 0.55))
    pixels = gray.load()
    xs = [x for x in range(width) if any(pixels[x, y] >= limit for y in range(height))]
    ys = [y for y in range(height) if any(pixels[x, y] >= limit for x in range(width))]
    if not xs or not ys:
        return crop
    pad = 2
    return crop.crop(
        (
            max(0, xs[0] - pad),
            max(0, ys[0] - pad),
            min(width, xs[-1] + 1 + pad),
            min(height, ys[-1] + 1 + pad),
        )
    )


def _drop_comma(crop: Image.Image) -> Image.Image:
    gray = crop.convert("L")
    width, height = gray.size
    if width < 24:
        return crop
    limit = max(48, int(gray.getextrema()[1] * 0.55))
    pixels = gray.load()
    ink = [
        sum(1 for y in range(height) if pixels[x, y] >= limit) / max(height, 1)
        for x in range(width)
    ]
    left = int(width * 0.18)
    right = int(width * 0.72)
    if right - left < 8:
        return crop
    cut = min(range(left, right), key=lambda x: ink[x])
    if ink[cut] > 0.12:
        return crop
    lo, hi = cut, cut
    while lo > left and ink[lo] < 0.14:
        lo -= 1
    while hi < right - 1 and ink[hi] < 0.14:
        hi += 1
    if not (2 <= hi - lo <= max(10, width // 10)):
        return crop
    left_img = crop.crop((0, 0, max(1, lo), height))
    right_img = crop.crop((min(width, hi), 0, width, height))
    joined = Image.new("RGB", (left_img.size[0] + right_img.size[0], height))
    joined.paste(left_img, (0, 0))
    joined.paste(right_img, (left_img.size[0], 0))
    return joined


_SLOT_COUNT = 8
_SLOT_WIDTH_RATIO = 0.72


def _is_gold_pixel(red: int, green: int, blue: int) -> bool:
    return red > 160 and green > 110 and blue < 180 and red >= green - 20 and red > blue + 25


def _gold_icon_width(crop: Image.Image) -> int:
    rgb = crop.convert("RGB")
    width, height = rgb.size
    if width < 16 or height < 8:
        return 0
    pixels = rgb.load()
    last = 0
    limit = min(width - 8, max(8, int(min(height * 1.2, width * 0.45))))
    for x in range(limit):
        gold = 0
        for y in range(height):
            red, green, blue = pixels[x, y]
            if _is_gold_pixel(red, green, blue):
                gold += 1
        if gold / height > 0.12:
            last = x + 1
    if last < 8:
        return 0
    return min(width - 8, last + max(2, height // 12))


def _pad_to_slots(crop: Image.Image) -> Image.Image:
    width, height = crop.size
    if height < 4:
        return crop
    canvas_w = max(width, int(round(height * _SLOT_WIDTH_RATIO)) * _SLOT_COUNT)
    if canvas_w <= width:
        return crop
    canvas = Image.new("RGB", (canvas_w, height), (0, 0, 0))
    canvas.paste(crop.convert("RGB"), (0, 0))
    return canvas


def prepare_digit_crop(crop: Image.Image, key: str = "coin") -> Image.Image:
    crop = crop.convert("RGB")
    if key != "coin":
        return crop
    crop = ImageOps.autocontrast(crop, cutoff=1)
    skip = _gold_icon_width(crop)
    if skip >= 8:
        crop = crop.crop((skip, 0, crop.size[0], crop.size[1]))
        crop = ImageOps.autocontrast(crop, cutoff=1)
    crop = _tight_ink(crop)
    crop = _drop_comma(crop)
    return _pad_to_slots(crop)


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
