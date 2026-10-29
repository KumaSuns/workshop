from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PySide6.QtCore import QDir, QEvent, QLockFile, QRegularExpression, QSettings, QStandardPaths, Qt, QThread, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QImage,
    QKeySequence,
    QPalette,
    QPixmap,
    QRegularExpressionValidator,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

MENU_IPC = "workshop-out-play-menu"
ROOT = Path(__file__).resolve().parent
MODELS_API = "http://hokkai-syabusyabu.com/home_page/workshop/models/api.php"
LOGO_PATH = ROOT / "images" / "rogo_003.png"
ICON_DIR = ROOT / "icons"
TSUM_ICON_DIR = ROOT / "tsum_icons"
TSUM_ICON_LIST_URL = "https://hokkai-syabusyabu.com/home_page/admin/tsumtsum_icon_list.php"
TSUM_ICON_FILE_URL = "https://hokkai-syabusyabu.com/home_page/tsumtsum/icon/"
ITEM_ICONS = (
    "Score.png",
    "Coin.png",
    "Exp.png",
    "Time.png",
    "Bomb.png",
    "5over4.png",
    "Combo.png",
)
ITEM_NAMES = (
    "+Score",
    "+Coin",
    "+Exp",
    "+Time",
    "+Bomb",
    "5＞4",
    "+Combo",
)
ITEM_DIM = 0.6
ITEM_MIST = 0.6
TITLE_POINT = 12
TITLE_MARGIN = 16
FLOW_LAMPS = (
    "システム開始",
    "BLUE STACK 起動確認",
    "使用アイテム確認",
    "ゲーム数確認",
    "画面の確認",
    "モデルの確認",
    "ハートの確認",
    "スタート画面確認",
    "使用ツムの確認",
    "プレイを開始",
    "TIME UP 検知",
    "リザルト検知",
    "システム終了",
)
def _flow_lamp_style(background: str, color: str, border: str) -> str:
    return (
        "QPushButton {"
        f" background: {background};"
        f" color: {color};"
        " font-weight: 700;"
        f" border: 1px solid {border};"
        " border-radius: 6px;"
        " padding: 2px;"
        "}"
    )


SURFACE = "#17233f"
SURFACE_LINE = "#A4C6FF"
SURFACE_INK = "#e8f0ff"


def _plain_surface(widget) -> None:
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(SURFACE_INK))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(SURFACE_INK))
    widget.setAutoFillBackground(True)
    widget.setPalette(palette)


def _soft_box(frame: QFrame) -> None:
    frame.setObjectName("softBox")
    frame.setFrameShape(QFrame.Shape.NoFrame)
    frame.setStyleSheet(
        "QFrame#softBox {"
        " background: #22325a;"
        f" border: 1px solid {SURFACE_LINE};"
        "}"
    )


FLOW_LAMP_OFF = _flow_lamp_style("#22325a", "#e8f0ff", "#A4C6FF")
FLOW_LAMP_ON = _flow_lamp_style("#2c426e", "#f4f8ff", "#A4C6FF")
FLOW_LAMP_BLINK_WHITE = _flow_lamp_style("#ffffff", "#17233f", "#A4C6FF")
FLOW_LAMP_BLINK = _flow_lamp_style("#A4C6FF", "#17233f", "#7eb0f0")


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


def _game_record_parts(item: dict) -> list[tuple[str, bool]]:
    names = item.get("items") or []
    if isinstance(names, str):
        items_text = names
    else:
        items_text = "、".join(str(name) for name in names if str(name))
    coin = item.get("coin")
    result = item.get("result_coin")
    coin_text = "－" if coin is None else str(int(coin))
    result_text = "－" if result is None else str(int(result))
    shown = f"{coin_text} / {result_text}"
    if coin is not None and result is not None and int(coin) > 0:
        shown += f" × {int(result) / int(coin):.1f}"
    return [
        (str(item.get("started") or ""), False),
        (f"  使用アイテム {items_text}", False),
        (f"  コイン {shown}", False),
    ]


def _windows_msg_type(event_type) -> bytes:
    if isinstance(event_type, (bytes, bytearray)):
        return bytes(event_type)
    data = getattr(event_type, "data", None)
    if callable(data):
        try:
            raw = data()
        except Exception:
            raw = b""
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
    try:
        return bytes(event_type)
    except Exception:
        return b""


