from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

LOGO_PATH = Path(__file__).resolve().parent / "images" / "rogo_002.png"


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
        blue.setColor(QPalette.ColorRole.Window, QColor("#2C7CFF"))
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
        header_layout.setContentsMargins(0, 0, 0, 0)
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
        for _ in range(3):
            slot = QFrame()
            slot.setFrameShape(QFrame.Shape.Box)
            layout.addWidget(slot, 1)
            self._slots.append(slot)
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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_logo()

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
        logo_h = max(1, height * 9 // 10)
        scaled = self._logo_src.scaledToHeight(
            logo_h, Qt.TransformationMode.SmoothTransformation
        )
        if scaled.width() > width:
            scaled = self._logo_src.scaledToWidth(
                width, Qt.TransformationMode.SmoothTransformation
            )
        self._logo.setPixmap(scaled)
        self._fitting_logo = False

    def _set_front(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()


def main() -> None:
    app = QApplication(sys.argv)
    window = MenuWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
