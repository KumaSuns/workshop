from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QWidget

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
    "がんばるぞ〜",
    "スコアより学習が大事",
    "コンボより正解が大事",
]

BUBBLES = [
    "おぼえた！",
    "ここだよ",
    "むずかしい…",
    "がんばれ",
    "フィーバー！",
    "〇つけた",
    "ボムだ！",
    "わかった",
    "もういっちょ",
    "できた！",
    "みてみて",
    "つむっ",
]


class TrainEffect(QWidget):
    cancelRequested = Signal()

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
        self._cancel_btn = QPushButton("中止", self)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.setStyleSheet(
            "QPushButton { background: #c23b4a; color: #f2f5f8; font-size: 16px; font-weight: 700; "
            "border: none; border-radius: 10px; padding: 8px 22px; min-width: 120px; min-height: 40px; }"
            "QPushButton:hover { background: #e04b5c; }"
            "QPushButton:disabled { background: #5a3a40; color: #c5cad3; }"
        )
        self._cancel_btn.clicked.connect(self.cancelRequested.emit)
        self._title = QLabel("学習中です", self)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("color: #ffe066; font-size: 32px; font-weight: 800; background: transparent;")
        self._detail = QLabel("準備しています…", self)
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #f2f5f8; font-size: 18px; background: transparent;")
        self._bar = QProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFormat("%p%")
        self._bar.setStyleSheet(
            "QProgressBar { background: #101216; border: 1px solid #3a4250; border-radius: 8px; "
            "text-align: center; color: #e8eaed; min-height: 22px; font-size: 14px; }"
            "QProgressBar::chunk { background: #ffe066; border-radius: 8px; }"
        )

    def start(self) -> None:
        host = self.parentWidget()
        if host is not None:
            self.setGeometry(0, 0, host.width(), host.height())
        self._blobs = []
        self._sparkles = []
        self._tick_n = 0
        self._progress = 0.0
        self._status = "学習中です"
        self._quip = random.choice(QUIPS)
        self._title.setText("学習中です")
        self._detail.setText(self._quip)
        self._bar.setValue(0)
        self._spawn_blobs()
        self._cancel_btn.setEnabled(True)
        self._cancel_btn.setText("中止")
        self.show()
        self.raise_()
        self._place_hud()
        self._cancel_btn.raise_()
        self._title.raise_()
        self._detail.raise_()
        self._bar.raise_()
        self._timer.start(16)

    def stop(self) -> None:
        self._timer.stop()
        self.hide()
        self._blobs = []
        self._sparkles = []

    def set_cancelling(self) -> None:
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("中止しています…")
        self._status = "学習を中止しています"

    def _place_hud(self) -> None:
        width = max(self.width(), 200)
        self._title.setGeometry(24, 24, width - 48, 48)
        self._detail.setGeometry(24, 76, width - 48, 48)
        bar_w = max(240, width - 80)
        bar_x = (width - bar_w) // 2
        bar_y = self.height() - 28 - 22
        self._bar.setGeometry(bar_x, max(120, bar_y), bar_w, 28)
        self._cancel_btn.adjustSize()
        btn_w = max(120, self._cancel_btn.width())
        btn_h = max(40, self._cancel_btn.height())
        self._cancel_btn.setFixedSize(btn_w, btn_h)
        status_h = 24
        gap = 12
        self._cancel_btn.move(
            max(12, (self.width() - btn_w) // 2),
            max(12, self._bar.y() - status_h - gap - btn_h),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_hud()

    def set_progress(self, epoch: int, total: int, message: str) -> None:
        self._progress = epoch / max(1, total)
        self._status = message
        self._bar.setRange(0, max(total, 1))
        self._bar.setValue(epoch)
        self._place_hud()
        self.update()

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
                    "ears": random.choice(["round", "round", "small", "none"]),
                    "bubble": None,
                    "bubble_life": 0,
                }
            )

    def _tick(self) -> None:
        self._tick_n += 1
        self._pulse += 0.08
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        if self._tick_n % 90 == 0:
            self._quip = random.choice(QUIPS)
            self._detail.setText(self._quip)
        talking = sum(1 for blob in self._blobs if blob.get("bubble_life", 0) > 0)
        if self._tick_n % 48 == 0 and talking < 3 and self._blobs:
            quiet = [blob for blob in self._blobs if blob.get("bubble_life", 0) <= 0]
            if quiet:
                speaker = random.choice(quiet)
                speaker["bubble"] = random.choice(BUBBLES)
                speaker["bubble_life"] = random.randint(70, 110)
        for blob in self._blobs:
            if blob.get("bubble_life", 0) > 0:
                blob["bubble_life"] -= 1
                if blob["bubble_life"] <= 0:
                    blob["bubble"] = None
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
            if blob["y"] > height - radius - 56:
                blob["y"] = height - radius - 56
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
        for blob in self._blobs:
            self._draw_blob(painter, blob)
        for blob in self._blobs:
            self._draw_bubble(painter, blob)
        for sparkle in self._sparkles:
            self._draw_sparkle(painter, sparkle)
        self._draw_banner(painter)

    def _draw_blob(self, painter: QPainter, blob: dict) -> None:
        radius = blob["r"]
        squash = blob["squash"]
        cx, cy = blob["x"], blob["y"]
        color = QColor(blob["color"])
        ry = radius * squash
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color.darker(118))
        ears = blob.get("ears", "round")
        if ears != "none":
            ear_r = radius * (0.38 if ears == "round" else 0.26)
            painter.drawEllipse(QPointF(cx - radius * 0.62, cy - ry * 0.72), ear_r, ear_r * 0.95)
            painter.drawEllipse(QPointF(cx + radius * 0.62, cy - ry * 0.72), ear_r, ear_r * 0.95)
        glow = QRadialGradient(QPointF(cx, cy - ry * 0.25), radius * 1.35)
        glow.setColorAt(0.0, color.lighter(135))
        glow.setColorAt(0.5, color)
        glow.setColorAt(1.0, color.darker(120))
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), radius, ry)
        painter.setBrush(QColor(255, 255, 255, 80))
        painter.drawEllipse(QPointF(cx - radius * 0.28, cy - ry * 0.38), radius * 0.28, ry * 0.18)
        blush = QColor(color.red(), 90, 110, 90)
        painter.setBrush(blush)
        painter.drawEllipse(QPointF(cx - radius * 0.38, cy + ry * 0.12), radius * 0.14, ry * 0.08)
        painter.drawEllipse(QPointF(cx + radius * 0.38, cy + ry * 0.12), radius * 0.14, ry * 0.08)
        painter.setBrush(QColor(28, 24, 36))
        eye_y = cy - ry * 0.06
        painter.drawEllipse(QPointF(cx - radius * 0.2, eye_y), 4.2, 5.4)
        painter.drawEllipse(QPointF(cx + radius * 0.2, eye_y), 4.2, 5.4)
        painter.setBrush(QColor(255, 255, 255, 220))
        painter.drawEllipse(QPointF(cx - radius * 0.2 + 1.2, eye_y - 1.4), 1.6, 1.8)
        painter.drawEllipse(QPointF(cx + radius * 0.2 + 1.2, eye_y - 1.4), 1.6, 1.8)
        smile = QPainterPath()
        smile.moveTo(cx - radius * 0.18, cy + ry * 0.2)
        smile.quadTo(
            QPointF(cx, cy + ry * 0.36),
            QPointF(cx + radius * 0.18, cy + ry * 0.2),
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(28, 24, 36), 2.6))
        painter.drawPath(smile)

    def _draw_bubble(self, painter: QPainter, blob: dict) -> None:
        text = blob.get("bubble")
        if not text or blob.get("bubble_life", 0) <= 0:
            return
        painter.setFont(QFont("Yu Gothic UI", 11, QFont.Weight.Bold))
        metrics = painter.fontMetrics()
        tw = metrics.horizontalAdvance(text) + 18
        th = metrics.height() + 10
        cx = blob["x"]
        cy = blob["y"]
        radius = blob["r"] * blob.get("squash", 1.0)
        bx = int(cx - tw / 2)
        by = int(cy - radius - th - 16)
        bx = max(8, min(bx, self.width() - tw - 8))
        by = max(8, by)
        painter.setPen(QPen(QColor(40, 36, 48), 2))
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.drawRoundedRect(bx, by, tw, th, 10, 10)
        tail = QPainterPath()
        tail.moveTo(cx - 7, by + th)
        tail.lineTo(cx, by + th + 9)
        tail.lineTo(cx + 7, by + th)
        painter.drawPath(tail)
        painter.setPen(QColor(40, 36, 48))
        painter.drawText(QRect(bx, by, tw, th), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_sparkle(self, painter: QPainter, sparkle: dict) -> None:
        color = QColor(sparkle["color"])
        color.setAlpha(int(220 * sparkle["life"]))
        size = 3 + 6 * sparkle["life"]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(sparkle["x"], sparkle["y"]), size, size)

    def _draw_banner(self, painter: QPainter) -> None:
        width = self.width()
        bar_y = self._bar.y()
        painter.setPen(QColor(154, 163, 178))
        painter.setFont(QFont("Yu Gothic UI", 12, QFont.Weight.DemiBold))
        painter.drawText(
            0,
            bar_y - 28,
            width,
            24,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._status,
        )
