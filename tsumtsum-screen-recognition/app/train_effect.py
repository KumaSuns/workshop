from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

COLORS = [
    "#FF6B9D",
    "#FFE066",
    "#7C5CFF",
    "#5CFF9E",
    "#FF9F43",
    "#4ECDC4",
    "#FF6B6B",
    "#C77DFF",
    "#5B6CFF",
]

QUIPS = [
    "ツムたちが勉強中…",
    "〇の場所を覚えています",
    "ボムの形もメモ中…",
    "フィーバー！もうちょっと！",
    "つながっても見逃さないぞ",
    "がんばるぞ〜",
    "スコアより学習が大事",
    "コンボより正解が大事",
]


class TrainEffect(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._blobs: list[dict] = []
        self._sparkles: list[dict] = []
        self._tick_n = 0
        self._progress = 0.0
        self._status = "学習中です"
        self._quip = QUIPS[0]
        self._pulse = 0.0

    def start(self) -> None:
        self.setGeometry(self.parentWidget().rect() if self.parentWidget() else self.rect())
        self._blobs = []
        self._sparkles = []
        self._tick_n = 0
        self._progress = 0.0
        self._status = "学習中です"
        self._quip = random.choice(QUIPS)
        self._spawn_blobs()
        self.show()
        self.raise_()
        self._timer.start(16)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()
        self._blobs = []
        self._sparkles = []

    def set_progress(self, epoch: int, total: int, message: str) -> None:
        self._progress = epoch / max(1, total)
        self._status = message

    def _spawn_blobs(self) -> None:
        width = max(self.width(), 200)
        height = max(self.height(), 200)
        count = 14
        for index in range(count):
            radius = random.randint(28, 46)
            lo_x = radius + 10
            hi_x = max(lo_x + 1, width - radius - 10)
            lo_y = radius + 80
            hi_y = max(lo_y + 1, height - radius - 40)
            self._blobs.append(
                {
                    "x": random.uniform(lo_x, hi_x),
                    "y": random.uniform(lo_y, hi_y),
                    "r": radius,
                    "vx": random.uniform(-3.2, 3.2),
                    "vy": random.uniform(-6.0, -1.5),
                    "color": COLORS[index % len(COLORS)],
                    "spin": random.uniform(0, 6.28),
                    "squash": 1.0,
                }
            )

    def _tick(self) -> None:
        self._tick_n += 1
        self._pulse += 0.08
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        if self._tick_n % 90 == 0:
            self._quip = random.choice(QUIPS)
        for blob in self._blobs:
            blob["vy"] += 0.28
            blob["x"] += blob["vx"]
            blob["y"] += blob["vy"]
            blob["spin"] += 0.04
            blob["squash"] += (1.0 - blob["squash"]) * 0.12
            radius = blob["r"]
            if blob["x"] < radius:
                blob["x"] = radius
                blob["vx"] = abs(blob["vx"])
                blob["squash"] = 0.72
            elif blob["x"] > width - radius:
                blob["x"] = width - radius
                blob["vx"] = -abs(blob["vx"])
                blob["squash"] = 0.72
            if blob["y"] > height - radius - 8:
                blob["y"] = height - radius - 8
                blob["vy"] = -random.uniform(8.5, 13.5)
                blob["squash"] = 0.62
                self._burst(blob["x"], blob["y"] + radius * 0.4, blob["color"])
            elif blob["y"] < radius + 8:
                blob["y"] = radius + 8
                blob["vy"] = abs(blob["vy"]) * 0.4
        if random.random() < 0.35:
            blob = random.choice(self._blobs)
            self._sparkles.append(
                {
                    "x": blob["x"] + random.uniform(-blob["r"], blob["r"]),
                    "y": blob["y"] + random.uniform(-blob["r"], blob["r"]),
                    "life": 1.0,
                    "color": blob["color"],
                }
            )
        alive = []
        for sparkle in self._sparkles:
            sparkle["life"] -= 0.035
            sparkle["y"] -= 0.8
            if sparkle["life"] > 0:
                alive.append(sparkle)
        self._sparkles = alive[-80:]
        self.update()

    def _burst(self, x: float, y: float, color: str) -> None:
        for _ in range(6):
            self._sparkles.append(
                {
                    "x": x + random.uniform(-18, 18),
                    "y": y + random.uniform(-10, 6),
                    "life": 1.0,
                    "color": color,
                }
            )

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(10, 12, 18, 210))
        self._draw_links(painter)
        for blob in self._blobs:
            self._draw_blob(painter, blob)
        for sparkle in self._sparkles:
            self._draw_sparkle(painter, sparkle)
        self._draw_banner(painter)

    def _draw_links(self, painter: QPainter) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index, left in enumerate(self._blobs):
            for right in self._blobs[index + 1 :]:
                dx = left["x"] - right["x"]
                dy = left["y"] - right["y"]
                dist = math.hypot(dx, dy)
                if dist > left["r"] + right["r"] + 36:
                    continue
                color = QColor("#7FD9FF")
                color.setAlpha(120)
                painter.setPen(QPen(color, 4))
                painter.drawLine(QPointF(left["x"], left["y"]), QPointF(right["x"], right["y"]))

    def _draw_blob(self, painter: QPainter, blob: dict) -> None:
        radius = blob["r"]
        squash = blob["squash"]
        cx, cy = blob["x"], blob["y"]
        color = QColor(blob["color"])
        glow = QRadialGradient(QPointF(cx, cy - radius * 0.2), radius * 1.4)
        glow.setColorAt(0.0, color.lighter(130))
        glow.setColorAt(0.55, color)
        glow.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 40))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), radius, radius * squash)
        painter.setBrush(QColor(255, 255, 255, 70))
        painter.drawEllipse(QPointF(cx - radius * 0.28, cy - radius * 0.32 * squash), radius * 0.22, radius * 0.16)
        painter.setBrush(QColor(28, 24, 36))
        eye_y = cy - radius * 0.08 * squash
        painter.drawEllipse(QPointF(cx - radius * 0.22, eye_y), 4.5, 5.5)
        painter.drawEllipse(QPointF(cx + radius * 0.22, eye_y), 4.5, 5.5)
        smile = QPainterPath()
        smile.moveTo(cx - radius * 0.22, cy + radius * 0.18 * squash)
        smile.quadTo(
            QPointF(cx, cy + radius * 0.34 * squash),
            QPointF(cx + radius * 0.22, cy + radius * 0.18 * squash),
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(28, 24, 36), 3))
        painter.drawPath(smile)

    def _draw_sparkle(self, painter: QPainter, sparkle: dict) -> None:
        color = QColor(sparkle["color"])
        color.setAlpha(int(220 * sparkle["life"]))
        size = 3 + 6 * sparkle["life"]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(sparkle["x"], sparkle["y"]), size, size)

    def _draw_banner(self, painter: QPainter) -> None:
        width = self.width()
        pulse = 0.5 + 0.5 * math.sin(self._pulse)
        title = QFont("Yu Gothic UI", 28, QFont.Weight.Black)
        painter.setFont(title)
        painter.setPen(QColor(255, 224, 80, int(200 + 55 * pulse)))
        painter.drawText(self.rect().adjusted(0, 28, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "FEVER LEARNING")
        sub = QFont("Yu Gothic UI", 14, QFont.Weight.DemiBold)
        painter.setFont(sub)
        painter.setPen(QColor(242, 245, 248))
        painter.drawText(self.rect().adjusted(0, 74, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._quip)
        painter.setPen(QColor(154, 163, 178))
        painter.drawText(self.rect().adjusted(0, 100, 0, 0), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, self._status)
        bar_w = min(420, width - 80)
        bar_h = 16
        bar_x = (width - bar_w) / 2
        bar_y = 132
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(16, 18, 22, 220))
        painter.drawRoundedRect(int(bar_x), bar_y, bar_w, bar_h, 8, 8)
        fill = max(8, int(bar_w * min(1.0, self._progress)))
        painter.setBrush(QColor("#FFE066"))
        painter.drawRoundedRect(int(bar_x), bar_y, fill, bar_h, 8, 8)
        painter.setPen(QColor("#16181d"))
        painter.setFont(QFont("Yu Gothic UI", 9, QFont.Weight.Bold))
        painter.drawText(
            int(bar_x),
            bar_y,
            bar_w,
            bar_h,
            Qt.AlignmentFlag.AlignCenter,
            f"{int(self._progress * 100)}%",
        )
