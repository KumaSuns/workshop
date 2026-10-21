from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QRegularExpression, QSettings, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parent
WORKSHOP = ROOT.parent
MODELS_API = "http://hokkai-syabusyabu.com/home_page/workshop/models/api.php"
LOGO_PATH = ROOT / "images" / "rogo_003.png"
ICON_DIR = ROOT / "icons"
ITEM_ICONS = (
    "Score.png",
    "Coin.png",
    "Exp.png",
    "Time.png",
    "Bomb.png",
    "5over4.png",
    "Combo.png",
)
ITEM_DIM = 0.6
ITEM_MIST = 0.6
TITLE_POINT = 14
TITLE_MARGIN = 16


def _dim_pixmap(pixmap: QPixmap) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() < 16:
                continue
            color.setRed(int(color.red() * ITEM_DIM))
            color.setGreen(int(color.green() * ITEM_DIM))
            color.setBlue(int(color.blue() * ITEM_DIM))
            image.setPixelColor(x, y, color)
    return QPixmap.fromImage(image)


def _mist_pixmap(pixmap: QPixmap) -> QPixmap:
    if pixmap.isNull():
        return pixmap
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    keep = 1.0 - ITEM_MIST
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() < 16:
                continue
            color.setRed(int(color.red() * keep + 255 * ITEM_MIST))
            color.setGreen(int(color.green() * keep + 255 * ITEM_MIST))
            color.setBlue(int(color.blue() * keep + 255 * ITEM_MIST))
            image.setPixelColor(x, y, color)
    return QPixmap.fromImage(image)


def _logo_source() -> QPixmap:
    image = QImage(str(LOGO_PATH)).convertToFormat(QImage.Format.Format_ARGB32)
    if image.isNull():
        return QPixmap()
    width = image.width()
    height = image.height()
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            if color.red() > 245 and color.green() > 245 and color.blue() > 245:
                color.setAlpha(0)
                image.setPixelColor(x, y, color)
                continue
            if color.alpha() < 16:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    if max_x < min_x:
        return QPixmap.fromImage(image)
    return QPixmap.fromImage(
        image.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)
    )


class MenuWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("メニュー")
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._header = QWidget()
        self._footer = QWidget()
        blue = root.palette()
        blue.setColor(QPalette.ColorRole.Window, QColor("#A4C6FF"))
        for band in (self._header, self._footer):
            band.setAutoFillBackground(True)
            band.setPalette(blue)
        self._logo_src = _logo_source()
        self._logo = QLabel()
        self._logo.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._logo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(50, 0, 0, 0)
        header_layout.addWidget(self._logo, 1)
        self._front = QCheckBox("最前面")
        self._front.setStyleSheet("background: transparent;")
        self._front.toggled.connect(self._set_front)
        header_layout.addWidget(
            self._front,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        line = self.fontMetrics().lineSpacing()
        self._header.setFixedHeight(line * 2)
        self._footer.setFixedHeight(line * 2)
        layout.addWidget(self._header)
        self._slots = []
        self._item_box = None
        self._item_src = []
        self._item_labels = []
        self._item_rows = []
        self._item_block = None
        self._center_slot = None
        self._center_buttons = []
        self._center_input = None
        self._launch_button = None
        for _ in range(3):
            slot = QFrame()
            slot.setFrameShape(QFrame.Shape.Box)
            layout.addWidget(slot, 1)
            self._slots.append(slot)
        self._fill_items(self._slots[0])
        self._fill_center(self._slots[1])
        self._model_update_check = _ModelUpdateCheck(self)
        self._model_update_check.found.connect(self._set_model_update)
        self._model_update_check.start()
        layout.addWidget(self._footer)
        self.setCentralWidget(root)
        self._placed = False
        self._fitting_logo = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._placed:
            return
        self._placed = True
        QTimer.singleShot(0, self._fill_right)

    def _fill_right(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        extra_w = max(0, frame.width() - self.width())
        extra_h = max(0, frame.height() - self.height())
        half = area.width() // 2
        gap = half * 3 // 100
        outer_w = half - gap
        self.resize(
            max(1, outer_w - extra_w),
            max(1, area.height() - extra_h),
        )
        frame = self.frameGeometry()
        self.move(area.right() - gap - frame.width() + 1, area.top())
        self._fit_logo()
        QTimer.singleShot(0, self._fit_items)
        QTimer.singleShot(0, self._fit_center)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_logo()
        QTimer.singleShot(0, self._fit_items)
        QTimer.singleShot(0, self._fit_center)

    def _fit_logo(self) -> None:
        if self._fitting_logo or self._logo_src.isNull():
            return
        width = self._logo.width()
        if width <= 1:
            width = self._header.width()
        if width <= 1:
            return
        height = self._header.height()
        if height <= 1:
            self._fitting_logo = False
            return
        self._fitting_logo = True
        logo_h = max(1, height * 7 // 10)
        scaled = self._logo_src.scaled(
            max(1, width),
            logo_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._logo.setPixmap(scaled)
        self._fitting_logo = False

    def _fill_items(self, slot: QFrame) -> None:
        column = QVBoxLayout(slot)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        frames = QHBoxLayout()
        frames.setContentsMargins(0, 0, 0, 0)
        frames.setSpacing(0)
        boxes = []
        for _ in range(3):
            box = QFrame()
            box.setFrameShape(QFrame.Shape.Box)
            frames.addWidget(box, 1)
            boxes.append(box)
        column.addLayout(frames, 1)
        self._item_box = boxes[1]
        inner = QVBoxLayout(self._item_box)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        inner.addWidget(self._section_title("使用アイテム"))
        block = QWidget()
        block.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(0)
        self._item_block = block_layout
        for names in (ITEM_ICONS[:4], ITEM_ICONS[4:]):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self._item_rows.append(row)
            for filename in names:
                label = QLabel()
                self._item_src.append(
                    _mist_pixmap(_dim_pixmap(QPixmap(str(ICON_DIR / filename))))
                )
                self._item_labels.append(label)
                row.addWidget(label)
            block_layout.addLayout(row)
        inner.addWidget(block, 0, Qt.AlignmentFlag.AlignHCenter)
        inner.addStretch(1)
        left = QVBoxLayout(boxes[0])
        left.setContentsMargins(0, 0, 0, TITLE_MARGIN)
        left.setSpacing(0)
        left.addWidget(self._section_title("MODEL情報"))
        left.addStretch(1)
        self._update_button = QPushButton("更新なし")
        self._update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_button.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        self._update_button.setStyleSheet(
            "QPushButton {"
            " background: #ffffff;"
            " color: #2c4a7a;"
            " font-weight: 700;"
            " font-size: 10pt;"
            " border: 1px solid #8eb4ee;"
            " border-radius: 6px;"
            " padding: 3px 26px;"
            "}"
            "QPushButton:hover { background: #f3f7ff; }"
        )
        left.addWidget(self._update_button, 0, Qt.AlignmentFlag.AlignHCenter)

    def _create_desktop_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        lnk = Path(desktop) / "AUTO PLAY.lnk"
        old = Path(desktop) / "メニュー.lnk"
        if old.exists() and old != lnk:
            old.unlink()
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        script = ROOT / "main.py"
        icon = ROOT / "images" / "menu.ico"

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        icon_line = f"$s.IconLocation = {ps_quote(str(icon) + ',0')}\n" if icon.is_file() else ""
        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(chr(34) + str(script) + chr(34))}\n"
            f"$s.WorkingDirectory = {ps_quote(str(ROOT))}\n"
            "$s.WindowStyle = 1\n"
            "$s.Description = 'AUTO PLAY'\n"
            f"{icon_line}"
            "$s.Save()\n"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", command],
                check=False,
                capture_output=True,
                text=True,
                creationflags=flags,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "アイコンを作れませんでした", str(exc))
            return
        if result.returncode != 0 or not lnk.exists():
            err = (result.stderr or result.stdout or "ショートカットを作れませんでした").strip()
            QMessageBox.critical(self, "アイコンを作れませんでした", err)
            return
        QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{lnk}")

    def _set_model_update(self, available: bool) -> None:
        if self._update_button is None:
            return
        self._update_button.setText("更新あり" if available else "更新なし")

    def _fill_center(self, slot: QFrame) -> None:
        self._center_slot = slot
        outer = QVBoxLayout(slot)
        outer.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        labels = {(0, 2): "オートプレイ"}
        number = 1
        for row in range(2):
            for col in range(3):
                button = QPushButton(labels.get((row, col), str(number)))
                number += 1
                button.setSizePolicy(
                    QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
                )
                self._center_buttons.append(button)
                grid.addWidget(button, row, col)
        self._launch_button = QPushButton("起動アイコンをデスクトップに作成")
        self._launch_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._launch_button.clicked.connect(self._create_desktop_shortcut)
        self._center_buttons.append(self._launch_button)
        grid.addWidget(self._launch_button, 2, 0, 1, 3)
        self._center_input = QComboBox()
        self._center_input.setEditable(True)
        self._center_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._center_input.addItems([str(value) for value in range(1, 101)])
        self._center_input.addItem("∞")
        field = self._center_input.lineEdit()
        field.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]*")))
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._center_input.setCurrentIndex(0)
        self._center_input.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        grid.addWidget(self._center_input, 0, 3)
        outer.addStretch(1)
        outer.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)

    def _fit_center(self) -> None:
        slot = self._center_slot
        if slot is None:
            return
        rect = slot.contentsRect()
        width = rect.width() // 8
        height = rect.height() // 8
        if width < 1 or height < 1:
            return
        for button in self._center_buttons:
            if self._launch_button is not None and button is self._launch_button:
                button.setFixedSize(width * 3, height)
            else:
                button.setFixedSize(width, height)
        if self._center_input is not None:
            self._center_input.setFixedSize(width, height)
            field = self._center_input.lineEdit()
            if field is not None:
                field.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _section_title(self, text: str) -> QLabel:
        title = QLabel(text)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(TITLE_POINT)
        title.setFont(title_font)
        title.setContentsMargins(0, TITLE_MARGIN, 0, TITLE_MARGIN)
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        return title

    def _fit_items(self) -> None:
        box = self._item_box
        if box is None:
            return
        rect = box.contentsRect()
        if rect.width() <= 1 or rect.height() <= 1:
            return
        side = min(rect.width() // 4, rect.height() // 2) * 9 // 16
        if side < 1:
            return
        gap = max(0, round(side * 4 / 64))
        for row in self._item_rows:
            row.setSpacing(gap)
        if self._item_block is not None:
            self._item_block.setSpacing(gap)
        for label, src in zip(self._item_labels, self._item_src):
            if src.isNull():
                label.clear()
                continue
            scaled = src.scaled(
                side,
                side,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(scaled)
            label.setFixedSize(scaled.size())

    def _set_front(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()


def _local_model() -> Path:
    bundled = WORKSHOP / "tsumtsum-screen-recognition" / "data" / "extractor" / "scene.pt"
    if bundled.is_file():
        return bundled
    return WORKSHOP / "video-frame-extractor" / "scene.pt"


def _file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _model_token() -> str:
    stored = str(QSettings("workshop", "WorkshopDataServer").value("api_token", "") or "").strip()
    return stored


def model_update_available() -> bool:
    local = _local_model()
    local_sha = _file_sha1(local) if local.is_file() else ""
    query = urllib.parse.urlencode({"action": "manifest"})
    request = urllib.request.Request(
        f"{MODELS_API}?{query}",
        headers={"X-Workshop-Token": _model_token()},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return False
    if not isinstance(payload, dict) or not payload.get("ok"):
        return False
    remote_sha = ""
    for item in payload.get("files") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("path") or "") == local.name:
            remote_sha = str(item.get("sha1") or "")
            break
    return bool(remote_sha) and remote_sha != local_sha


class _ModelUpdateCheck(QThread):
    found = Signal(bool)

    def run(self) -> None:
        self.found.emit(model_update_available())


def main() -> None:
    app = QApplication(sys.argv)
    window = MenuWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
