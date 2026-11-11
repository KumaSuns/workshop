from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.marks import play_mark, start_text
from app.prep import read_prep
from app.session import MirrorSession

APP_ROOT = Path(__file__).resolve().parent.parent
WORKSHOP = APP_ROOT.parent
ICON_DIR = WORKSHOP / "video-frame-extractor" / "app" / "assets" / "icons"
ICON_FILES = ("Score.png", "Coin.png", "Exp.png", "Time.png", "Bomb.png", "5over4.png", "Combo.png")
LAMPS = ("ゲーム開始", "SKILL", "FEVER", "TIME UP")
LAMP_ON = (
    QColor(48, 196, 96),
    QColor(255, 196, 40),
    QColor(255, 120, 32),
    QColor(214, 22, 36),
)
ROWS = ("COIN", "RESULT COIN", "倍率", "コイン利益")
BG = QColor(8, 12, 22)
EDGE = QColor(80, 255, 214)
TEXT = QColor(20, 24, 32)


def _pixel_font(name: str, pixels: int) -> QFont:
    font = QFont(name)
    font.setPixelSize(pixels)
    font.setBold(True)
    return font


def _flat_button(text: str, font: QFont) -> QPushButton:
    button = QPushButton(text)
    button.setFont(font)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        "QPushButton { background: #102830; color: #BEFFEC; border: 1px solid #50FFD6; }"
        "QPushButton:hover { background: #184048; }"
        "QPushButton:pressed { background: #0C1C24; }"
    )
    return button


class ToolsPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(480)
        self.setAutoFillBackground(True)
        button_font = _pixel_font("Bahnschrift", 13)
        watch_font = _pixel_font("Yu Gothic UI", 14)
        self.copy_button = _flat_button("画像をコピー", button_font)
        self.copy_button.setGeometry(12, 12, 160, 36)
        self.watch_button = QPushButton("解析オン")
        self.watch_button.setFont(watch_font)
        self.watch_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.watch_button.setGeometry(180, 12, 120, 36)
        self.start_frame = QLabel("")
        self.start_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start_frame.setFont(_pixel_font("Yu Gothic UI", 18))
        self.start_frame.setGeometry(12, 60, 456, 64)
        self.start_frame.setStyleSheet("background: white; color: #141820; border: 1px solid #50FFD6;")
        self.prep = PrepBoard()
        self.prep.setGeometry(12, 136, 456, 112)
        self.play_frame = QLabel("")
        self.play_frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.play_frame.setFont(_pixel_font("Yu Gothic UI", 28))
        self.play_frame.setGeometry(12, 260, 456, 72)
        self.play_frame.setStyleSheet("background: white; color: #141820; border: 1px solid #50FFD6;")
        self.play_column = PlayColumn()
        self.play_column.setGeometry(12, 344, 456, 296)
        for child in (
            self.copy_button,
            self.watch_button,
            self.start_frame,
            self.prep,
            self.play_frame,
            self.play_column,
        ):
            child.setParent(self)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BG)
        painter.setPen(QPen(EDGE))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)


