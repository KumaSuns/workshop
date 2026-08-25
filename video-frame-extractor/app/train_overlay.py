from __future__ import annotations

import math

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

CPU_RGB = (40, 255, 96)
GPU_RGB = (255, 36, 48)


def soft_glow(now: float) -> float:
    breath = 0.5 + 0.5 * math.sin(now * 1.55)
    swell = 0.5 + 0.5 * math.sin(now * 0.62 + 0.8)
    return 0.42 + 0.36 * breath + 0.18 * swell


def apply_device_glow(cpu: "GlowBadge", gpu: "GlowBadge", active: str | None, intensity: float) -> None:
    if active == "gpu":
        cpu.set_idle()
        gpu.set_glow(intensity)
    elif active == "cpu":
        gpu.set_idle()
        cpu.set_glow(intensity)
    else:
        cpu.set_idle()
        gpu.set_idle()


class GlowBadge(QWidget):
    def __init__(
        self,
        text: str,
        rgb: tuple[int, int, int],
        parent=None,
        *,
        px: int = 16,
        bg: tuple[int, int, int] = (28, 32, 40),
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._rgb = rgb
        self._bg = bg
        self._px = px
        self._active = False
        self._intensity = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(self.sizeHint())

    def sizeHint(self) -> QSize:
        return QSize(int(self._px * 5.2), int(self._px * 3.6))

    def set_idle(self) -> None:
        if not self._active and self._intensity == 0:
            return
        self._active = False
        self._intensity = 0.0
        self.update()

    def set_glow(self, intensity: float) -> None:
        self._active = True
        self._intensity = max(0.0, min(1.0, intensity))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(*self._bg))
        r, g, b = self._rgb
        if self._active:
            center = rect.center()
            radius = min(rect.width(), rect.height()) * (0.30 + 0.22 * self._intensity)
            gradient = QRadialGradient(float(center.x()), float(center.y()), radius)
            core = int(80 + 120 * self._intensity)
            gradient.setColorAt(0.0, QColor(r, g, b, core))
            gradient.setColorAt(0.42, QColor(r, g, b, int(core * 0.38)))
            gradient.setColorAt(1.0, QColor(r, g, b, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawEllipse(center, int(radius), int(radius))
            mix = 0.58 + 0.42 * self._intensity
            painter.setPen(
                QColor(
                    min(255, int(r * mix + 40 * self._intensity)),
                    min(255, int(g * mix + 40 * self._intensity)),
                    min(255, int(b * mix + 40 * self._intensity)),
                )
            )
        else:
            painter.setPen(QColor(int(r * 0.5), int(g * 0.5), int(b * 0.5)))
        font = QFont("Consolas")
        font.setPixelSize(self._px)
        font.setBold(True)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)


class TrainOverlay(QFrame):
    cancelRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("trainOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setStyleSheet(
            """
            QFrame#trainOverlay {
                background: #0c0e12;
                border: none;
            }
            QLabel#trainTitle {
                color: #f2f5f8;
                font-size: 28px;
                font-weight: 700;
            }
            QLabel#trainDetail {
                color: #d7dde6;
                font-size: 16px;
            }
            QProgressBar {
                background: #101216;
                border: 1px solid #3a4250;
                border-radius: 8px;
                text-align: center;
                color: #e8eaed;
                min-height: 22px;
                font-size: 13px;
            }
            QProgressBar::chunk { background: #5b6cff; border-radius: 8px; }
            QPushButton#trainCancel {
                background: #c23b4a;
                color: #f2f5f8;
                font-size: 16px;
                font-weight: 700;
                border: none;
                border-radius: 10px;
                padding: 10px 28px;
                min-width: 140px;
            }
            QPushButton#trainCancel:hover { background: #e04b5c; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch(1)
        self.title = QLabel("学習中です")
        self.title.setObjectName("trainTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        device_row = QHBoxLayout()
        device_row.setSpacing(40)
        self.cpu_badge = GlowBadge("CPU", CPU_RGB, px=34, bg=(12, 14, 18))
        self.gpu_badge = GlowBadge("GPU", GPU_RGB, px=34, bg=(12, 14, 18))
        device_row.addStretch(1)
        device_row.addWidget(self.cpu_badge)
        device_row.addWidget(self.gpu_badge)
        device_row.addStretch(1)
        layout.addLayout(device_row)
        self.detail = QLabel("画像を読んでいます…")
        self.detail.setObjectName("trainDetail")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        self.cancel_btn = QPushButton("中止")
        self.cancel_btn.setObjectName("trainCancel")
        self.cancel_btn.clicked.connect(self.cancelRequested.emit)
        layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        self.hide()

    def start(self) -> None:
        self.title.setText("学習中です")
        self.detail.setText("画像を読んでいます…")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("中止")
        self._place()
        self.show()
        self.raise_()

    def set_progress(self, current: int, total: int, message: str) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(current)
        self.detail.setText(message)

    def set_cancelling(self) -> None:
        self.title.setText("中止しています")
        self.detail.setText("この epoch が終わるまで待っています…")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("中止しています…")

    def stop(self) -> None:
        apply_device_glow(self.cpu_badge, self.gpu_badge, None, 0.0)
        self.hide()

    def set_device_glow(self, active: str | None, intensity: float) -> None:
        if not self.isVisible():
            return
        apply_device_glow(self.cpu_badge, self.gpu_badge, active, intensity)

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        central = parent.centralWidget() if hasattr(parent, "centralWidget") else None
        if central is not None:
            self.setGeometry(central.geometry())
        else:
            self.setGeometry(parent.rect())