class MenuWindow(QMainWindow):
    tsum_icon_ready = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.tsum_icon_ready.connect(self._on_tsum_icon_ready)
        self.setWindowTitle("AUTO PLAY")
        root = QWidget()
        _plain_surface(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._header = QWidget()
        self._footer = QWidget()
        blue = root.palette()
        blue.setColor(QPalette.ColorRole.Window, QColor("#A4C6FF"))
        blue.setColor(QPalette.ColorRole.WindowText, QColor("#17233f"))
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
        settings_button = QPushButton("設定")
        settings_button.clicked.connect(self._open_type_settings)
        header_layout.addWidget(
            settings_button,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
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
        self._item_lit = []
        self._item_active: set[int] = set()
        self._item_labels = []
        self._item_rows = []
        self._item_block = None
        self._center_slot = None
        self._center_buttons = []
        self._autoplay_button = None
        self._end_play_button = None
        self._item_check = None
        self._play_stop = threading.Event()
        self._stop_hotkey = False
        self._stop_key_timer = None
        self._q_down = False
        self._autoplay_alive = False
        self._stop_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Q), self)
        self._stop_shortcut.setAutoRepeat(False)
        self._stop_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._stop_shortcut.activated.connect(self._stop_play)
        self._tsum_hotkey = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._tsum_hot_ids: list[int] = []
        self._tsum_hot_yes = None
        self._tsum_hot_no = None
        self._tsum_hot_cancel = None
        self._stopped_by_key = False
        self._intro = None
        self._play_worker = None
        self._play_games = None
        self._play_api = None
        self._used_tsum_name = ""
        self._tsum_body = None
        self._used_tsum_label = None
        self._used_tsum_icon = None
        self._tsum_box = None
        self._tsum_actions = None
        self._tsum_path: Path | None = None
        self._tsum_list = None
        self._tsum_prompt = None
        self._tsum_blink_on = True
        self._tsum_blink_timer = None
        self._center_input = None
        self._center_blank = None
        self._activity = None
        self._launch_button = None
        self._game_list = None
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        model_box = QFrame()
        model_box.setFrameShape(QFrame.Shape.NoFrame)
        _plain_surface(model_box)
        body.addWidget(model_box, 1)
        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(0)
        for _ in range(3):
            slot = QFrame()
            slot.setFrameShape(QFrame.Shape.NoFrame)
            _plain_surface(slot)
            right_column.addWidget(slot, 1)
            self._slots.append(slot)
        body.addLayout(right_column, 2)
        layout.addLayout(body, 1)
        self._fill_model(model_box)
        self._fill_items(self._slots[0])
        self._fill_center(self._slots[1])
        self._fill_records(self._slots[2])
        self._model_update_check = _ModelUpdateCheck(self._model_token_value, self)
        self._model_update_check.found.connect(self._set_model_update)
        self._model_update_check.start()
        self._app_update_check = _AppUpdateCheck(self)
        self._app_update_check.found.connect(self._ask_app_update)
        self._app_update_check.start()
        self._app_allowed = None
        self._app_use_box = None
        if self._autoplay_button is not None:
            self._autoplay_button.setEnabled(False)
        self._app_use_check = _AppUseCheck(self._model_token_value, self)
        self._app_use_check.found.connect(self._apply_app_use)
        self._app_use_check.start()
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
        QTimer.singleShot(0, self._fit_model_buttons)

    def _start_ipc(self) -> None:
        self._ipc_buffers: dict[int, bytes] = {}
        self._ipc_server = QLocalServer(self)
        self._ipc_server.newConnection.connect(self._on_ipc_connection)
        if self._ipc_server.listen(MENU_IPC):
            return
        QLocalServer.removeServer(MENU_IPC)
        self._ipc_server.listen(MENU_IPC)

    def _on_ipc_connection(self) -> None:
        sock = self._ipc_server.nextPendingConnection()
        if sock is None:
            return
        self._ipc_buffers[id(sock)] = b""
        sock.readyRead.connect(lambda s=sock: self._on_ipc_ready(s))
        sock.disconnected.connect(lambda s=sock: self._ipc_buffers.pop(id(s), None))

    def _on_ipc_ready(self, sock: QLocalSocket) -> None:
        self._ipc_buffers[id(sock)] = self._ipc_buffers.get(id(sock), b"") + bytes(sock.readAll())
        buffer = self._ipc_buffers[id(sock)]
        if b"\n" not in buffer:
            return
        line, rest = buffer.split(b"\n", 1)
        self._ipc_buffers[id(sock)] = rest
        try:
            json.loads(line.decode("utf-8"))
        except Exception:
            sock.write(b'{"ok":false}\n')
            sock.flush()
            return
        sock.write(b'{"ok":true}\n')
        sock.flush()
        self._bring_to_front()
        self._reread_app_use()

    def _bring_to_front(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

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
        QTimer.singleShot(0, self._fit_model_summary)
        QTimer.singleShot(0, self._fit_used_tsum_icon)
        QTimer.singleShot(0, self._fit_flow_lamps)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_logo()
        QTimer.singleShot(0, self._fit_items)
        QTimer.singleShot(0, self._fit_center)
        QTimer.singleShot(0, self._fit_model_summary)
        QTimer.singleShot(0, self._fit_used_tsum_icon)
        QTimer.singleShot(0, self._fit_flow_lamps)

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

    def _fill_model(self, model_box: QFrame) -> None:
        self._model_box = model_box
        left = QVBoxLayout(model_box)
        left.setContentsMargins(0, 0, 0, TITLE_MARGIN)
        left.setSpacing(0)
        left.addWidget(self._section_title("MODEL情報"))
        mark_font = self.font()
        mark_font.setBold(True)
        mark_font.setPointSize(10)
        self._model_choice_label = QLabel("")
        self._model_choice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._model_choice_label.setFont(mark_font)
        self._model_choice_label.setStyleSheet("color: #A4C6FF; background: transparent;")
        left.addWidget(self._model_choice_label)
        self._show_model_choice()
        self._add_used_sections(left, mark_font)
        self._flow_lamps: dict[str, QPushButton] = {}
        for name in FLOW_LAMPS:
            lamp = QPushButton(name)
            lamp.setFont(mark_font)
            lamp.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lamp.setFlat(False)
            lamp.setAutoDefault(False)
            lamp.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            lamp.setStyleSheet(FLOW_LAMP_OFF)
            self._flow_lamps[name] = lamp
            left.addWidget(lamp, 0, Qt.AlignmentFlag.AlignHCenter)
        QTimer.singleShot(0, self._fit_flow_lamps)
        left.addStretch(1)
        memory_title = QLabel("メモリ使用率")
        memory_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        memory_title.setFont(mark_font)
        left.addWidget(memory_title)
        self._memory_use = QLabel("")
        self._memory_use.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._memory_use.setFont(mark_font)
        left.addWidget(self._memory_use)
        self._refresh_memory_use()
        self._memory_timer = QTimer(self)
        self._memory_timer.setInterval(1000)
        self._memory_timer.timeout.connect(self._refresh_memory_use)
        self._memory_timer.start()
        self._model_differs: dict[str, bool] = {}
        self._model_fetch = None
        self._model_progress = None
        self._model_fetch_name = ""
        self._model_token_value = _model_token()
        self._update_buttons: dict[str, QPushButton] = {}
        self._model_summary = QPushButton("更新なし")
        self._model_summary.clicked.connect(self._open_model_updates)
        self._model_summary.setCursor(Qt.CursorShape.PointingHandCursor)
        self._model_summary.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._paint_model_button(self._model_summary, False)
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(4, 4, 4, 4)
        summary_row.addStretch(1)
        summary_row.addWidget(self._model_summary)
        summary_row.addStretch(1)
        left.addLayout(summary_row)
        self._model_update_window = QDialog(self)
        self._model_update_window.setWindowTitle("更新")
        model_grid = QGridLayout(self._model_update_window)
        model_grid.setContentsMargins(8, 8, 8, 8)
        model_grid.setHorizontalSpacing(4)
        model_grid.setVerticalSpacing(4)
        for index, (name, label, _dest) in enumerate(MODEL_BUTTONS):
            button = QPushButton(f"{label} 更新なし")
            button.clicked.connect(
                lambda _checked=False, model_name=name: self._import_model(model_name)
            )
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._paint_model_button(button, False)
            self._update_buttons[name] = button
            self._model_differs[name] = False
            model_grid.addWidget(button, index // 2, index % 2)
        self._fit_model_buttons()
        self._fit_model_summary()

    def _refresh_memory_use(self) -> None:
        label = getattr(self, "_memory_use", None)
        if label is None:
            return
        percent = _memory_use_percent()
        if percent is None:
            return
        label.setText(f"{percent} %")

    def _fit_model_summary(self) -> None:
        box = getattr(self, "_model_box", None)
        button = getattr(self, "_model_summary", None)
        if box is None or button is None:
            return
        width = box.width() * 80 // 100
        if width < 1:
            return
        button.setFixedWidth(width)

    def _add_used_sections(self, left: QVBoxLayout, mark_font) -> None:
        tsum_box = QFrame()
        tsum_box.setFrameShape(QFrame.Shape.NoFrame)
        tsum_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._tsum_box = tsum_box
        self._item_box = QFrame()
        self._item_box.setFrameShape(QFrame.Shape.NoFrame)
        self._item_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        left.addWidget(self._item_box)
        inner = QVBoxLayout(self._item_box)
        inner.setContentsMargins(0, 0, 0, 5)
        inner.setSpacing(0)
        inner.addWidget(self._section_title("使用アイテム", 5, 5))
        block = QWidget()
        block.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        block_layout.setSpacing(5)
        self._item_block = block_layout
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(5)
        row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._item_rows.append(row)
        for filename in ITEM_ICONS:
            label = QLabel()
            raw = QPixmap(str(ICON_DIR / filename))
            self._item_lit.append(raw)
            self._item_src.append(_mist_pixmap(_dim_pixmap(raw)))
            self._item_labels.append(label)
            row.addWidget(label)
        block_layout.addLayout(row)
        inner.addWidget(block, 0, Qt.AlignmentFlag.AlignHCenter)
        above = QVBoxLayout(tsum_box)
        above.setContentsMargins(0, 0, 0, 0)
        above.setSpacing(0)
        above.addWidget(self._section_title("使用ツム"))
        self._used_tsum_icon = QLabel()
        self._used_tsum_icon.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._used_tsum_icon.setMinimumWidth(0)
        self._used_tsum_icon.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._used_tsum_icon.setFixedHeight(0)
        self._used_tsum_frame = QFrame()
        _soft_box(self._used_tsum_frame)
        self._used_tsum_frame.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        icon_box = QVBoxLayout(self._used_tsum_frame)
        icon_box.setContentsMargins(0, 0, 0, 0)
        icon_box.setSpacing(0)
        icon_box.addWidget(self._used_tsum_icon, 0, Qt.AlignmentFlag.AlignCenter)
        above.addWidget(self._used_tsum_frame, 0, Qt.AlignmentFlag.AlignHCenter)
        above.addSpacing(3)
        self._used_tsum_label = QLabel("")
        self._used_tsum_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        above.addWidget(self._used_tsum_label)
        self._play_count_label = QLabel("0")
        self._play_count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._play_count_label.setFont(mark_font)
        self._tsum_recognition = QLabel("")
        self._tsum_recognition.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tsum_recognition.setFont(mark_font)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(TITLE_MARGIN)
        row.addStretch(1)
        row.addWidget(
            self._count_side("プレイ回数", self._play_count_label),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        row.addWidget(tsum_box, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(
            self._count_side("ツム認知度", self._tsum_recognition),
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        row.addStretch(1)
        left.insertLayout(left.indexOf(self._item_box), row)

    def _count_side(self, title: str, label: QLabel) -> QWidget:
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        column = QVBoxLayout(wrap)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._section_title(title))
        column.addWidget(label)
        return wrap

    def _fill_items(self, slot: QFrame) -> None:
        column = QVBoxLayout(slot)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        right_box = QFrame()
        right_box.setFrameShape(QFrame.Shape.NoFrame)
        column.addWidget(right_box, 1)
        right = QVBoxLayout(right_box)
        right.setContentsMargins(0, 0, 0, TITLE_MARGIN)
        right.setSpacing(0)
        self._tsum_body = QVBoxLayout()
        self._tsum_body.setContentsMargins(0, 0, 0, 0)
        self._tsum_body.setSpacing(0)
        right.addLayout(self._tsum_body, 1)
        self._tsum_actions = QVBoxLayout()
        self._tsum_actions.setContentsMargins(0, 0, 0, 0)
        self._tsum_actions.setSpacing(0)
        right.addLayout(self._tsum_actions)

    def _create_desktop_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        if sys.platform == "darwin":
            dest = self._create_macos_shortcut(Path(desktop))
            QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{dest}")
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

    def _create_macos_shortcut(self, desktop: Path) -> Path:
        import shutil

        app_path = desktop / "AUTO PLAY.app"
        contents = app_path / "Contents"
        macos_dir = contents / "MacOS"
        if app_path.exists():
            shutil.rmtree(app_path)
        macos_dir.mkdir(parents=True, exist_ok=True)
        launcher = macos_dir / "launch"
        launcher.write_text(
            "#!/bin/bash\n"
            f'cd "{ROOT}"\n'
            f'exec "{sys.executable}" "{ROOT / "main.py"}"\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        (contents / "Info.plist").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>workshop.auto-play</string>
  <key>CFBundleName</key><string>AUTO PLAY</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
""",
            encoding="utf-8",
        )
        return app_path

    def _ask_app_update(self, available: bool) -> None:
        if not available:
            return
        box = QMessageBox(self)
        box.setWindowTitle("AUTO PLAY")
        box.setText("アプリの更新があります。更新してもよろしいですか？")
        yes = box.addButton("はい", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("いいえ", QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(no)
        box.exec()
        if box.clickedButton() is not yes:
            return
        ok, detail = _pull_app_update()
        if ok:
            try:
                _schedule_relaunch()
            except OSError:
                self._set_activity("終了して、もう一度起動する")
                return
            server = getattr(self, "_ipc_server", None)
            if server is not None:
                server.close()
            QLocalServer.removeServer(MENU_IPC)
            QApplication.quit()
            return
        self._set_activity(detail or "更新できませんでした。")

    def _fit_model_buttons(self) -> None:
        buttons = [button for button in self._update_buttons.values() if button is not None]
        if not buttons:
            return
        saved = [(button, button.text()) for button in buttons]
        for button in buttons:
            button.ensurePolished()
        width = 0
        for name, label, _dest in MODEL_BUTTONS:
            button = self._update_buttons.get(name)
            if button is None:
                continue
            for suffix in ("更新する", "更新なし"):
                button.setText(f"{label} {suffix}")
                width = max(width, button.sizeHint().width())
        for button, text in saved:
            button.setText(text)
        if width <= 0:
            return
        for button in buttons:
            button.setFixedWidth(width)
        window = self._model_update_window
        window.adjustSize()

    def _paint_model_button(self, button: QPushButton, differs: bool) -> None:
        if differs:
            button.setStyleSheet(
                "QPushButton {"
                " background: #FF1A6F;"
                " color: #ffffff;"
                " font-weight: 700;"
                " font-size: 8pt;"
                " border: 1px solid #FF1A6F;"
                " border-radius: 6px;"
                " padding: 2px;"
                "}"
                "QPushButton:hover { background: #FF1A6F; }"
            )
            return
        button.setStyleSheet(
            "QPushButton {"
            " background: #ffffff;"
            " color: #2c4a7a;"
            " font-weight: 700;"
                " font-size: 8pt;"
                " border: 1px solid #8eb4ee;"
                " border-radius: 6px;"
                " padding: 2px;"
            "}"
            "QPushButton:hover { background: #f3f7ff; }"
        )

    def _set_model_update(self, available: object) -> None:
        flags = available if isinstance(available, dict) else {}
        for name, label, _dest in MODEL_BUTTONS:
            button = self._update_buttons.get(name)
            if button is None:
                continue
            differs = bool(flags.get(name))
            self._model_differs[name] = differs
            button.setText(f"{label} 更新する" if differs else f"{label} 更新なし")
            self._paint_model_button(button, differs)
            button.setEnabled(True)
        self._refresh_model_summary()

    def _refresh_model_summary(self) -> None:
        differs = any(self._model_differs.values())
        self._model_summary.setText("更新あり" if differs else "更新なし")
        self._paint_model_button(self._model_summary, differs)

    def _open_model_updates(self) -> None:
        if not any(self._model_differs.values()):
            return
        self._fit_model_buttons()
        self._model_update_window.show()
        self._model_update_window.raise_()
        self._model_update_window.activateWindow()

    def _import_model(self, name: str) -> None:
        if not self._model_differs.get(name) or self._model_fetch is not None:
            return
        label = next(text for key, text, _path in MODEL_BUTTONS if key == name)
        dest = next(path for key, _text, path in MODEL_BUTTONS if key == name)
        button = self._update_buttons.get(name)
        if button is not None:
            button.setEnabled(False)
        dialog = QProgressDialog(f"{label} を取り込んでいます。", None, 0, 0, self)
        dialog.setWindowTitle("モデルを取り込み")
        dialog.setCancelButton(None)
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.show()
        self._model_progress = dialog
        QApplication.processEvents()
        self._model_fetch_name = name
        worker = _ModelFetch(self._model_token_value, name, dest, self)
        worker.finished_import.connect(self._on_model_imported)
        self._model_fetch = worker
        worker.start()

    def _close_model_progress(self) -> None:
        dialog = self._model_progress
        self._model_progress = None
        if dialog is not None:
            dialog.close()

    def _on_model_imported(self, ok: bool, message: str) -> None:
        name = self._model_fetch_name
        label = next(text for key, text, _path in MODEL_BUTTONS if key == name)
        self._model_fetch = None
        self._model_fetch_name = ""
        self._close_model_progress()
        button = self._update_buttons.get(name)
        if button is not None:
            button.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "モデルを取り込めませんでした", message or "モデルを取り込めませんでした。")
            return
        self._model_differs[name] = False
        if button is not None:
            button.setText(f"{label} 更新なし")
            self._paint_model_button(button, False)
        self._refresh_model_summary()
        QMessageBox.information(self, "モデルを取り込みました", f"{label} を取り込みました。")

    def _fill_records(self, slot: QFrame) -> None:
        from app.game_record import load_game_records

        column = QVBoxLayout(slot)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self._game_list = QListWidget()
        self._game_list.setFrameShape(QFrame.Shape.NoFrame)
        self._game_list.setStyleSheet(
            "QListWidget { background: #17233f; color: #e8f0ff; border: none; }"
            "QListWidget QLabel { color: #e8f0ff; background: transparent; }"
        )
        column.addWidget(self._game_list, 1)
        for item in load_game_records():
            self._show_game_record(item)

    def _record_row(self, parts: list[tuple[str, bool]]) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        labels = []
        for text, _right in parts:
            label = QLabel(text)
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            labels.append(label)
            layout.addWidget(label)
        layout.addStretch(1)
        row._record_labels = labels
        return row

    def _align_game_records(self) -> None:
        game_list = self._game_list
        if game_list is None:
            return
        metrics = QFontMetrics(game_list.font())
        rows = []
        widest: list[int] = []
        for index in range(game_list.count()):
            listed = game_list.item(index)
            if listed is None:
                continue
            widget = game_list.itemWidget(listed)
            labels = getattr(widget, "_record_labels", None) if widget is not None else None
            if not labels:
                continue
            rows.append((listed, widget, labels))
            for label_index, label in enumerate(labels):
                width = metrics.horizontalAdvance(label.text())
                if label_index >= len(widest):
                    widest.append(width)
                elif width > widest[label_index]:
                    widest[label_index] = width
        for listed, widget, labels in rows:
            for label_index, label in enumerate(labels):
                label.setFixedWidth(widest[label_index])
            listed.setSizeHint(widget.sizeHint())

    def _show_game_record(self, item: object) -> None:
        if not isinstance(item, dict) or self._game_list is None:
            return
        record_id = item.get("id")
        if item.get("result_coin") is not None and self._play_busy():
            self._set_flow_lamp("リザルト検知")
        parts = _game_record_parts(item)
        for row in range(self._game_list.count()):
            listed = self._game_list.item(row)
            if listed is None or listed.data(Qt.ItemDataRole.UserRole) != record_id:
                continue
            widget = self._game_list.itemWidget(listed)
            labels = getattr(widget, "_record_labels", None) if widget is not None else None
            if labels is not None:
                for label, (text, _right) in zip(labels, parts):
                    label.setText(text)
            self._align_game_records()
            return
        entry = QListWidgetItem()
        entry.setData(Qt.ItemDataRole.UserRole, record_id)
        self._game_list.insertItem(0, entry)
        self._game_list.setItemWidget(entry, self._record_row(parts))
        self._align_game_records()

    def _show_play_count(self) -> None:
        label = getattr(self, "_play_count_label", None)
        if label is None or self._center_input is None:
            return
        label.setText(self._center_input.currentText().strip())

    def _show_tsum_recognition(self, count: int) -> None:
        label = getattr(self, "_tsum_recognition", None)
        if label is None:
            return
        label.setText(f"{int(count)}体")

    def _fill_center(self, slot: QFrame) -> None:
        self._center_slot = slot
        outer = QVBoxLayout(slot)
        outer.setContentsMargins(0, 0, 0, 0)
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 10, 0, 0)
        column.setSpacing(0)
        grid_host = QWidget()
        grid_host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        end_button = QPushButton("このプレイでやめる")
        end_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._end_play_button = end_button
        self._write_button_key(end_button, "このプレイでやめる", "F2")
        end_button.clicked.connect(self._end_after_this_play)
        self._center_buttons.append(end_button)
        grid.addWidget(end_button, 0, 1)
        play_button = QPushButton("オートプレイ")
        play_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._autoplay_button = play_button
        self._write_button_key(play_button, "オートプレイ", "F3")
        play_button.clicked.connect(self._on_autoplay)
        play_key = QShortcut(QKeySequence(Qt.Key.Key_F3), play_button)
        play_key.setAutoRepeat(False)
        play_key.setContext(Qt.ShortcutContext.WindowShortcut)
        play_key.activated.connect(self._on_autoplay)
        self._center_buttons.append(play_button)
        grid.addWidget(play_button, 0, 2)
        self._launch_button = QPushButton("起動アイコンをデスクトップに作成")
        self._launch_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self._launch_button.clicked.connect(self._create_desktop_shortcut)
        self._center_buttons.append(self._launch_button)
        self._center_blank = QFrame()
        _soft_box(self._center_blank)
        blank_layout = QVBoxLayout(self._center_blank)
        blank_layout.setContentsMargins(TITLE_MARGIN, TITLE_MARGIN, TITLE_MARGIN, TITLE_MARGIN)
        blank_layout.setSpacing(0)
        self._activity = QLabel("")
        self._activity.setWordWrap(True)
        self._activity.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        blank_layout.addWidget(self._activity, 1)
        stop_hint = QLabel("プレイ中の停止は Q")
        hint_font = stop_hint.font()
        hint_point = hint_font.pointSize()
        if hint_point < 1:
            hint_point = 9
        hint_font.setPointSize(hint_point + 2)
        hint_font.setBold(True)
        stop_hint.setFont(hint_font)
        stop_hint.setStyleSheet("color: #FF1A6F;")
        stop_hint.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        hint_metrics = stop_hint.fontMetrics()
        stop_hint.setContentsMargins(0, 0, hint_metrics.horizontalAdvance("あ"), max(1, hint_metrics.height() // 2))
        half_char = max(1, holder.fontMetrics().height() // 2)
        column.setSpacing(half_char)
        column.addWidget(self._center_blank, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(grid_host, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(self._launch_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._center_input = QComboBox()
        self._center_input.setEditable(True)
        self._center_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._center_input.addItems([str(value) for value in range(1, 101)])
        self._center_input.addItem("∞")
        field = self._center_input.lineEdit()
        field.setValidator(QRegularExpressionValidator(QRegularExpression("[0-9]*")))
        field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._center_input.setCurrentIndex(0)
        self._center_input.currentTextChanged.connect(self._show_play_count)
        self._show_play_count()
        self._center_input.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        grid.addWidget(self._center_input, 0, 3)
        outer.addStretch(1)
        outer.addWidget(holder, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(2)
        outer.addWidget(
            stop_hint,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )

    def _fit_flow_lamps(self) -> None:
        box = getattr(self, "_model_box", None)
        lamps = getattr(self, "_flow_lamps", None)
        if box is None or not lamps:
            return
        width = box.contentsRect().width() // 2
        if width < 1:
            return
        for lamp in lamps.values():
            lamp.setFixedWidth(width)

    def _ensure_flow_blink(self) -> None:
        timer = getattr(self, "_flow_blink_timer", None)
        if timer is not None:
            return
        timer = QTimer(self)
        timer.setInterval(500)
        timer.timeout.connect(self._tick_flow_blink)
        self._flow_blink_timer = timer
        self._flow_current = ""
        self._flow_blink_on = True
        self._flow_reached = -1

    def _tick_flow_blink(self) -> None:
        name = getattr(self, "_flow_current", "")
        lamps = getattr(self, "_flow_lamps", None)
        if not name or not lamps or name not in lamps:
            return
        self._flow_blink_on = not self._flow_blink_on
        lamps[name].setStyleSheet(
            FLOW_LAMP_BLINK if self._flow_blink_on else FLOW_LAMP_BLINK_WHITE
        )

    def _set_flow_lamp(self, name: str) -> None:
        lamps = getattr(self, "_flow_lamps", None)
        if not lamps:
            return
        self._ensure_flow_blink()
        if not name:
            self._flow_blink_timer.stop()
            current = self._flow_current
            if current in lamps:
                lamps[current].setStyleSheet(FLOW_LAMP_ON)
            return
        if name not in lamps:
            return
        if name == "システム開始":
            self._flow_blink_timer.stop()
            for lamp in lamps.values():
                lamp.setStyleSheet(FLOW_LAMP_OFF)
            self._flow_current = ""
            self._flow_reached = -1
        index = FLOW_LAMPS.index(name)
        reached = self._flow_reached
        if index < reached:
            return
        if name != "システム終了" and index > reached + 1:
            return
        if name == "システム終了":
            self._flow_blink_timer.stop()
            for lamp in lamps.values():
                lamp.setStyleSheet(FLOW_LAMP_OFF)
            lamps[name].setStyleSheet(FLOW_LAMP_BLINK)
            self._flow_current = name
            self._flow_reached = index
            return
        if name == self._flow_current and self._flow_blink_timer.isActive():
            return
        if self._flow_current in lamps and self._flow_current != name:
            lamps[self._flow_current].setStyleSheet(FLOW_LAMP_ON)
        self._flow_current = name
        self._flow_reached = index
        self._flow_blink_on = True
        lamps[name].setStyleSheet(FLOW_LAMP_BLINK)
        self._flow_blink_timer.start()

    def _lamp_for_activity(self, text: str) -> str:
        if text.startswith("TIME UP"):
            return "TIME UP 検知"
        if text.startswith("ハート"):
            return "ハートの確認"
        if text == "使用ツムの問いに答えてください":
            return "使用ツムの確認"
        if (
            text.startswith("モデルを読み込み")
            or text == "ツム名のモデル"
            or text.startswith("画面認識のライブラリ")
        ):
            return "モデルの確認"
        if text.startswith("スタートを検出") or text.startswith("スタートをクリック"):
            return "スタート画面確認"
        if text == "プレイを開始します":
            return "プレイを開始"
        if text.startswith("BlueStacks"):
            return "BLUE STACK 起動確認"
        if text.startswith("アイテムの画面"):
            return "使用アイテム確認"
        if (
            "画面を待って" in text
            or text.startswith("許可")
            or text.startswith("TAP TO START")
            or text.startswith("動画")
        ):
            return "画面の確認"
        return ""

    def _set_activity(self, text: str) -> None:
        if self._activity is None:
            return
        if text.startswith("LossTime "):
            return
        self._activity.setText(text)
        lamp = self._lamp_for_activity(text)
        if lamp:
            self._set_flow_lamp(lamp)

    def _on_play_done(self) -> None:
        self._autoplay_alive = False
        self._unregister_stop_hotkey()
        self._set_activity("プレイが終わりました")
        self._set_flow_lamp("システム終了")

    def _play_busy(self) -> bool:
        intro_on = self._intro is not None and self._intro.isRunning()
        play_on = self._play_worker is not None and self._play_worker.isRunning()
        return intro_on or play_on

    def _register_stop_hotkey(self) -> None:
        if sys.platform == "win32" and not self._stop_hotkey:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            ok = user32.RegisterHotKey(hwnd, 1, 0x4000, 0x51)
            user32.RegisterHotKey(hwnd, 2, 0x4000, 0x71)
            self._stop_hotkey = bool(ok)
        self._start_stop_key_poll()

    def _start_stop_key_poll(self) -> None:
        if sys.platform != "win32":
            return
        timer = self._stop_key_timer
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(100)
            timer.timeout.connect(self._poll_stop_key)
            self._stop_key_timer = timer
        if not timer.isActive():
            self._q_down = False
            timer.start()

    def _poll_stop_key(self) -> None:
        if not self._play_busy():
            return
        import ctypes

        down = bool(ctypes.windll.user32.GetAsyncKeyState(0x51) & 0x8000)
        pressed = down and not self._q_down
        self._q_down = down
        if pressed:
            self._stop_play()

    def _unregister_stop_hotkey(self) -> None:
        timer = self._stop_key_timer
        if timer is not None:
            timer.stop()
        if sys.platform != "win32" or not self._stop_hotkey:
            return
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(self.winId())
        user32.UnregisterHotKey(hwnd, 1)
        user32.UnregisterHotKey(hwnd, 2)
        self._stop_hotkey = False

    def _end_after_this_play(self) -> None:
        worker = self._play_worker
        if worker is None or not worker.isRunning():
            return
        worker.finish_after_this()
        self._set_activity("このプレイでやめます")

    def _stop_play(self) -> None:
        item_check = self._item_check
        item_on = item_check is not None and item_check.isRunning()
        if not self._play_busy() and not item_on and not self._autoplay_alive:
            return
        self._stopped_by_key = True
        self._autoplay_alive = False
        if not self._play_stop.is_set():
            self._play_stop.set()
            if self._intro is not None and self._intro.isRunning():
                self._intro.requestInterruption()
            if self._play_worker is not None and self._play_worker.isRunning():
                self._play_worker.requestInterruption()
        self._clear_tsum_frame()
        if item_on:
            item_check.requestInterruption()
            self._item_check = None
        worker = self._play_worker
        if worker is not None:
            worker.provide_used_tsum(None)
            worker.provide_kinds(None)
        modal = QApplication.activeModalWidget()
        if isinstance(modal, QMessageBox):
            modal.done(0)
        try:
            from app.bluestacks import halt_input
        except Exception:
            halt_input = None
        if halt_input is not None:
            halt_input()
        if self._autoplay_button is not None:
            self._autoplay_button.setEnabled(True)
        if not self._play_busy():
            self._set_activity("停止しました")
            self._set_flow_lamp("システム終了")
            return
        self._set_activity("停止しています")

    def _on_play_stopped(self) -> None:
        self._autoplay_alive = False
        self._unregister_stop_hotkey()
        if not self._stopped_by_key:
            return
        self._stopped_by_key = False
        self._set_activity("停止しました")
        self._set_flow_lamp("システム終了")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Q and not event.isAutoRepeat():
            self._stop_play()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Q
            and not event.isAutoRepeat()
        ):
            self._stop_play()
            return True
        return super().eventFilter(watched, event)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and (self._stop_hotkey or self._tsum_hotkey):
            raw = _windows_msg_type(eventType)
            if raw.startswith(b"windows_generic_MSG") or raw.startswith(b"windows_dispatcher_MSG"):
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312 and int(msg.wParam) == 1:
                    QTimer.singleShot(0, self._stop_play)
                    return True, 0
                if msg.message == 0x0312 and int(msg.wParam) == 2:
                    QTimer.singleShot(0, self._end_after_this_play)
                    return True, 0
                if self._tsum_hotkey and msg.message == 0x0312:
                    action = {
                        3: self._tsum_hot_yes,
                        4: self._tsum_hot_no,
                        5: self._tsum_hot_cancel,
                    }.get(int(msg.wParam))
                    if action is not None:
                        QTimer.singleShot(0, action)
                        return True, 0
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event) -> None:
        self._unregister_tsum_hotkeys()
        self._unregister_stop_hotkey()
        super().closeEvent(event)

    def _register_tsum_hotkeys(self, yes, no, cancel) -> None:
        self._unregister_tsum_hotkeys()
        self._tsum_hot_yes = yes
        self._tsum_hot_no = no
        self._tsum_hot_cancel = cancel
        if sys.platform != "win32":
            return
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(self.winId())
        registered = []
        for hot_id, virtual_key in ((3, 0x0D), (4, 0x4E), (5, 0x1B)):
            if user32.RegisterHotKey(hwnd, hot_id, 0x4000, virtual_key):
                registered.append(hot_id)
        self._tsum_hot_ids = registered
        self._tsum_hotkey = bool(registered)

    def _unregister_tsum_hotkeys(self) -> None:
        self._tsum_hot_yes = None
        self._tsum_hot_no = None
        self._tsum_hot_cancel = None
        if sys.platform != "win32" or not self._tsum_hotkey:
            self._tsum_hot_ids = []
            self._tsum_hotkey = False
            return
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(self.winId())
        for hot_id in self._tsum_hot_ids:
            user32.UnregisterHotKey(hwnd, hot_id)
        self._tsum_hot_ids = []
        self._tsum_hotkey = False

    def _reread_app_use(self) -> None:
        running = self._app_use_check
        if running is not None and running.isRunning():
            return
        check = _AppUseCheck(self._model_token_value, self)
        check.found.connect(self._apply_app_use)
        self._app_use_check = check
        check.start()

    def _apply_app_use(self, allowed: object) -> None:
        if isinstance(allowed, tuple) and len(allowed) == 2 and allowed[0] is False:
            self._app_allowed = False
            if self._autoplay_button is not None:
                self._autoplay_button.setEnabled(False)
            if self._app_use_box is not None:
                return
            message = allowed[1].strip() if isinstance(allowed[1], str) else ""
            if not message:
                message = "ただいまメンテナンス中です。"
            box = QMessageBox(self)
            box.setWindowTitle("AUTO PLAY")
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(message)
            self._app_use_box = box
            box.exec()
            self._app_use_box = None
            if not self._app_allowed:
                QApplication.quit()
            return
        self._app_allowed = True
        if self._autoplay_button is not None:
            self._autoplay_button.setEnabled(True)
        if self._app_use_box is not None:
            self._app_use_box.done(0)

    def _on_autoplay(self) -> None:
        if not self._app_allowed:
            return
        self._autoplay_alive = True
        self._play_stop.clear()
        self._set_flow_lamp("システム開始")
        self._set_activity("BlueStacks を確認しています")
        if self._play_stop.is_set():
            return
        if not _bluestacks_running():
            self._autoplay_alive = False
            self._set_activity("BlueStacks は起動していません。")
            QMessageBox.information(self, "オートプレイ", "BlueStacks は起動していません。")
            return
        if self._play_stop.is_set():
            return
        if self._item_check is not None:
            return
        if self._autoplay_button is not None:
            self._autoplay_button.setEnabled(False)
        self._set_activity("アイテムの画面を確認しています")
        worker = _ItemCheck(self)
        worker.found.connect(self._on_items_checked)
        self._item_check = worker
        worker.start()

    def _on_items_checked(self, payload: object) -> None:
        self._item_check = None
        if self._play_stop.is_set() or not self._autoplay_alive:
            if self._autoplay_button is not None:
                self._autoplay_button.setEnabled(True)
            return
        if self._autoplay_button is not None:
            self._autoplay_button.setEnabled(True)
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            self._light_items([str(name) for name in payload["items"]])
        self._set_flow_lamp("ゲーム数確認")
        ok, games = self._game_count()
        if not ok:
            self._autoplay_alive = False
            self._set_activity("プレイするゲーム数がありません。")
            QMessageBox.information(self, "オートプレイ", "プレイするゲーム数がありません。")
            return
        _start_play_here(self, games)

    def _on_intro_ok(self) -> None:
        if self._play_stop.is_set():
            return
        _start_match(self)

    def _on_intro_fail(self, message: str) -> None:
        self._autoplay_alive = False
        self._unregister_stop_hotkey()
        self._set_activity(message)
        self._set_flow_lamp("システム終了")
        QMessageBox.critical(self, "オートプレイ", message)

    def _on_play_fail(self, message: str) -> None:
        self._autoplay_alive = False
        self._unregister_stop_hotkey()
        self._set_activity(message)
        self._set_flow_lamp("システム終了")
        QMessageBox.critical(self, "オートプレイ", message)

    def _on_need_used_tsum(self, guess: str, path: str, pick_only: bool) -> None:
        worker = self._play_worker
        if worker is None:
            return
        if self._play_stop.is_set():
            worker.provide_used_tsum(None)
            return
        saved = self._used_tsum_name
        if saved:
            worker.provide_used_tsum(saved)
            return
        self._tsum_path = Path(path) if path else None
        if pick_only or not guess:
            self._show_tsum_list("" if pick_only else guess)
            return
        self._show_tsum_guess(guess)

    def _clear_tsum_frame(self) -> None:
        self._unregister_tsum_hotkeys()
        for layout in (self._tsum_body, self._tsum_actions):
            if layout is None:
                continue
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                child = item.layout()
                if widget is not None:
                    widget.deleteLater()
                elif child is not None:
                    self._clear_nested(child)
        self._tsum_list = None
        self._tsum_prompt = None
        if self._tsum_blink_timer is not None:
            self._tsum_blink_timer.stop()

    def _clear_nested(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child is not None:
                self._clear_nested(child)

    def _write_button_key(self, button: QPushButton, label: str, key: str) -> None:
        metrics = button.fontMetrics()
        space = metrics.horizontalAdvance(" ")
        gap = max(1, metrics.horizontalAdvance("あ") // 2)
        count = max(1, round(gap / space)) if space else 1
        button.setText(label + (" " * count) + f"({key})")

    def _tsum_button_text(self, label: str, key: str) -> str:
        font = QApplication.font()
        point = font.pointSize()
        if point < 1:
            point = 9
        font.setPointSize(point + 2)
        metrics = QFontMetrics(font)
        space = metrics.horizontalAdvance(" ")
        gap = max(1, metrics.horizontalAdvance("あ") // 2)
        count = max(1, round(gap / space)) if space else 1
        return label + (" " * count) + f"({key})"

    def _add_tsum_button(self, text: str, slot, keys=()) -> QPushButton:
        button = QPushButton(text)
        font = button.font()
        point = font.pointSize()
        if point < 1:
            point = 9
        font.setPointSize(point + 2)
        button.setFont(font)
        metrics = button.fontMetrics()
        button.setMinimumWidth(metrics.horizontalAdvance(text) + metrics.height() * 2)
        button.setMinimumHeight(metrics.height() * 2)
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        button.setAutoDefault(False)

        def activate(b=button, s=slot) -> None:
            self._show_tsum_press(b, s)

        button.clicked.connect(lambda _checked=False, run=activate: run())
        for key in keys:
            shortcut = QShortcut(QKeySequence(key), button)
            shortcut.setAutoRepeat(False)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(activate)
        if self._tsum_body is not None:
            self._tsum_body.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        return button

    def _show_tsum_press(self, button: QPushButton, slot) -> None:
        if button.property("pressing"):
            return
        button.setProperty("pressing", True)
        button.setDown(True)
        QTimer.singleShot(200, lambda b=button, s=slot: self._finish_tsum_press(b, s))

    def _finish_tsum_press(self, button: QPushButton, slot) -> None:
        button.setDown(False)
        slot()

    def _tsum_question(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        font = label.font()
        point = font.pointSize()
        if point < 1:
            point = 9
        self._tsum_prompt_pt = point + 4
        font.setPointSize(self._tsum_prompt_pt)
        font.setBold(True)
        label.setFont(font)
        label.setContentsMargins(0, 0, 0, label.fontMetrics().height() // 2)
        self._tsum_prompt = label
        self._tsum_blink_on = True
        self._paint_tsum_prompt()
        if self._tsum_blink_timer is None:
            timer = QTimer(self)
            timer.setInterval(500)
            timer.timeout.connect(self._toggle_tsum_prompt)
            self._tsum_blink_timer = timer
        self._tsum_blink_timer.start()
        return label

    def _toggle_tsum_prompt(self) -> None:
        self._tsum_blink_on = not self._tsum_blink_on
        self._paint_tsum_prompt()

    def _paint_tsum_prompt(self) -> None:
        label = self._tsum_prompt
        if label is None:
            return
        color = "#FF1A6F" if self._tsum_blink_on else "transparent"
        point = getattr(self, "_tsum_prompt_pt", 13)
        label.setStyleSheet(f"color: {color}; font-weight: 700; font-size: {point}pt;")

    def _show_tsum_guess(self, guess: str) -> None:
        self._set_activity("使用ツムの問いに答えてください")
        self._clear_tsum_frame()
        if self._tsum_body is None:
            return
        self._tsum_body.addStretch(1)
        self._tsum_body.addWidget(self._tsum_question(f"使用ツムは {guess} ですか？"))
        buttons = (
            self._add_tsum_button(
                self._tsum_button_text("はい", "Enter"),
                lambda: self._accept_used_tsum(guess, None),
                (Qt.Key.Key_Return, Qt.Key.Key_Enter),
            ),
            self._add_tsum_button(
                self._tsum_button_text("いいえ", "N"),
                lambda: self._show_tsum_list(guess),
                (Qt.Key.Key_N,),
            ),
            self._add_tsum_button(
                self._tsum_button_text("やめる", "Esc"),
                self._cancel_used_tsum,
                (Qt.Key.Key_Escape,),
            ),
        )
        width = max(button.minimumWidth() for button in buttons)
        height = max(button.minimumHeight() for button in buttons)
        for button in buttons:
            button.setFixedSize(width, height)
        self._tsum_body.addStretch(1)
        self._register_tsum_hotkeys(buttons[0].click, buttons[1].click, buttons[2].click)

    def _show_tsum_list(self, skip_name: str = "") -> None:
        self._set_activity("使用ツムの問いに答えてください")
        names = _used_tsum_names()
        if skip_name:
            names = [name for name in names if name != skip_name]
        self._clear_tsum_frame()
        if self._tsum_body is None:
            return
        question = self._tsum_question("使用ツムはどれですか？")
        self._tsum_body.addWidget(question)
        name_list = QListWidget()
        pad = name_list.fontMetrics().horizontalAdvance("あ")
        gap = question.fontMetrics().height() // 2
        name_list.setStyleSheet(f"QListWidget::item {{ padding-left: {pad}px; }}")
        for name in names:
            name_list.addItem(name)
        if names:
            name_list.setCurrentRow(0)
        name_list.itemDoubleClicked.connect(lambda *_: self._accept_listed_tsum())
        self._tsum_list = name_list
        self._tsum_body.addWidget(name_list, 1)
        below = QWidget()
        below.setFixedHeight(gap)
        self._tsum_body.addWidget(below)
        buttons = (
            self._add_tsum_button("これにします", self._accept_listed_tsum),
            self._add_tsum_button("やめる", self._cancel_used_tsum),
        )
        width = max(button.minimumWidth() for button in buttons)
        height = max(button.minimumHeight() for button in buttons)
        for button in buttons:
            button.setFixedSize(width, height)

    def _accept_listed_tsum(self) -> None:
        row = self._tsum_list.currentItem() if self._tsum_list is not None else None
        if row is None:
            return
        self._accept_used_tsum(row.text(), None)

    def _accept_used_tsum(self, name: str, folder_id: str | None) -> None:
        saved = self._save_used_tsum_choice(self._tsum_path, name, folder_id)
        if not saved:
            return
        self._finish_used_tsum(saved)

    def _finish_used_tsum(self, name: str) -> None:
        worker = self._play_worker
        self._used_tsum_name = name
        self._clear_tsum_frame()
        if self._used_tsum_label is not None:
            self._used_tsum_label.setText(name)
        self._show_used_tsum_icon(name)
        threading.Thread(
            target=_fetch_used_tsum_icon,
            args=(name, self.tsum_icon_ready.emit),
            daemon=True,
        ).start()
        if worker is not None:
            worker.provide_used_tsum(name)

    def _cancel_used_tsum(self) -> None:
        worker = self._play_worker
        self._used_tsum_name = ""
        self._clear_tsum_frame()
        if self._used_tsum_label is not None:
            self._used_tsum_label.setText("")
        self._show_used_tsum_icon("")
        if worker is not None:
            worker.provide_used_tsum(None)
            self._play_stop.set()
        self._set_activity("中止しました")

    def _on_tsum_icon_ready(self, name: str) -> None:
        if name != self._used_tsum_name:
            return
        self._show_used_tsum_icon(name)

    def _show_used_tsum_icon(self, name: str) -> None:
        label = self._used_tsum_icon
        frame = getattr(self, "_used_tsum_frame", None)
        if label is None or frame is None:
            return
        limit_w, limit_h = self._used_tsum_icon_limit()
        if limit_w > 1 and limit_h > 1:
            frame.setFixedSize(limit_w, limit_h)
        border = frame.frameWidth() * 2
        inner_w = max(0, limit_w - border)
        inner_h = max(0, limit_h - border)
        path = _used_tsum_icon_file(name) if name else None
        pixmap = QPixmap(str(path)) if path is not None else QPixmap()
        if pixmap.isNull() or inner_w < 1 or inner_h < 1:
            label.clear()
            label.setFixedSize(inner_w, inner_h)
            return
        if pixmap.width() != inner_w or pixmap.height() != inner_h:
            pixmap = pixmap.scaled(
                inner_w,
                inner_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        label.setPixmap(pixmap)
        label.setFixedSize(pixmap.width(), pixmap.height())

    def _fit_used_tsum_icon(self) -> None:
        self._show_used_tsum_icon(self._used_tsum_name)

    def _used_tsum_icon_limit(self) -> tuple[int, int]:
        box = self._model_box
        if box is None:
            return 0, 0
        width = box.contentsRect().width()
        side = width // 9
        if side < 1:
            return 0, 0
        return side, side

    def _save_used_tsum_choice(
        self, path: Path | None, name: str, folder_id: str | None
    ) -> str | None:
        try:
            saved = _save_used_tsum(path, name, folder_id)
        except Exception as exc:  # noqa: BLE001
            if self._tsum_body is not None:
                self._tsum_body.addWidget(QLabel(str(exc)))
            return None
        return saved or name

    def _on_need_kinds(self) -> None:
        worker = self._play_worker
        if worker is None:
            return
        if self._play_stop.is_set():
            worker.provide_kinds(None)
            return
        kinds = _read_kind_count_now()
        if kinds not in (4, 5):
            box = QMessageBox(self)
            box.setWindowTitle("オートプレイ")
            box.setText("種類は何種類ですか？")
            four = box.addButton("4種類", QMessageBox.ButtonRole.AcceptRole)
            five = box.addButton("5種類", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(five)
            box.exec()
            clicked = box.clickedButton()
            if clicked is four:
                kinds = 4
            elif clicked is five:
                kinds = 5
            else:
                worker.provide_kinds(None)
                self._play_stop.set()
                return
        charm = _charm_for_tsum(self._used_tsum_name)
        if charm is None:
            asked = self._ask_charm_tsum()
            if asked is None:
                worker.provide_kinds(None)
                self._play_stop.set()
                return
            charm = asked
        if charm:
            kinds = max(1, int(kinds) - 1)
        worker.provide_kinds(int(kinds))

    def _ask_charm_tsum(self) -> bool | None:
        box = QMessageBox(self)
        box.setWindowTitle("オートプレイ")
        box.setText("チャームツムですか？")
        box.setInformativeText("使うと種類が1つ減ります。")
        yes = box.addButton("はい", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("いいえ", QMessageBox.ButtonRole.NoRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            return True
        if clicked is no:
            return False
        return None

    def _game_count(self) -> tuple[bool, int | None]:
        if self._center_input is None:
            return False, None
        text = self._center_input.currentText().strip()
        if text == "∞":
            return True, None
        if text.isdigit() and int(text) > 0:
            return True, int(text)
        return False, None

    def _fit_center(self) -> None:
        slot = self._center_slot
        if slot is None:
            return
        rect = slot.contentsRect()
        width = rect.width() // 8
        height = rect.height() // 8
        if width < 1 or height < 1:
            return
        button_w = width * 3 // 2
        end_button = self._end_play_button
        if end_button is not None:
            text_w = end_button.fontMetrics().horizontalAdvance(end_button.text())
            text_w += end_button.fontMetrics().height()
            button_w = max(button_w, text_w)
        for button in self._center_buttons:
            if self._launch_button is not None and button is self._launch_button:
                button.setFixedSize(width * 3, height)
            else:
                button.setFixedSize(button_w, height)
        if self._center_input is not None:
            self._center_input.setFixedSize(width, height)
            field = self._center_input.lineEdit()
            if field is not None:
                field.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._center_blank is not None:
            self._center_blank.setFixedSize(width * 6, height * 3)

    def _section_title(self, text: str, top: int = TITLE_MARGIN, bottom: int = TITLE_MARGIN) -> QWidget:
        wrap = QWidget()
        column = QVBoxLayout(wrap)
        column.setContentsMargins(0, top, 0, bottom)
        column.setSpacing(2)
        title = QLabel(text)
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(TITLE_POINT)
        title.setFont(title_font)
        title.setStyleSheet("color: #f4f8ff; background: transparent;")
        title.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        column.addWidget(title)
        bar = QFrame()
        bar.setFixedSize(QFontMetrics(title_font).horizontalAdvance(text), 3)
        bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        bar.setStyleSheet("background-color: #A4C6FF; border: none;")
        column.addWidget(bar, 0, Qt.AlignmentFlag.AlignHCenter)
        return wrap

    def _fit_items(self) -> None:
        box = self._item_box
        if box is None:
            return
        rect = box.contentsRect()
        count = len(self._item_labels)
        if rect.width() <= 1 or count < 1:
            return
        gap = 5
        side = (rect.width() - (count - 1) * gap) * 3 // (4 * count)
        if side < 1:
            return
        for row in self._item_rows:
            row.setSpacing(gap)
        if self._item_block is not None:
            self._item_block.setSpacing(gap)
        for index, label in enumerate(self._item_labels):
            src = self._item_lit[index] if index in self._item_active else self._item_src[index]
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

    def _light_items(self, names: list[str]) -> None:
        found = {name.strip() for name in names if name.strip()}
        self._item_active = {index for index, name in enumerate(ITEM_NAMES) if name in found}
        if not self._item_labels or self._item_labels[0].width() <= 1:
            self._fit_items()
            return
        for index, label in enumerate(self._item_labels):
            src = self._item_lit[index] if index in self._item_active else self._item_src[index]
            if src.isNull():
                label.clear()
                continue
            side = max(label.width(), label.height())
            scaled = src.scaled(
                side,
                side,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(scaled)

    def _on_play_items(self, text: str) -> None:
        if text.strip() in {"", "－", "-"}:
            return
        self._light_items([part.strip() for part in text.split("、")])

    def _open_type_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("設定")
        column = QVBoxLayout(dialog)
        column.addWidget(QLabel("どのモデルを使いますか？"))
        kinds = QRadioButton("PatternType")
        named = QRadioButton("NamedType")
        named.setChecked(_type_model_choice() == "named")
        kinds.setChecked(not named.isChecked())
        column.addWidget(kinds)
        column.addWidget(named)
        gpu = _gpu_label()
        if gpu:
            column.addWidget(QLabel(gpu))
        column.addWidget(QLabel(f"本アプリが動く環境値 {_guide_score()}/100"))
        decide = QPushButton("決定")
        decide.clicked.connect(dialog.accept)
        column.addWidget(decide)

        def save(checked: bool) -> None:
            if not checked:
                return
            QSettings("workshop", "AutoPlay").setValue(
                "tsum_model", "named" if named.isChecked() else "kinds"
            )

        kinds.toggled.connect(save)
        named.toggled.connect(save)
        dialog.exec()
        self._show_model_choice()

    def _show_model_choice(self) -> None:
        label = getattr(self, "_model_choice_label", None)
        if label is None:
            return
        label.setText("NamedType" if _type_model_choice() == "named" else "PatternType")

    def _set_front(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()


def _type_model_choice() -> str:
    stored = str(QSettings("workshop", "AutoPlay").value("tsum_model", "kinds") or "kinds")
    if stored == "named":
        return "named"
    return "kinds"


def _gpu_label() -> str:
    try:
        import torch
        if not torch.cuda.is_available():
            return ""
        name = str(torch.cuda.get_device_name(0) or "").strip()
    except Exception:
        return ""
    if not name:
        return ""
    return f"GPU {name}"


def _ram_bytes() -> int:
    if sys.platform == "win32":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return 0
        return int(status.ullTotalPhys)
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return 0


def _memory_use_percent() -> int | None:
    if sys.platform == "win32":
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return max(0, min(100, int(status.dwMemoryLoad)))
    if sys.platform == "darwin":
        try:
            text = subprocess.check_output(["vm_stat"], text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return None
        page = 4096
        pages: dict[str, int] = {}
        for line in text.splitlines():
            if line.startswith("Mach Virtual Memory Statistics"):
                mark = "page size of "
                if mark in line and "bytes" in line:
                    page = int(line.split(mark, 1)[1].split("bytes", 1)[0].strip())
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            number = value.strip().strip(".").replace(",", "")
            if number.isdigit():
                pages[key.strip()] = int(number)
        total = _ram_bytes()
        if total <= 0 or page <= 0:
            return None
        available = (
            pages.get("Pages free", 0)
            + pages.get("Pages inactive", 0)
            + pages.get("Pages speculative", 0)
        ) * page
        used = max(0, total - available)
        return max(0, min(100, round(used / total * 100)))
    try:
        info = Path("/proc/meminfo").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    mem: dict[str, int] = {}
    for line in info.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            mem[parts[0].rstrip(":")] = int(parts[1])
    total = mem.get("MemTotal", 0)
    available = mem.get("MemAvailable", mem.get("MemFree", 0))
    if total <= 0:
        return None
    return max(0, min(100, round((total - available) / total * 100)))


def _guide_score() -> int:
    ram = _ram_bytes()
    ram_gb = ram / (1024 ** 3) if ram else 0.0
    memory_points = min(40.0, ram_gb / 16 * 40) if ram_gb else 0.0
    cores = os.cpu_count() or 1
    cpu_points = min(30.0, cores / 8 * 30)
    gpu_points = 8.0
    try:
        import torch

        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            vram_gb = int(getattr(props, "total_memory", 0) or 0) / (1024 ** 3)
            gpu_points = min(30.0, 18.0 + vram_gb / 8 * 12)
    except Exception:
        pass
    return max(0, min(100, round(memory_points + cpu_points + gpu_points)))


SCREEN_MODELS = ROOT / "bundled" / "screen" / "data" / "models"
APP_MODEL = ROOT / "models" / "scene.pt"
MODEL_BUTTONS: list[tuple[str, str, Path]] = [
    ("pieces.pt", "〇", SCREEN_MODELS / "pieces.pt"),
    ("tsum_types.pt", "PatternType", SCREEN_MODELS / "tsum_types.pt"),
    ("named_tsum_test.pt", "NamedType", SCREEN_MODELS / "named_tsum_test.pt"),
    ("game_region.pt", "ゲーム範囲", SCREEN_MODELS / "game_region.pt"),
    ("score.pt", "スコア", SCREEN_MODELS / "score.pt"),
    ("coin.pt", "コイン", SCREEN_MODELS / "coin.pt"),
    ("coin_digits.pt", "コインの数字", SCREEN_MODELS / "coin_digits.pt"),
    ("result_coin.pt", "リザルトのコイン", SCREEN_MODELS / "result_coin.pt"),
    ("result_coin_digits.pt", "リザルトの数字", SCREEN_MODELS / "result_coin_digits.pt"),
    ("timer.pt", "タイマー", SCREEN_MODELS / "timer.pt"),
    ("skill.pt", "スキル", SCREEN_MODELS / "skill.pt"),
    ("fan.pt", "扇風機", SCREEN_MODELS / "fan.pt"),
    ("fever.pt", "フィーバー", SCREEN_MODELS / "fever.pt"),
    ("pause.pt", "一時停止", SCREEN_MODELS / "pause.pt"),
    ("scene.pt", "シーン", APP_MODEL),
]


_ITEM_CHECK = r"""
import json
import sys
from PySide6.QtWidgets import QApplication
sys.path.insert(0, sys.argv[1])
QApplication([])
from app.bluestacks import capture_screen_path
from app.play import _items_used_path
try:
    items = _items_used_path(capture_screen_path())
except Exception as exc:
    print(json.dumps({"error": str(exc)}, ensure_ascii=False))
else:
    print(json.dumps({"items": items}, ensure_ascii=False))
"""


def _recognized_items() -> dict:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [sys.executable, "-c", _ITEM_CHECK, str(ROOT)],
        check=False,
        capture_output=True,
        text=True,
        creationflags=flags,
    )
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines:
        err = (result.stderr or "").strip().splitlines()
        return {"error": err[-1] if err else "アイテムの画面を認識できませんでした。"}
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"error": "アイテムの画面を認識できませんでした。"}
    return payload if isinstance(payload, dict) else {"error": "アイテムの画面を認識できませんでした。"}


def _load_play_api():
    root = str(ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    for key in list(sys.modules):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    from app.bluestacks import start_tsum, tsum_is_running
    from app.intro import IntroWorker
    from app.play import PlayWorker, read_kind_count

    return start_tsum, tsum_is_running, IntroWorker, PlayWorker, read_kind_count


def _start_play_here(window: MenuWindow, games: int | None) -> None:
    if window._play_worker is not None and window._play_worker.isRunning():
        return
    if window._intro is not None and window._intro.isRunning():
        return
    if window._play_api is None:
        window._play_api = _load_play_api()
    start_tsum, tsum_is_running, _intro_cls, _play_cls, _read_kinds = window._play_api
    window._play_games = games
    window._play_stop.clear()
    if not tsum_is_running():
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        try:
            start_tsum(desktop or "")
        except Exception as exc:  # noqa: BLE001
            window._set_activity(str(exc))
            QMessageBox.critical(window, "オートプレイ", str(exc))
            return
        intro = _intro_cls(window._play_stop, window)
        intro.status.connect(window._set_activity)
        intro.succeeded.connect(window._on_intro_ok)
        intro.failed.connect(window._on_intro_fail)
        intro.stopped.connect(window._on_play_stopped)
        window._intro = intro
        window._register_stop_hotkey()
        intro.start()
        return
    _start_match(window)


def _used_tsum_names() -> list[str]:
    path = ROOT / "bundled" / "assets" / "models" / "use_tsum" / "registry.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    if not isinstance(payload, dict):
        return []
    names = [str(value).strip() for value in payload.values() if str(value).strip()]
    return sorted(set(names), key=lambda value: value.casefold())


_TSUM_ICON_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _used_tsum_icon_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or Path(cleaned).name != cleaned:
        return ""
    return cleaned


def _used_tsum_icon_file(name: str) -> Path | None:
    safe = _used_tsum_icon_name(name)
    if not safe or not TSUM_ICON_DIR.is_dir():
        return None
    for path in TSUM_ICON_DIR.iterdir():
        if path.is_file() and path.stem == safe and path.suffix.lower() in _TSUM_ICON_EXTS:
            return path
    return None


def _used_tsum_icon_present(name: str) -> bool:
    return _used_tsum_icon_file(name) is not None


def _tsum_icon_filename(payload: object, name: str) -> str:
    if not isinstance(payload, dict):
        return ""
    icons = payload.get("icons")
    if not isinstance(icons, list):
        return ""
    for item in icons:
        if not isinstance(item, dict):
            continue
        matched = False
        names = item.get("tsum_names")
        if isinstance(names, list) and name in {str(value) for value in names}:
            matched = True
        if not matched:
            links = item.get("links")
            if isinstance(links, list):
                for link in links:
                    if isinstance(link, dict) and str(link.get("name") or "") == name:
                        matched = True
                        break
        if not matched:
            continue
        filename = Path(str(item.get("filename") or "")).name
        if filename and filename not in {".", ".."}:
            return filename
    return ""


def _fetch_used_tsum_icon(name: str, on_saved=None) -> None:
    safe = _used_tsum_icon_name(name)
    if not safe or _used_tsum_icon_present(safe):
        return
    try:
        request = urllib.request.Request(TSUM_ICON_LIST_URL)
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        filename = _tsum_icon_filename(payload, safe)
        if not filename:
            return
        ext = Path(filename).suffix.lower()
        if ext not in _TSUM_ICON_EXTS:
            return
        image_url = TSUM_ICON_FILE_URL + urllib.parse.quote(filename)
        image_request = urllib.request.Request(image_url)
        with urllib.request.urlopen(image_request, timeout=20) as response:
            data = response.read()
            content_type = str(response.headers.get("Content-Type") or "")
        if not data:
            return
        if content_type and not content_type.lower().startswith("image/"):
            return
        if _used_tsum_icon_present(safe):
            return
        TSUM_ICON_DIR.mkdir(parents=True, exist_ok=True)
        dest = TSUM_ICON_DIR / f"{safe}{ext}"
        temporary = dest.with_name(dest.name + ".part")
        temporary.write_bytes(data)
        temporary.replace(dest)
        if on_saved is not None:
            on_saved(safe)
    except (OSError, json.JSONDecodeError, UnicodeError, urllib.error.URLError, TimeoutError):
        return


def _save_used_tsum(path: Path | None, name: str, folder_id: str | None) -> str:
    from app.play import register_used_tsum_id, save_used_tsum_teach

    if path is not None and path.is_file():
        return save_used_tsum_teach(path, name, folder_id)
    if folder_id:
        return register_used_tsum_id(name, folder_id)
    return name


def _read_kind_count_now() -> int | None:
    from app.play import read_kind_count

    try:
        found = read_kind_count()
    except Exception:
        return None
    if found in (4, 5):
        return int(found)
    return None


def _charm_for_tsum(name: str) -> bool | None:
    from app.main_window import _is_not_charm_tsum, _tsum_meta_for_name

    saved = _tsum_meta_for_name(name)
    if saved is not None and isinstance(saved.get("charm"), bool):
        return bool(saved["charm"])
    if _is_not_charm_tsum(name):
        return False
    return None


def _start_match(window: MenuWindow) -> None:
    if window._play_api is None:
        return
    _start_tsum, _running, _intro_cls, play_cls, _read_kinds = window._play_api
    worker = play_cls(
        window._play_stop,
        window,
        start_match=True,
        loop=True,
        ask_kinds=True,
        games=window._play_games,
        use_named=_type_model_choice() == "named",
    )
    worker.status.connect(window._set_activity)
    worker.recognized.connect(window._show_tsum_recognition)
    worker.flow.connect(window._set_flow_lamp)
    worker.recorded.connect(window._show_game_record)
    worker.items.connect(window._on_play_items)
    worker.need_used_tsum.connect(window._on_need_used_tsum)
    worker.need_kinds.connect(window._on_need_kinds)
    worker.failed.connect(window._on_play_fail)
    worker.completed.connect(window._on_play_done)
    worker.stopped.connect(window._on_play_stopped)
    window._used_tsum_name = ""
    window._play_worker = worker
    window._register_stop_hotkey()
    worker.start()


def _bluestacks_running() -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq HD-Player.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=flags,
    )
    return "HD-Player.exe" in (result.stdout or "")


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
    if stored:
        return stored
    try:
        from app.server_sync import api_token
    except Exception:
        return "kumadesk-workshop-local"
    return str(api_token() or "").strip() or "kumadesk-workshop-local"


def _server_model_shas(token: str) -> dict[str, str]:
    query = urllib.parse.urlencode({"action": "manifest"})
    request = urllib.request.Request(
        f"{MODELS_API}?{query}",
        headers={"X-Workshop-Token": token},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not payload.get("ok"):
        return {}
    found: dict[str, str] = {}
    for item in payload.get("files") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("path") or "")
        sha = str(item.get("sha1") or "")
        if name and sha:
            found[name] = sha
    return found


def app_use_allowed(token: str) -> tuple[bool, str] | None:
    if not token:
        return None
    query = urllib.parse.urlencode({"action": "app", "t": str(time.time_ns())})
    request = urllib.request.Request(
        f"{MODELS_API}?{query}",
        headers={
            "X-Workshop-Token": token,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("ok") or "use" not in payload:
        return None
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        message = "ただいまメンテナンス中です。"
    return bool(payload.get("use")), message


def model_updates(token: str) -> dict[str, bool]:
    try:
        remote = _server_model_shas(token)
    except (OSError, json.JSONDecodeError, UnicodeError):
        return {name: False for name, _label, _dest in MODEL_BUTTONS}
    flags: dict[str, bool] = {}
    for name, _label, dest in MODEL_BUTTONS:
        remote_sha = remote.get(name, "")
        local_sha = _file_sha1(dest) if dest.is_file() else ""
        flags[name] = bool(remote_sha) and remote_sha != local_sha
    return flags


def _import_server_model(token: str, name: str, dest: Path) -> None:
    query = urllib.parse.urlencode({"action": "file", "path": name})
    request = urllib.request.Request(
        f"{MODELS_API}?{query}",
        headers={"X-Workshop-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            remote_sha = str(response.headers.get("X-Workshop-Sha1") or "")
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()
        raise RuntimeError(detail or "モデルを取り込めませんでした。") from exc
    digest = hashlib.sha1(data).hexdigest()
    if remote_sha and digest != remote_sha:
        raise RuntimeError("受け取ったモデルがサーバーのモデルと違います。")
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(".pt.part")
    temporary.write_bytes(data)
    temporary.replace(dest)


def _git_in_app(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def app_update_available() -> bool:
    try:
        inside = _git_in_app(["rev-parse", "--is-inside-work-tree"])
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        fetched = _git_in_app(["fetch", "origin", "master"])
        if fetched.returncode != 0:
            return False
        missing = _git_in_app(["rev-list", "--count", "HEAD..FETCH_HEAD"])
        if missing.returncode != 0:
            return False
        return int(missing.stdout.strip() or "0") > 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def _names_from_git(result: subprocess.CompletedProcess[str]) -> set[str]:
    if result.returncode != 0:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def _restore_update_files() -> subprocess.CompletedProcess[str] | None:
    local = _git_in_app(["diff", "--name-only", "HEAD"])
    incoming = _git_in_app(["diff", "--name-only", "HEAD", "FETCH_HEAD"])
    blocked = sorted(_names_from_git(local) & _names_from_git(incoming))
    if not blocked:
        return None
    return _git_in_app(["checkout", "HEAD", "--", *blocked])


def _schedule_relaunch() -> None:
    exe = str(sys.executable)
    main = str(ROOT / "main.py")
    pid = os.getpid()
    code = (
        "import os,subprocess,time\n"
        f"pid={pid}\n"
        "while True:\n"
        "    try:\n"
        "        os.kill(pid, 0)\n"
        "    except OSError:\n"
        "        break\n"
        "    time.sleep(0.2)\n"
        f"subprocess.Popen([{exe!r}, {main!r}], cwd={str(ROOT)!r})\n"
    )
    flags = 0
    if sys.platform == "win32":
        flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    subprocess.Popen(
        [exe, "-c", code],
        cwd=str(ROOT),
        creationflags=flags,
        close_fds=True,
    )


def _pull_app_update() -> tuple[bool, str]:
    try:
        fetched = _git_in_app(["fetch", "origin", "master"])
        if fetched.returncode != 0:
            detail = (fetched.stderr or fetched.stdout or "更新できませんでした。").strip()
            return False, detail
        restored = _restore_update_files()
        if restored is not None and restored.returncode != 0:
            detail = (restored.stderr or restored.stdout or "更新できませんでした。").strip()
            return False, detail
        result = _git_in_app(["pull", "origin", "master"])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "更新できませんでした。").strip()
        return False, detail
    return True, ""


class _AppUseCheck(QThread):
    found = Signal(object)

    def __init__(self, token: str, parent=None) -> None:
        super().__init__(parent)
        self._token = token

    def run(self) -> None:
        state = None
        for _ in range(3):
            state = app_use_allowed(self._token)
            if state is not None:
                break
        self.found.emit(state)


class _AppUpdateCheck(QThread):
    found = Signal(bool)

    def run(self) -> None:
        self.found.emit(app_update_available())


class _ModelUpdateCheck(QThread):
    found = Signal(object)

    def __init__(self, token: str, parent=None) -> None:
        super().__init__(parent)
        self._token = token

    def run(self) -> None:
        self.found.emit(model_updates(self._token))


class _ItemCheck(QThread):
    found = Signal(object)

    def run(self) -> None:
        self.found.emit(_recognized_items())


class _ModelFetch(QThread):
    finished_import = Signal(bool, str)

    def __init__(self, token: str, name: str, dest: Path, parent=None) -> None:
        super().__init__(parent)
        self._token = token
        self._name = name
        self._dest = dest

    def run(self) -> None:
        try:
            _import_server_model(self._token, self._name, self._dest)
        except (OSError, RuntimeError) as exc:
            self.finished_import.emit(False, str(exc))
            return
        self.finished_import.emit(True, "")


def _lock_path() -> Path:
    return Path(QDir.tempPath()) / f"{MENU_IPC}.lock"


def _lock_holder_pid(lock: QLockFile) -> int:
    try:
        pid, _hostname, _app = lock.getLockInfo()
    except Exception:
        return 0
    try:
        return int(pid or 0)
    except Exception:
        return 0


def _handoff_to_running() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(MENU_IPC)
    if not sock.waitForConnected(400):
        return False
    sock.write(b'{"raise":true}\n')
    sock.waitForBytesWritten(800)
    if not sock.waitForReadyRead(800):
        sock.disconnectFromServer()
        return False
    reply = bytes(sock.readAll())
    sock.disconnectFromServer()
    return b'"ok"' in reply


def _lock_holder_dead(lock: QLockFile) -> bool:
    pid = _lock_holder_pid(lock)
    if pid <= 0:
        return True
    try:
        os.kill(int(pid), 0)
        return False
    except OSError:
        return True


def _acquire_instance_lock() -> QLockFile | None:
    lock = QLockFile(str(_lock_path()))
    if lock.tryLock(100):
        return lock
    if _lock_holder_dead(lock):
        lock.removeStaleLockFile()
        if lock.tryLock(100):
            return lock
    if lock.removeStaleLockFile() and lock.tryLock(100):
        return lock
    return None


def _python_for_pip() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return console
    return exe


def _ensure_pillow() -> None:
    try:
        import PIL.Image  # noqa: F401
        return
    except ModuleNotFoundError:
        sys.modules.pop("PIL", None)
    exe = _python_for_pip()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        [str(exe), "-m", "pip", "install", "Pillow"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=flags,
    )
    sys.modules.pop("PIL", None)


def main() -> None:
    _ensure_pillow()
    app = QApplication(sys.argv)
    try:
        import PIL.Image  # noqa: F401
    except ModuleNotFoundError:
        exe = _python_for_pip()
        QMessageBox.critical(
            None,
            "Pillow",
            "Pillow が入っていません。\n" + f'"{exe}" -m pip install Pillow',
        )
    lock = _acquire_instance_lock()
    if lock is None:
        if not _handoff_to_running():
            QMessageBox.information(
                None,
                "すでに起動しています",
                "メニューは、すでに開いています。",
            )
        sys.exit(0)
    app._instance_lock = lock
    QLocalServer.removeServer(MENU_IPC)
    window = MenuWindow()
    window._start_ipc()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