class PrepBoard(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._tsum = ""
        self._on = [False] * len(ICON_FILES)
        self._bright: list[QPixmap | None] = []
        self._dim: list[QPixmap | None] = []
        for name in ICON_FILES:
            path = ICON_DIR / name
            if not path.is_file():
                self._bright.append(None)
                self._dim.append(None)
                continue
            image = QImage(str(path))
            self._bright.append(QPixmap.fromImage(image))
            self._dim.append(QPixmap.fromImage(_fade(image)))
        self._font = _pixel_font("Yu Gothic UI", 18)

    def show_prep(self, tsum: str, items: list[bool]) -> None:
        changed = tsum != self._tsum
        self._tsum = tsum
        for index in range(len(self._on)):
            nxt = index < len(items) and items[index]
            if nxt != self._on[index]:
                self._on[index] = nxt
                changed = True
        if changed:
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        painter.setPen(QPen(EDGE))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        if self._tsum:
            painter.setPen(TEXT)
            painter.setFont(self._font)
            painter.drawText(12, 6, max(1, self.width() - 24), 28, int(Qt.AlignmentFlag.AlignVCenter), "使用ツム  " + self._tsum)
        count = len(ICON_FILES)
        icon = 56
        gap = 6
        row_width = count * icon + (count - 1) * gap
        x = max(8, (self.width() - row_width) // 2)
        y = 40
        for index in range(count):
            pixmap = self._bright[index] if self._on[index] else self._dim[index]
            if pixmap is not None and not pixmap.isNull():
                painter.drawPixmap(x, y, icon, icon, pixmap)
            if self._on[index]:
                painter.setPen(QPen(QColor(255, 196, 40), 3))
                painter.drawRect(x + 1, y + 1, icon - 3, icon - 3)
            x += icon + gap


class PlayColumn(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._on = [False, False, False, False]
        self._values = ["", "", "", ""]
        self._font = _pixel_font("Yu Gothic UI", 16)

    def set_lamps(self, start: bool, skill: bool, fever: bool, time_up: bool) -> None:
        nxt = [start, skill, fever, time_up]
        if nxt != self._on:
            self._on = nxt
            self.update()

    def set_money(self, coin: str, result: str, rate: str, profit: str) -> None:
        nxt = [coin, result, rate, profit]
        if nxt != self._values:
            self._values = nxt
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("white"))
        painter.setPen(QPen(EDGE))
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)
        painter.setFont(self._font)
        lamp = 14
        row_h = 36
        for index, name in enumerate(LAMPS):
            y = index * row_h
            circle_y = y + (row_h - lamp) // 2
            if self._on[index]:
                painter.setBrush(LAMP_ON[index])
                painter.setPen(Qt.PenStyle.NoPen)
            else:
                painter.setBrush(QColor(214, 218, 224))
                painter.setPen(QPen(QColor(160, 166, 174)))
            painter.drawEllipse(16, circle_y, lamp, lamp)
            painter.setPen(TEXT)
            painter.drawText(16 + lamp + 10, y, max(1, self.width() - 48), row_h, int(Qt.AlignmentFlag.AlignVCenter), name)
        top = len(LAMPS) * row_h + 8
        label_width = max(1, int(self.width() * 0.46))
        for index, name in enumerate(ROWS):
            y = top + index * row_h
            painter.drawText(16, y, label_width, row_h, int(Qt.AlignmentFlag.AlignVCenter), name)
            painter.drawText(
                label_width,
                y,
                max(1, self.width() - label_width - 16),
                row_h,
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                self._values[index],
            )


class VolumePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(104)
        self.volume = 100
        self.muted = False
        self._caption = _pixel_font("Bahnschrift", 13)
        self._number = _pixel_font("Bahnschrift", 28)
        self._mute_font = _pixel_font("Bahnschrift", 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._changed = None

    def restore(self, volume: int, muted: bool) -> None:
        self.volume = max(0, min(100, volume))
        self.muted = muted
        self.update()
        self._notify()

    def on_change(self, callback) -> None:
        self._changed = callback

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), BG)
        painter.setPen(QPen(QColor(80, 255, 214, 70), 2))
        painter.drawRect(1, 1, self.width() - 3, self.height() - 3)
        accent = QColor(255, 84, 112) if self.muted else EDGE
        painter.setPen(accent)
        painter.setFont(self._caption)
        painter.drawText(0, 14, self.width(), 20, int(Qt.AlignmentFlag.AlignCenter), "音量")
        painter.setPen(QColor(255, 140, 156) if self.muted else QColor("white"))
        painter.setFont(self._number)
        painter.drawText(0, 36, self.width(), 34, int(Qt.AlignmentFlag.AlignCenter), "--" if self.muted else str(self.volume))
        self._draw_meter(painter)
        self._draw_mute(painter)

    def _meter(self) -> tuple[int, int, int, int]:
        top = 78
        bottom = self.height() - 86
        return (30, top, self.width() - 60, max(40, bottom - top))

    def _mute_rect(self) -> tuple[int, int, int, int]:
        return (10, self.height() - 72, self.width() - 20, 56)

    def _draw_meter(self, painter: QPainter) -> None:
        x, top, width, height = self._meter()
        blocks = 12
        gap = 4
        block = max(6, (height - gap * (blocks - 1)) // blocks)
        bottom = top + height
        lit = 0 if self.muted else int(round(self.volume / 100 * blocks))
        for index in range(blocks):
            y = bottom - (index + 1) * block - index * gap
            color = _block_color(index) if index < lit else QColor(26, 34, 52)
            painter.fillRect(x, y, width, block, color)

    def _draw_mute(self, painter: QPainter) -> None:
        x, y, width, height = self._mute_rect()
        fill = QColor(186, 32, 64) if self.muted else QColor(16, 40, 48)
        line = QColor(255, 120, 140) if self.muted else EDGE
        painter.fillRect(x, y, width, height, fill)
        painter.setPen(QPen(line, 2))
        painter.drawRect(x, y, width, height)
        painter.setPen(QColor("white"))
        painter.setFont(self._mute_font)
        painter.drawText(x, y, width, height, int(Qt.AlignmentFlag.AlignCenter), "消音中" if self.muted else "消音")

    def mousePressEvent(self, event) -> None:
        point = event.position().toPoint()
        x, y, width, height = self._mute_rect()
        if x <= point.x() <= x + width and y <= point.y() <= y + height:
            self.muted = not self.muted
            self.update()
            self._notify()
            return
        mx, my, mwidth, mheight = self._meter()
        if mx <= point.x() <= mx + mwidth and my <= point.y() <= my + mheight:
            self._set_from_meter(point.y())

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        point = event.position().toPoint()
        x, y, width, height = self._mute_rect()
        if x <= point.x() <= x + width and y <= point.y() <= y + height:
            return
        self._set_from_meter(point.y())

    def _set_from_meter(self, y: int) -> None:
        _x, top, _width, height = self._meter()
        ratio = (top + height - y) / max(1, height)
        nxt = max(0, min(100, int(round(ratio * 100))))
        if nxt == self.volume:
            return
        self.volume = nxt
        self.update()
        self._notify()

    def _notify(self) -> None:
        if self._changed is not None:
            self._changed(self.volume, self.muted)


class _MarkBridge(QObject):
    done = Signal(object)


class FrameView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._image = QImage()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAutoFillBackground(False)

    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BG)
        if self._image.isNull():
            return
        target = self.size()
        if target.width() < 2 or target.height() < 2:
            return
        scaled = self._image.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (target.width() - scaled.width()) // 2
        y = (target.height() - scaled.height()) // 2
        painter.drawImage(x, y, scaled)


class PcmOut:
    def __init__(self) -> None:
        self._sink = None
        self._io = None
        self._rate = 0
        self._channels = 0
        self._volume = 1.0

    def set_output(self, volume: int, muted: bool) -> None:
        self._volume = 0.0 if muted else max(0.0, min(1.0, volume / 100))
        if self._sink is not None:
            self._sink.setVolume(self._volume)

    def play(self, payload: bytes) -> None:
        if len(payload) < 8:
            return
        rate = int.from_bytes(payload[0:4], "big")
        channels = int.from_bytes(payload[4:6], "big")
        bits = int.from_bytes(payload[6:8], "big")
        if bits != 16 or rate < 8000 or rate > 192000 or channels not in (1, 2):
            return
        pcm = payload[8:]
        if not pcm:
            return
        try:
            self._submit(pcm, rate, channels)
        except Exception:
            self._sink = None
            self._io = None
            self._rate = 0

    def _submit(self, pcm: bytes, rate: int, channels: int) -> None:
        if self._sink is None or self._rate != rate or self._channels != channels:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

            fmt = QAudioFormat()
            fmt.setSampleRate(rate)
            fmt.setChannelCount(channels)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            device = QMediaDevices.defaultAudioOutput()
            self._sink = QAudioSink(device, fmt)
            self._sink.setVolume(self._volume)
            self._io = self._sink.start()
            self._rate = rate
            self._channels = channels
        if self._io is not None:
            self._io.write(pcm)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ミラー")
        self.resize(960 + 480 + 104, 540)
        self._placed = False
        self._image = QImage()
        self._applied_aspect = 0.0
        self._watch = True
        self._play_timing = False
        self._play_seen = ""
        self._play_seen_count = 0
        self._play_ms = 0
        self._play_running = False
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        stage = QWidget()
        stage.setStyleSheet("background: #080C16;")
        column = QVBoxLayout(stage)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self._picture = FrameView()
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet("background: #080C16;")
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(0, 4, 8, 4)
        self._status = QLabel("待っています")
        self._status.setFont(_pixel_font("Bahnschrift", 13))
        self._status.setStyleSheet("color: #BEFFEC; background: #080C16; padding-left: 12px;")
        self._shortcut = _flat_button("起動アイコンを作る", _pixel_font("Bahnschrift", 13))
        self._shortcut.setFixedWidth(168)
        self._shortcut.clicked.connect(self._create_launch_shortcut)
        bar_row.addWidget(self._status, 1)
        bar_row.addWidget(self._shortcut)
        column.addWidget(self._picture, 1)
        column.addWidget(bar)
        self._tools = ToolsPanel()
        self._side = VolumePanel()
        row.addWidget(stage, 1)
        row.addWidget(self._tools)
        row.addWidget(self._side)
        self.setCentralWidget(root)
        self._tools.copy_button.clicked.connect(self._copy_image)
        self._tools.watch_button.clicked.connect(self._toggle_watch)
        self._apply_watch_button()
        self._audio = PcmOut()
        self._side.on_change(self._on_volume)
        volume, muted = _load_volume()
        self._side.restore(volume, muted)
        self._status.setText("待っています  " + "  ".join(_status_addresses()))
        self._clock = QTimer(self)
        self._clock.setInterval(100)
        self._clock.timeout.connect(self._tick_play)
        self._clock.start()
        self._tick_base = 0
        self._session = MirrorSession()
        self._session.status.connect(self._status.setText)
        self._session.ready.connect(self._on_frame)
        self._session.pcm.connect(self._audio.play)
        self._mark_bridge = _MarkBridge()
        self._mark_bridge.done.connect(self._apply_mark)
        self._held_prep = False
        self._held_tsum = ""
        self._held_on = [False] * 7
        self._mark_lock = threading.Lock()
        self._mark_image = QImage()
        self._mark_busy = False
        self._dns: subprocess.Popen[bytes] | None = None
        self._dns_timer = QTimer(self)
        self._dns_timer.setInterval(2000)
        self._dns_timer.timeout.connect(self._start_dns)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._placed:
            return
        self._placed = True
        QTimer.singleShot(0, self._place)
        self._session.start()
        self._start_dns()
        self._dns_timer.start()

    def closeEvent(self, event) -> None:
        self._session.stop()
        self._session.wait(1500)
        if self._dns is not None:
            self._dns.terminate()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._picture.set_image(self._image)

    def _place(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        chrome_h = max(0, frame.height() - self.height())
        self.resize(self.width(), max(1, area.height() - chrome_h))
        frame = self.frameGeometry()
        x = frame.left()
        if x < area.left():
            x = area.left()
        if x > area.right() - frame.width():
            x = max(area.left(), area.right() - frame.width())
        self.move(x, area.top())

    def _start_dns(self) -> None:
        if self._dns is not None and self._dns.poll() is None:
            return
        try:
            self._dns = subprocess.Popen(
                ["dns-sd", "-R", "このPC", "_mirrdev._tcp", "local", "47777"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._dns = None

    def _on_volume(self, volume: int, muted: bool) -> None:
        self._audio.set_output(volume, muted)
        _save_volume(volume, muted)

    def _toggle_watch(self) -> None:
        self._watch = not self._watch
        if self._play_timing:
            if self._watch:
                self._play_running = True
                self._tick_base = self._clock_now() - self._play_ms
            else:
                self._play_running = False
        self._apply_watch_button()

    def _apply_watch_button(self) -> None:
        button = self._tools.watch_button
        if self._watch:
            button.setText("解析オン")
            button.setStyleSheet(
                "QPushButton { background: #C42028; color: white; border: 1px solid #FFA0A0; }"
                "QPushButton:hover { background: #DC3038; }"
                "QPushButton:pressed { background: #96141C; }"
            )
            return
        button.setText("解析オフ")
        button.setStyleSheet(
            "QPushButton { background: #2058C4; color: white; border: 1px solid #A0C4FF; }"
            "QPushButton:hover { background: #3070DC; }"
            "QPushButton:pressed { background: #143C96; }"
        )

    def _on_frame(self) -> None:
        while True:
            payload = self._session.take_frame()
            if payload is None:
                return
            image = QImage.fromData(payload)
            if image.isNull():
                self._status.setText("映像を表示できません")
                continue
            self._image = image
            self._status.setText("受信中")
            self._fit_window(image)
            self._picture.set_image(image)
            if self._watch:
                self._submit_mark(image.copy())

    def _submit_mark(self, image: QImage) -> None:
        with self._mark_lock:
            self._mark_image = image
            if self._mark_busy:
                return
            self._mark_busy = True
        threading.Thread(target=self._mark_loop, daemon=True).start()

    def _mark_loop(self) -> None:
        while True:
            with self._mark_lock:
                image = self._mark_image
                self._mark_image = QImage()
                if image.isNull():
                    self._mark_busy = False
                    return
            try:
                text = start_text(image)
                mark = play_mark(image)
                is_prep, tsum, items = read_prep(image)
            except Exception:
                text, mark, is_prep, tsum, items = "", "", False, "", [False] * 7
            self._mark_bridge.done.emit((text, mark, is_prep, tsum, items))

    def _apply_mark(self, result: object) -> None:
        text, mark, is_prep, tsum, items = result
        self._tools.start_frame.setText(text)
        hold = self._play_timing or mark == "go"
        if hold:
            if self._held_prep:
                self._tools.prep.show_prep(self._held_tsum, self._held_on)
        elif is_prep:
            self._held_tsum = tsum
            self._held_on = list(items)
            self._held_prep = True
            self._tools.prep.show_prep(self._held_tsum, self._held_on)
        elif self._held_prep:
            self._tools.prep.show_prep(self._held_tsum, self._held_on)
        self._note_play(mark)
        self._tools.play_column.set_lamps(
            (mark == "go" or self._play_timing) and mark != "timeup",
            False,
            False,
            mark == "timeup",
        )

    def _note_play(self, mark: str) -> None:
        if not mark:
            self._play_seen = ""
            self._play_seen_count = 0
            return
        if mark == self._play_seen:
            self._play_seen_count += 1
        else:
            self._play_seen = mark
            self._play_seen_count = 1
        if self._play_seen_count < 2:
            return
        if mark == "go" and not self._play_timing:
            self._play_ms = 0
            self._tick_base = self._clock_now()
            self._play_timing = True
            self._play_running = True
            self._show_play_time()
            return
        if mark == "timeup" and self._play_timing:
            self._play_running = False
            self._play_timing = False
            self._show_play_time()

    def _tick_play(self) -> None:
        if self._play_timing and self._play_running:
            self._play_ms = self._clock_now() - self._tick_base
            self._show_play_time()

    def _show_play_time(self) -> None:
        elapsed = max(0, self._play_ms)
        minutes = elapsed // 60000
        seconds = (elapsed // 1000) % 60
        tenth = (elapsed % 1000) // 100
        self._tools.play_frame.setText(f"{minutes}:{seconds:02d}.{tenth}")

    def _clock_now(self) -> int:
        from time import monotonic

        return int(monotonic() * 1000)

    def _fit_window(self, image: QImage) -> None:
        if self.isMaximized() or image.width() < 2 or image.height() < 2:
            return
        aspect = image.width() / image.height()
        if abs(aspect - self._applied_aspect) <= 0.02:
            return
        self._applied_aspect = aspect
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        max_width = min(image.width(), int(area.width() * 0.72))
        max_height = min(image.height(), int(area.height() * 0.86) - 40)
        picture_width = max_width
        picture_height = int(round(picture_width / aspect))
        if picture_height > max_height:
            picture_height = max(1, max_height)
            picture_width = max(1, int(round(picture_height * aspect)))
        frame = self.frameGeometry()
        extra_w = max(0, frame.width() - self.width())
        extra_h = max(0, frame.height() - self.height())
        client_w = picture_width + 480 + 104
        client_h = picture_height + 40
        center_x = frame.left() + frame.width() // 2
        center_y = frame.top() + frame.height() // 2
        self.resize(client_w, client_h)
        frame = self.frameGeometry()
        x = center_x - (client_w + extra_w) // 2
        y = center_y - (client_h + extra_h) // 2
        x = min(max(x, area.left()), max(area.left(), area.right() - frame.width()))
        y = min(max(y, area.top()), max(area.top(), area.bottom() - frame.height()))
        self.move(x, y)

    def _copy_image(self) -> None:
        if self._image.isNull():
            self._status.setText("コピーする画像がありません")
            return
        QApplication.clipboard().setImage(self._image)
        self._status.setText("画像をコピーしました")

    def _create_launch_shortcut(self) -> None:
        desktop = Path.home() / "Desktop"
        if not desktop.is_dir():
            self._status.setText("起動アイコンを作れませんでした")
            return
        if sys.platform == "darwin":
            self._create_macos_shortcut(desktop)
            return
        self._create_windows_shortcut(desktop)

    def _create_windows_shortcut(self, desktop: Path) -> None:
        lnk = desktop / "ミラー.lnk"
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        script = APP_ROOT / "main.py"

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(chr(34) + str(script) + chr(34))}\n"
            f"$s.WorkingDirectory = {ps_quote(str(APP_ROOT))}\n"
            "$s.WindowStyle = 1\n"
            "$s.Description = 'iPhone の画面をこのPCに出す'\n"
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
        except OSError as exc:
            self._status.setText("起動アイコンを作れませんでした。 " + str(exc))
            return
        if result.returncode != 0 or not lnk.exists():
            err = (result.stderr or result.stdout or "起動アイコンを作れませんでした").strip()
            self._status.setText("起動アイコンを作れませんでした。 " + err)
            return
        self._status.setText("デスクトップに「ミラー」を作りました")

    def _create_macos_shortcut(self, desktop: Path) -> None:
        app_path = desktop / "ミラー.app"
        contents = app_path / "Contents"
        macos_dir = contents / "MacOS"
        try:
            if app_path.exists():
                shutil.rmtree(app_path)
            macos_dir.mkdir(parents=True, exist_ok=True)
            launcher = macos_dir / "launch"
            launcher.write_text(
                "#!/bin/bash\n"
                f'cd "{APP_ROOT}"\n'
                f'exec "{sys.executable}" "{APP_ROOT / "main.py"}"\n',
                encoding="utf-8",
            )
            launcher.chmod(0o755)
            (contents / "Info.plist").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>workshop.mirror</string>
  <key>CFBundleName</key><string>ミラー</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
""",
                encoding="utf-8",
            )
        except OSError as exc:
            self._status.setText("起動アイコンを作れませんでした。 " + str(exc))
            return
        self._status.setText("デスクトップに「ミラー」を作りました")


def _volume_path() -> Path:
    if sys.platform == "win32":
        base = Path.home() / "AppData" / "Local"
    else:
        base = Path.home() / "Library" / "Application Support"
    return base / "MirrorDisplay" / "volume.txt"


def _load_volume() -> tuple[int, bool]:
    try:
        lines = _volume_path().read_text(encoding="utf-8").splitlines()
        volume = int(lines[0])
        muted = len(lines) > 1 and lines[1] == "1"
        return (max(0, min(100, volume)), muted)
    except (OSError, ValueError, IndexError):
        return (100, False)


def _save_volume(volume: int, muted: bool) -> None:
    path = _volume_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{volume}\n{'1' if muted else '0'}\n", encoding="utf-8")
    except OSError:
        pass


def _status_addresses() -> list[str]:
    from app.session import lan_addresses

    return lan_addresses()


def _fade(image: QImage) -> QImage:
    faded = image.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(faded.height()):
        for x in range(faded.width()):
            pixel = faded.pixel(x, y)
            alpha = (pixel >> 24) & 255
            red = min(255, int(((pixel >> 16) & 255) * 0.35 + 158))
            green = min(255, int(((pixel >> 8) & 255) * 0.35 + 158))
            blue = min(255, int((pixel & 255) * 0.35 + 158))
            faded.setPixel(x, y, (alpha << 24) | (red << 16) | (green << 8) | blue)
    return faded


def _block_color(index: int) -> QColor:
    ratio = index / 11
    red = int(80 + (255 - 80) * ratio)
    green = int(255 + (70 - 255) * ratio)
    blue = int(214 + (170 - 214) * ratio)
    return QColor(red, green, blue)
