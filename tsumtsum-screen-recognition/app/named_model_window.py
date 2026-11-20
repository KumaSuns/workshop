from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
import re

from PySide6.QtCore import QEvent, QRect, QSettings, Qt, QStandardPaths, QThread, QTimer, Signal
from PySide6.QtGui import QClipboard, QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from app.paths import APP_ROOT, DATA_DIR, IMAGE_EXTENSIONS, SERVER_SYNC_PATH
from app.regions import PIECE_COLORS, is_tsum_kind, tsum_group_color

NAMED_MODEL_ARG = "--named-model"
NAMED_MODEL_ICON = APP_ROOT / "named_model.ico"


def _registered_marks() -> tuple[set[str], set[str]]:
    from app.named_tsum_test import VER01_IMAGE_DIR

    named: set[str] = set()
    not_tsum: set[str] = set()
    if not VER01_IMAGE_DIR.is_dir():
        return named, not_tsum
    for path in VER01_IMAGE_DIR.rglob("*.png"):
        matched = re.fullmatch(r"(.+)_\d+_\d+", path.stem)
        if not matched:
            continue
        if path.parent.name == "ツムではない":
            not_tsum.add(matched.group(1))
        else:
            named.add(matched.group(1))
    return named, not_tsum


class _RegisteredFileDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
        number = str(index.data(Qt.ItemDataRole.UserRole + 1) or "")
        name = str(index.data(Qt.ItemDataRole.UserRole) or "")
        registered = bool(index.data(Qt.ItemDataRole.UserRole + 2))
        not_tsum = bool(index.data(Qt.ItemDataRole.UserRole + 3))
        color = option.palette.highlightedText().color() if selected else option.palette.text().color()
        painter.setPen(color)
        metrics = QFontMetrics(option.font)
        text_y = option.rect.top()
        text_h = option.rect.height()
        rows = index.model().rowCount() if index.model() is not None else 1
        number_w = metrics.horizontalAdvance("0" * max(2, len(str(rows))))
        painter.drawText(
            QRect(option.rect.left() + 4, text_y, number_w, text_h),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            number,
        )
        diameter = 10
        x = option.rect.left() + 4 + number_w + 6
        if registered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#E10600"))
            painter.drawEllipse(x, option.rect.center().y() - diameter // 2, diameter, diameter)
        x += diameter + 6
        if not_tsum:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#21A336"))
            painter.drawEllipse(x, option.rect.center().y() - diameter // 2, diameter, diameter)
        x += diameter + 6
        painter.setPen(color)
        painter.drawText(
            QRect(x, text_y, max(1, option.rect.right() - x), text_h),
            Qt.AlignmentFlag.AlignVCenter,
            name,
        )
        painter.restore()


class _CircleStrip(QWidget):
    CELL = 52
    GAP = 4
    LABEL = 28
    NAME_H = 22

    picked = Signal()
    assigned = Signal(str)
    opened = Signal(str)
    name_menu = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, QColor, str, list[tuple[QPixmap, dict]]]] = []
        self._wrap = 1
        self._edits: dict[str, QLineEdit] = {}
        self._name_btns: dict[str, QPushButton] = {}
        self._picked: dict | None = None
        self._gallery: list[QPixmap] = []
        self._named_groups: list[tuple[str, list[tuple[QPixmap, Path]]]] = []
        self._saved_path: Path | None = None
        self._saved_paths: set[Path] = set()
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    def clear_rows(self) -> None:
        self._rows = []
        self._gallery = []
        self._named_groups = []
        self._picked = None
        for edit in self._edits.values():
            edit.hide()
        for button in self._name_btns.values():
            button.hide()
        self.setFixedSize(1, 1)
        self.picked.emit()
        self.update()

    def select_piece(self, piece: dict) -> None:
        self._picked = piece
        self.setFocus()
        self.picked.emit()
        self.update()

    def picked_piece(self) -> dict | None:
        return self._picked

    def edited_names(self) -> dict[str, str]:
        return {key: edit.text().strip() for key, edit in self._edits.items() if edit.isVisible()}

    def set_rows(self, pixmap: QPixmap, pieces: list[dict], names: dict[str, str]) -> None:
        self._picked = None
        self._gallery = []
        self._named_groups = []
        grouped: dict[str, list[tuple[QPixmap, dict]]] = {}
        for piece in pieces:
            key = "B" if piece.get("kind") == "bomb" else str(int(piece.get("group") or 1))
            grouped.setdefault(key, []).append((self._crop(pixmap, piece), piece))

        def sort_key(key: str) -> tuple[int, int]:
            if key == "B":
                return (1, 0)
            return (0, int(key))

        rows = []
        for key in sorted(grouped, key=sort_key):
            color = QColor("#FF5C5C") if key == "B" else QColor(tsum_group_color(int(key)))
            label = names.get(key) or "ボム" if key == "B" else names.get(key, "")
            rows.append((key, color, label, grouped[key]))
        self._rows = rows
        self._saved_path = None
        self._saved_paths = set()
        self._sync_edits()
        self._apply_size()
        self.picked.emit()

    def show_images(self, tiles: list[QPixmap]) -> None:
        self._rows = []
        self._picked = None
        self._gallery = tiles
        self._named_groups = []
        self._saved_path = None
        self._saved_paths = set()
        for edit in self._edits.values():
            edit.hide()
        for button in self._name_btns.values():
            button.hide()
        self._apply_size()
        self.picked.emit()

    def saved_path(self) -> Path | None:
        return self._saved_path

    def showing_saved(self) -> bool:
        return bool(self._named_groups)

    def saved_paths(self) -> list[Path]:
        return list(self._saved_paths)

    def show_named(self, groups: list[tuple[str, list[tuple[QPixmap, Path]]]]) -> None:
        self._rows = []
        self._picked = None
        self._gallery = []
        self._named_groups = groups
        self._saved_path = None
        self._saved_paths = set()
        for edit in self._edits.values():
            edit.hide()
        for button in self._name_btns.values():
            button.hide()
        self._apply_size()
        self.picked.emit()

    def set_row_name(self, key: str, name: str) -> None:
        edit = self._edits.get(key)
        if edit is None or not edit.isVisible():
            return
        edit.setText(name)

    def name_button(self, key: str) -> QPushButton | None:
        button = self._name_btns.get(key)
        if button is None or not button.isVisible():
            return None
        return button

    def set_wrap_width(self, width: int) -> None:
        self._wrap = max(1, width)
        self._apply_size()

    def _per_row(self) -> int:
        room = max(self.CELL, self._wrap - self.LABEL)
        return max(1, room // (self.CELL + self.GAP))

    def _apply_size(self) -> None:
        if self._named_groups:
            per = max(1, (self._wrap - self.GAP) // (self.CELL + self.GAP))
            height = self.GAP
            for _name, tiles in self._named_groups:
                lines = max(1, (len(tiles) + per - 1) // per)
                height += self.NAME_H + lines * (self.CELL + self.GAP)
            self.setFixedSize(max(self._wrap, self.CELL), height)
            self.update()
            return
        if self._gallery:
            per = max(1, self._wrap // (self.CELL + self.GAP))
            lines = max(1, (len(self._gallery) + per - 1) // per)
            height = lines * (self.CELL + self.GAP) + self.GAP
            self.setFixedSize(max(self._wrap, self.CELL), height)
            self.update()
            return
        if not self._rows:
            self.setFixedSize(1, 1)
            self.update()
            return
        lines = 0
        name_lines = 0
        per = self._per_row()
        for key, _color, _name, tiles in self._rows:
            name_lines += 1
            lines += max(1, (len(tiles) + per - 1) // per)
        height = name_lines * self.NAME_H + lines * (self.CELL + self.GAP) + self.GAP
        self.setFixedSize(max(self._wrap, self.LABEL + self.CELL), height)
        self._place_edits()
        self.update()

    def _sync_edits(self) -> None:
        alive = {key for key, _color, _name, _tiles in self._rows}
        for key, _color, name, _tiles in self._rows:
            edit = self._edits.get(key)
            if edit is None:
                edit = QLineEdit(self)
                edit.setFont(QFont("Yu Gothic UI", 11, QFont.Weight.Bold))
                edit.setStyleSheet("QLineEdit { background: #FFFFFF; color: #101216; }")
                self._edits[key] = edit
            edit.setText(name)
            button = self._name_btns.get(key)
            if button is None:
                button = QPushButton(self)
                button.setFixedSize(self.NAME_H, self.NAME_H)
                button.clicked.connect(lambda _checked=False, row_key=key: self.name_menu.emit(row_key))
                self._name_btns[key] = button
        for key, edit in self._edits.items():
            if key not in alive:
                edit.hide()
        for key, button in self._name_btns.items():
            if key not in alive:
                button.hide()

    def _place_edits(self) -> None:
        per = self._per_row()
        y = self.GAP
        for key, _color, _name, tiles in self._rows:
            edit = self._edits[key]
            button = self._name_btns[key]
            button.setGeometry(0, y, self.NAME_H, self.NAME_H)
            button.show()
            edit.setGeometry(self.NAME_H, y, max(1, self.width() - self.NAME_H), self.NAME_H)
            edit.show()
            y += self.NAME_H
            lines = max(1, (len(tiles) + per - 1) // per)
            y += lines * (self.CELL + self.GAP)

    def _crop(self, pixmap: QPixmap, piece: dict) -> QPixmap:
        x, y = int(piece["x"]), int(piece["y"])
        radius = max(8, int(piece.get("r") or 16))
        span = max(12, int(round(radius * 1.05)))
        tile = pixmap.copy(QRect(x - span, y - span, span * 2, span * 2))
        if tile.isNull():
            return QPixmap()
        return tile.scaled(
            self.CELL,
            self.CELL,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
        if self._named_groups:
            per = max(1, (self._wrap - self.GAP) // (self.CELL + self.GAP))
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Yu Gothic UI", 11, QFont.Weight.DemiBold))
            y = self.GAP
            for name, tiles in self._named_groups:
                painter.drawText(QRect(self.GAP, y, max(1, self._wrap - self.GAP), self.NAME_H), Qt.AlignmentFlag.AlignVCenter, name)
                y += self.NAME_H
                column = 0
                x = self.GAP
                for tile, path in tiles:
                    chosen = path in self._saved_paths
                    if not tile.isNull():
                        painter.drawPixmap(x, y, tile)
                    painter.setPen(QPen(QColor("#FFFFFF") if chosen else QColor("#F0A202"), 4 if chosen else 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(x, y, self.CELL - 1, self.CELL - 1)
                    painter.setPen(QColor("#FFFFFF"))
                    column += 1
                    if column >= per:
                        column = 0
                        x = self.GAP
                        y += self.CELL + self.GAP
                    else:
                        x += self.CELL + self.GAP
                if column:
                    y += self.CELL + self.GAP
            return
        if self._gallery:
            per = max(1, self._wrap // (self.CELL + self.GAP))
            x = self.GAP
            y = self.GAP
            column = 0
            for tile in self._gallery:
                if not tile.isNull():
                    painter.drawPixmap(x, y, tile)
                painter.setPen(QPen(QColor("#21A336"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(x, y, self.CELL - 1, self.CELL - 1)
                column += 1
                if column >= per:
                    column = 0
                    x = self.GAP
                    y += self.CELL + self.GAP
                else:
                    x += self.CELL + self.GAP
            return
        if not self._rows:
            return
        painter.setFont(QFont("Yu Gothic UI", 11, QFont.Weight.DemiBold))
        per = self._per_row()
        y = self.GAP
        for key, color, _name, tiles in self._rows:
            y += self.NAME_H
            for start in range(0, len(tiles), per):
                chunk = tiles[start : start + per]
                if start == 0:
                    painter.setPen(color)
                    painter.drawText(
                        QRect(0, y, self.LABEL, self.CELL),
                        Qt.AlignmentFlag.AlignCenter,
                        key,
                    )
                x = self.LABEL
                for tile, piece in chunk:
                    if not tile.isNull():
                        painter.drawPixmap(x, y, tile)
                    chosen = piece is self._picked
                    painter.setPen(QPen(QColor("#FFFFFF") if chosen else color, 4 if chosen else 2))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawRect(x, y, self.CELL - 1, self.CELL - 1)
                    x += self.CELL + self.GAP
                y += self.CELL + self.GAP

    def mousePressEvent(self, event) -> None:
        saved = self._saved_at(int(event.position().x()), int(event.position().y()))
        if saved is not None:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                if saved in self._saved_paths:
                    self._saved_paths.discard(saved)
                else:
                    self._saved_paths.add(saved)
            else:
                self._saved_paths = {saved}
            self._saved_path = saved if saved in self._saved_paths else None
            self.setFocus()
            self.update()
            return
        piece = self._piece_at(int(event.position().x()), int(event.position().y()))
        if piece is None:
            return
        self._picked = piece
        self.setFocus()
        self.picked.emit()
        self.update()

    def keyPressEvent(self, event) -> None:
        number = event.text()
        if self._picked is not None and (number.isdigit() or number in {"b", "B"}):
            self.assigned.emit("B" if number in {"b", "B"} else number)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        saved = self._saved_at(int(event.position().x()), int(event.position().y()))
        if saved is None:
            return
        matched = re.fullmatch(r"(.+)_\d+_\d+", saved.stem)
        if matched is None:
            return
        self.opened.emit(matched.group(1))
        event.accept()

    def _saved_at(self, px: int, py: int) -> Path | None:
        if not self._named_groups:
            return None
        per = max(1, (self._wrap - self.GAP) // (self.CELL + self.GAP))
        y = self.GAP
        for _name, tiles in self._named_groups:
            y += self.NAME_H
            column = 0
            x = self.GAP
            for _tile, path in tiles:
                if x <= px < x + self.CELL and y <= py < y + self.CELL:
                    return path
                column += 1
                if column >= per:
                    column = 0
                    x = self.GAP
                    y += self.CELL + self.GAP
                else:
                    x += self.CELL + self.GAP
            if column:
                y += self.CELL + self.GAP
        return None

    def _piece_at(self, px: int, py: int) -> dict | None:
        per = self._per_row()
        y = self.GAP
        for key, _color, _name, tiles in self._rows:
            y += self.NAME_H
            for start in range(0, len(tiles), per):
                chunk = tiles[start : start + per]
                x = self.LABEL
                for _tile, piece in chunk:
                    if x <= px < x + self.CELL and y <= py < y + self.CELL:
                        return piece
                    x += self.CELL + self.GAP
                y += self.CELL + self.GAP
        return None


class _Ver01TrainThread(QThread):
    failed = Signal(str)
    done = Signal(str)
    cancelled = Signal()
    progressed = Signal(int, str)

    def __init__(self, rows: list) -> None:
        super().__init__()
        self._rows = rows
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            from app.named_tsum_test import VER01_MODEL_PATH, NamedTrainingCancelled, train

            def on_fraction(percent: int, text: str) -> None:
                self.progressed.emit(int(percent), str(text))

            train(
                path=VER01_MODEL_PATH,
                rows=self._rows,
                on_fraction=on_fraction,
                should_stop=lambda: self._stop,
            )
        except NamedTrainingCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc).strip() or "学習できませんでした。")
            return
        self.progressed.emit(100, "終わりました")
        self.done.emit(str(VER01_MODEL_PATH))


class _Ver01Progress(QWidget):
    def __init__(self, main_window: QWidget) -> None:
        super().__init__(None)
        self._main_window = main_window
        self.setWindowTitle("学習")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setFixedSize(560, 210)
        self._running = True
        self._thread: _Ver01TrainThread | None = None
        self.setStyleSheet(
            "QWidget { background: #FFF6D8; }"
            "QLabel#score { color: #E23B2F; font-size: 28px; font-weight: 700; }"
            "QLabel#detail { color: #35507A; font-size: 14px; }"
            "QProgressBar { border: 3px solid #F0A202; border-radius: 11px;"
            " background: #FFFFFF; min-height: 22px; max-height: 22px; }"
            "QProgressBar::chunk { background: #3EC1FF; border-radius: 8px; }"
            "QPushButton { border: 3px solid #F0A202; border-radius: 11px;"
            " background: #FFFFFF; color: #35507A; font-size: 14px; font-weight: 700;"
            " min-width: 120px; min-height: 32px; }"
            "QPushButton:disabled { color: #B0B8C4; border-color: #E4D7A8; }"
            "QCheckBox { color: #35507A; font-size: 14px; font-weight: 700; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 8, 18, 8)
        layout.setSpacing(6)
        self.percent = QLabel("0%")
        self.percent.setObjectName("score")
        self.percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.detail = QLabel("準備しています")
        self.detail.setObjectName("detail")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setFixedHeight(36)
        self.shutdown_box = QCheckBox("終わったらシャットダウン")
        self.cancel_btn = QPushButton("中止")
        self.cancel_btn.clicked.connect(self._cancel)
        self.main_btn = QPushButton("メインウィンドウ")
        self.main_btn.clicked.connect(self._show_main)
        self.close_btn = QPushButton("とじる")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.setSpacing(12)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.main_btn)
        buttons.addWidget(self.close_btn)
        layout.addWidget(self.percent)
        layout.addWidget(self.bar)
        layout.addWidget(self.detail)
        layout.addWidget(self.shutdown_box, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addLayout(buttons)

    def is_running(self) -> bool:
        return self._running

    def attach(self, thread: _Ver01TrainThread) -> None:
        self._thread = thread
        thread.progressed.connect(self.set_progress)
        thread.done.connect(self.mark_done)
        thread.cancelled.connect(self.mark_cancelled)
        thread.failed.connect(self.mark_failed)

    def set_progress(self, percent: int, text: str) -> None:
        self.bar.setValue(int(percent))
        self.percent.setText(f"{int(percent)}%")
        self.detail.setText(text)

    def mark_done(self, path: str) -> None:
        self._running = False
        self.bar.setValue(100)
        self.percent.setText("100%")
        shown = QFontMetrics(self.detail.font()).elidedText(
            path, Qt.TextElideMode.ElideMiddle, max(1, self.detail.width())
        )
        self.detail.setText(f"終わりました\n{shown}")
        self.cancel_btn.setEnabled(False)
        self.shutdown_box.setEnabled(False)
        self.close_btn.setEnabled(True)
        if self.shutdown_box.isChecked():
            subprocess.run(["shutdown", "/s", "/t", "0"], check=False)
        self._bring_forward()

    def _show_main(self) -> None:
        window = self._main_window
        window.show()
        window.raise_()
        window.activateWindow()

    def _cancel(self) -> None:
        if self._thread is None or not self._running:
            return
        self.cancel_btn.setEnabled(False)
        self.detail.setText("中止しています")
        self._thread.request_stop()

    def mark_cancelled(self) -> None:
        self._running = False
        self.cancel_btn.setEnabled(False)
        self.shutdown_box.setEnabled(False)
        self.close_btn.setEnabled(True)
        self.detail.setText("中止しました")

    def _bring_forward(self) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.show()

    def mark_failed(self, message: str) -> None:
        self._running = False
        self.cancel_btn.setEnabled(False)
        self.shutdown_box.setEnabled(False)
        self.close_btn.setEnabled(True)
        shown = QFontMetrics(self.detail.font()).elidedText(
            message, Qt.TextElideMode.ElideRight, max(1, self.detail.width())
        )
        self.detail.setText(shown)

    def closeEvent(self, event) -> None:
        if self._running:
            event.ignore()
            return
        super().closeEvent(event)


_ver01_progress: _Ver01Progress | None = None


def _ask_ver01_start(clock: str, faces: int, kinds: int) -> bool:
    dialog = QDialog(None)
    dialog.setWindowTitle("学習")
    dialog.setFixedSize(420, 168)
    dialog.setStyleSheet(
        "QDialog { background: #FFF6D8; }"
        "QLabel#score { color: #E23B2F; font-size: 28px; font-weight: 700; }"
        "QLabel#detail { color: #35507A; font-size: 14px; }"
        "QPushButton { border: 3px solid #F0A202; border-radius: 11px;"
        " background: #FFFFFF; color: #35507A; font-size: 14px; font-weight: 700;"
        " min-width: 120px; min-height: 36px; }"
        "QPushButton#go { background: #3EC1FF; color: #FFFFFF; }"
    )
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(8)
    score = QLabel(f"予測 {clock}")
    score.setObjectName("score")
    score.setAlignment(Qt.AlignmentFlag.AlignCenter)
    detail = QLabel(f"顔 {faces} 枚、名前 {kinds} 個。\n学習を始めますか？")
    detail.setObjectName("detail")
    detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
    detail.setFixedHeight(40)
    buttons = QHBoxLayout()
    buttons.setSpacing(12)
    go = QPushButton("実行")
    go.setObjectName("go")
    cancel = QPushButton("キャンセル")
    buttons.addStretch(1)
    buttons.addWidget(go)
    buttons.addWidget(cancel)
    buttons.addStretch(1)
    layout.addWidget(score)
    layout.addWidget(detail)
    layout.addLayout(buttons)
    go.clicked.connect(dialog.accept)
    cancel.clicked.connect(dialog.reject)
    return dialog.exec() == QDialog.DialogCode.Accepted


class NamedModelWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NamedModel")
        if NAMED_MODEL_ICON.is_file():
            self.setWindowIcon(QIcon(str(NAMED_MODEL_ICON)))
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        shortcut = QPushButton("起動アイコン作成")
        shortcut.clicked.connect(self.create_launch_shortcut)
        self.shortcut_btn = shortcut
        layout.addWidget(shortcut, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addStretch(1)
        self.file_count = QLabel(central)
        self.file_mark = QLabel(central)
        self.file_mark.setTextFormat(Qt.TextFormat.RichText)
        self.file_mark.setText(
            '<span style="color:#E10600">●</span> 登録'
            '　<span style="color:#21A336">●</span> ツムではない'
        )
        self.button_window = QFrame(central)
        self.button_window.setObjectName("buttonWindow")
        self.button_window.setFrameShape(QFrame.Shape.Box)
        self.button_window.setLineWidth(1)
        self.button_window.setStyleSheet(
            "QPushButton:checked { background: #3EC1FF; color: #FFFFFF; border: 3px solid #F0A202; }"
        )
        self.number_buttons: list[QPushButton] = []
        for number in range(1, 19):
            button = QPushButton(str(number), self.button_window)
            self.number_buttons.append(button)
        self.number_buttons[0].setText("Circle Mark\nOLD")
        self.number_buttons[0].clicked.connect(lambda: self._mark_circles(False))
        self.number_buttons[1].setText("Circle Mark\nNEW")
        self.number_buttons[1].clicked.connect(lambda: self._mark_circles(True))
        self.number_buttons[12].setText("画像済み")
        self.number_buttons[12].clicked.connect(self._show_saved_faces)
        self.number_buttons[14].setText("ボム一覧")
        self.number_buttons[14].clicked.connect(self._show_registered_bombs)
        self.number_buttons[15].setText("ツムではない")
        self.number_buttons[15].clicked.connect(self._show_not_tsum_images)
        self.number_buttons[16].setText("サーバー\nアップ")
        self.number_buttons[16].clicked.connect(self._upload_ver01_model)
        self.number_buttons[17].setText("学習")
        self.number_buttons[17].clicked.connect(self._ask_ver01_train)
        for button in self.number_buttons:
            button.setCheckable(True)
            button.setAutoExclusive(True)
        self.image_window = QFrame(central)
        self.image_window.setObjectName("imageWindow")
        self.image_window.setFrameShape(QFrame.Shape.Box)
        self.image_window.setLineWidth(1)
        self.play_window = QFrame(self.image_window)
        self.play_window.setObjectName("playWindow")
        self.play_window.setFrameShape(QFrame.Shape.Box)
        self.play_window.setLineWidth(1)
        play_layout = QVBoxLayout(self.play_window)
        play_layout.setContentsMargins(2, 2, 2, 2)
        self.play_image = QLabel(self.play_window)
        self.play_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.play_image.installEventFilter(self)
        play_layout.addWidget(self.play_image)
        self.play_name = QLabel(self.image_window)
        self.play_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.undo_circle_btn = QPushButton("戻る", self.image_window)
        self.undo_circle_btn.setEnabled(False)
        self.undo_circle_btn.clicked.connect(self._undo_circle_drag)
        self._circle_undo: list[tuple[dict, int, int]] = []
        self._play_path: Path | None = None
        self._play_pieces: list[dict] = []
        self._place_big = False
        self._drag_piece: dict | None = None
        self._circle_scale = 1.0
        self._circle_ox = 0.0
        self._circle_oy = 0.0
        self._source_w = 1
        self._source_h = 1
        self.control_window = QFrame(central)
        self.control_window.setObjectName("controlWindow")
        self.control_window.setFrameShape(QFrame.Shape.Box)
        self.control_window.setLineWidth(1)
        control_layout = QVBoxLayout(self.control_window)
        control_layout.setContentsMargins(0, 0, 0, 0)
        self.register_ver01_btn = QPushButton("登録")
        self.register_ver01_btn.setEnabled(False)
        self.register_ver01_btn.clicked.connect(self._register_ver01)
        self.circle_count_label = QLabel("〇 0")
        self.tsum_count_label = QLabel("ツム 0")
        self.big_count_label = QLabel("デカツム 0")
        self.bomb_count_label = QLabel("ボム 0")
        for label in (
            self.circle_count_label,
            self.tsum_count_label,
            self.big_count_label,
            self.bomb_count_label,
        ):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        register_row = QHBoxLayout()
        register_row.setContentsMargins(0, 0, 0, 0)
        register_row.addWidget(self.register_ver01_btn, 4)
        register_row.addWidget(self.circle_count_label, 1)
        register_row.addWidget(self.tsum_count_label, 1)
        register_row.addWidget(self.big_count_label, 1)
        register_row.addWidget(self.bomb_count_label, 1)
        control_layout.addLayout(register_row)
        self.circle_strip = _CircleStrip()
        self.circle_scroll = QScrollArea(self.control_window)
        self.circle_scroll.setWidgetResizable(False)
        self.circle_scroll.setWidget(self.circle_strip)
        control_layout.addWidget(self.circle_scroll)
        self.name_list_btn = QPushButton("ツム名一覧", self.control_window)
        self.name_list_btn.clicked.connect(self._show_registered_names)
        control_layout.addWidget(self.name_list_btn)
        self.not_tsum_btn = QPushButton("ツムではない", self.control_window)
        self.not_tsum_btn.setEnabled(False)
        self.not_tsum_btn.clicked.connect(self._save_not_tsum)
        control_layout.addWidget(self.not_tsum_btn)
        self.circle_strip.picked.connect(self._sync_not_tsum_button)
        self.circle_strip.opened.connect(self._open_saved_source)
        self.circle_strip.assigned.connect(self._assign_picked_number)
        self.circle_strip.name_menu.connect(self._pick_row_name)
        self._blink_on = False
        self._blink = QTimer(self)
        self._blink.setInterval(280)
        self._blink.timeout.connect(self._toggle_blink)
        self.file_window = QFrame(central)
        self.file_window.setObjectName("fileWindow")
        self.file_window.setFrameShape(QFrame.Shape.Box)
        self.file_window.setLineWidth(1)
        file_layout = QVBoxLayout(self.file_window)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.file_list = QListWidget(self.file_window)
        self.file_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.file_list.setStyleSheet(
            "QListWidget::item:selected { background: palette(highlight); }"
        )
        self.file_list.setItemDelegate(_RegisteredFileDelegate(self.file_list))
        file_layout.addWidget(self.file_list)
        self.file_list.itemClicked.connect(self._show_play_image)
        self._fill_file_list()
        self._did_maximize = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._did_maximize:
            return
        self._did_maximize = True
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.availableGeometry())
        self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _fill_file_list(self) -> None:
        images = DATA_DIR / "images"
        if not images.is_dir():
            self.file_count.setText("0")
            return
        files = [
            path
            for path in images.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        named, not_tsum = _registered_marks()
        self.file_list.clear()
        self.file_count.setText(str(len(files)))
        for number, path in enumerate(files, start=1):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, path.name)
            item.setData(Qt.ItemDataRole.UserRole + 1, number)
            item.setData(Qt.ItemDataRole.UserRole + 2, path.stem in named)
            item.setData(Qt.ItemDataRole.UserRole + 3, path.stem in not_tsum)
            self.file_list.addItem(item)

    def _open_saved_source(self, stem: str) -> None:
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item is None:
                continue
            name = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if Path(name).stem != stem:
                continue
            self.file_list.setCurrentItem(item)
            self.file_list.scrollToItem(item)
            self._show_play_image(item)
            return

    def _show_play_image(self, item: QListWidgetItem) -> None:
        name = str(item.data(Qt.ItemDataRole.UserRole) or "")
        path = DATA_DIR / "images" / name
        self._play_path = path if path.is_file() else None
        self._play_pieces = []
        self._circle_undo.clear()
        self.undo_circle_btn.setEnabled(False)
        self.circle_strip.clear_rows()
        self.register_ver01_btn.setEnabled(False)
        self.play_name.setText(name if self._play_path is not None else "")
        self._fit_play_image()

    def _refresh_circle_counts(self) -> None:
        total = len(self._play_pieces)
        normal = 0
        big = 0
        bomb = 0
        for piece in self._play_pieces:
            kind = str(piece.get("kind") or "")
            if kind == "bomb":
                bomb += 1
            elif kind == "big" or int(piece.get("big") or 0) == 1:
                big += 1
            elif is_tsum_kind(kind):
                normal += 1
        self.circle_count_label.setText(f"〇 {total}")
        self.tsum_count_label.setText(f"ツム {normal}")
        self.big_count_label.setText(f"デカツム {big}")
        self.bomb_count_label.setText(f"ボム {bomb}")

    def _fit_play_image(self) -> None:
        self._refresh_circle_counts()
        if self._play_path is None:
            self.play_image.clear()
            self.play_name.clear()
            return
        pixmap = QPixmap(str(self._play_path))
        if pixmap.isNull():
            self.play_image.clear()
            self.play_name.clear()
            return
        target = self.play_image.size()
        if target.width() < 2 or target.height() < 2:
            return
        scaled = pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._source_w = pixmap.width()
        self._source_h = pixmap.height()
        self._circle_scale = scaled.width() / pixmap.width() if pixmap.width() else 1.0
        self._circle_ox = (target.width() - scaled.width()) / 2
        self._circle_oy = (target.height() - scaled.height()) / 2
        if self._play_pieces and pixmap.width() > 0 and scaled.width() > 0:
            scale = self._circle_scale
            painter = QPainter(scaled)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for piece in self._play_pieces:
                kind = str(piece.get("kind") or "")
                if is_tsum_kind(kind):
                    color = tsum_group_color(int(piece.get("group") or 1))
                else:
                    color = PIECE_COLORS.get(kind, "#FFE066")
                painter.setPen(QPen(QColor(color), 3))
                x = int(piece["x"]) * scale
                y = int(piece["y"]) * scale
                radius = max(1.0, int(piece["r"]) * scale)
                painter.drawEllipse(
                    int(x - radius),
                    int(y - radius),
                    int(radius * 2),
                    int(radius * 2),
                )
                if piece is self.circle_strip.picked_piece() and self._blink_on:
                    painter.setPen(QPen(QColor("#E10600"), 5))
                    painter.drawEllipse(
                        int(x - radius),
                        int(y - radius),
                        int(radius * 2),
                        int(radius * 2),
                    )
            painter.end()
        self.play_image.setPixmap(scaled)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.play_image and event.type() == QEvent.Type.Wheel:
            if self._wheel_circle(event):
                return True
        if watched is self.play_image and event.type() in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        }:
            if self._drag_circle(event):
                return True
        return super().eventFilter(watched, event)

    def _display_to_source(self, px: float, py: float) -> tuple[float, float] | None:
        if self._circle_scale <= 0:
            return None
        return (px - self._circle_ox) / self._circle_scale, (py - self._circle_oy) / self._circle_scale

    def _circle_at(self, x: float, y: float) -> dict | None:
        picked = None
        for piece in self._play_pieces:
            radius = max(8, int(piece.get("r") or 16))
            if (int(piece["x"]) - x) ** 2 + (int(piece["y"]) - y) ** 2 <= radius ** 2:
                picked = piece
        return picked

    def _wheel_circle(self, event) -> bool:
        if self._play_path is None or self._source_w <= 0:
            return False
        if event.angleDelta().y() == 0:
            return False
        point = self._display_to_source(event.position().x(), event.position().y())
        if point is None:
            return False
        x, y = point
        piece = self._circle_at(x, y)
        if piece is None:
            self._place_big = not self._place_big
            return True
        big = str(piece.get("kind") or "") == "big" or int(piece.get("big") or 0) == 1
        radius = max(8, int(piece.get("r") or 16))
        if big:
            piece["kind"] = "tsum"
            piece.pop("big", None)
            piece["r"] = max(8, int(round(radius / 1.8)))
        else:
            piece["kind"] = "big"
            piece["big"] = 1
            piece["r"] = max(8, int(round(radius * 1.8)))
        pixmap = QPixmap(str(self._play_path)) if self._play_path is not None else QPixmap()
        if not pixmap.isNull():
            self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
            self.circle_strip.set_rows(pixmap, self._play_pieces, self.circle_strip.edited_names())
            self.circle_strip.select_piece(piece)
        self._fit_play_image()
        return True

    def _drag_circle(self, event) -> bool:
        if self._play_path is None or self._source_w <= 0:
            return False
        point = self._display_to_source(event.position().x(), event.position().y())
        if point is None:
            return False
        x, y = point
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            if x < 0 or y < 0 or x >= self._source_w or y >= self._source_h:
                return False
            picked = self._circle_at(x, y)
            if picked is None:
                self._add_circle(x, y)
                return True
            self._drag_piece = picked
            self._circle_undo.append((picked, int(picked["x"]), int(picked["y"])))
            self.undo_circle_btn.setEnabled(True)
            self.play_image.grabMouse()
            self.circle_strip.select_piece(picked)
            return True
        if self._drag_piece is None:
            return False
        if event.type() == QEvent.Type.MouseMove:
            self._drag_piece["x"] = int(min(max(x, 0), self._source_w - 1))
            self._drag_piece["y"] = int(min(max(y, 0), self._source_h - 1))
            self._fit_play_image()
            return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            piece = self._drag_piece
            self._drag_piece = None
            self.play_image.releaseMouse()
            pixmap = QPixmap(str(self._play_path)) if self._play_path is not None else QPixmap()
            if not pixmap.isNull():
                self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
                self.circle_strip.set_rows(pixmap, self._play_pieces, self.circle_strip.edited_names())
                self.circle_strip.select_piece(piece)
            self._fit_play_image()
            return True
        return False

    def _add_circle(self, x: float, y: float) -> None:
        radii = [int(piece.get("r") or 0) for piece in self._play_pieces if int(piece.get("r") or 0) > 0]
        radii.sort()
        radius = radii[len(radii) // 2] if radii else 36
        if self._place_big:
            radius = max(8, int(round(radius * 1.8)))
        groups = [
            int(piece.get("group") or 0)
            for piece in self._play_pieces
            if is_tsum_kind(str(piece.get("kind") or ""))
        ]
        piece = {
            "x": int(min(max(x, 0), self._source_w - 1)),
            "y": int(min(max(y, 0), self._source_h - 1)),
            "r": radius,
            "kind": "big" if self._place_big else "tsum",
            "group": (max(groups) if groups else 0) + 1,
            "tsum_name": "",
        }
        if self._place_big:
            piece["big"] = 1
        self._play_pieces.append(piece)
        self._circle_undo.append((piece, None, None))
        self.undo_circle_btn.setEnabled(True)
        pixmap = QPixmap(str(self._play_path)) if self._play_path is not None else QPixmap()
        if not pixmap.isNull():
            self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
            self.circle_strip.set_rows(pixmap, self._play_pieces, self.circle_strip.edited_names())
            self.circle_strip.select_piece(piece)
        self.register_ver01_btn.setEnabled(True)
        self._fit_play_image()

    def _undo_circle_drag(self) -> None:
        if not self._circle_undo:
            return
        piece, x, y = self._circle_undo.pop()
        self.undo_circle_btn.setEnabled(bool(self._circle_undo))
        if x is None or y is None:
            self._play_pieces = [item for item in self._play_pieces if item is not piece]
            self.register_ver01_btn.setEnabled(bool(self._play_pieces))
        elif piece in self._play_pieces:
            piece["x"] = x
            piece["y"] = y
        else:
            return
        pixmap = QPixmap(str(self._play_path)) if self._play_path is not None else QPixmap()
        if pixmap.isNull() or not self._play_pieces:
            self.circle_strip.clear_rows()
            self._fit_play_image()
            return
        self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
        self.circle_strip.set_rows(pixmap, self._play_pieces, self.circle_strip.edited_names())
        if piece in self._play_pieces:
            self.circle_strip.select_piece(piece)
        self._fit_play_image()

    def _registered_tsum_names(self) -> list[str]:
        import locale

        from app.named_tsum_test import VER01_IMAGE_DIR

        names: list[str] = []
        if VER01_IMAGE_DIR.is_dir():
            for folder in VER01_IMAGE_DIR.iterdir():
                if folder.is_dir() and folder.name not in {"ツムではない", "ボム"}:
                    names.append(folder.name)
        previous = locale.setlocale(locale.LC_COLLATE)
        try:
            for candidate in ("Japanese_Japan.932", "ja_JP.UTF-8"):
                try:
                    locale.setlocale(locale.LC_COLLATE, candidate)
                    break
                except locale.Error:
                    continue
            names.sort(key=locale.strxfrm)
        finally:
            locale.setlocale(locale.LC_COLLATE, previous)
        return names

    def _tsum_name_menu(self, parent) -> QMenu:
        menu = QMenu(parent)
        names = self._registered_tsum_names()
        if not names:
            empty = menu.addAction("登録がありません")
            empty.setEnabled(False)
        else:
            for name in names:
                menu.addAction(name)
        return menu

    def _show_registered_names(self) -> None:
        menu = self._tsum_name_menu(self.name_list_btn)
        chosen = menu.exec(self.name_list_btn.mapToGlobal(self.name_list_btn.rect().bottomLeft()))
        if chosen is not None and chosen.isEnabled():
            QApplication.clipboard().setText(chosen.text(), QClipboard.Mode.Clipboard)
            self._move_saved_face(chosen.text())

    def _pick_row_name(self, key: str) -> None:
        button = self.circle_strip.name_button(key)
        if button is None:
            return
        menu = self._tsum_name_menu(button)
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if chosen is not None and chosen.isEnabled():
            self.circle_strip.set_row_name(key, chosen.text())

    def _show_registered_bombs(self) -> None:
        import locale

        from app.named_tsum_test import VER01_IMAGE_DIR

        names: list[str] = []
        folder = VER01_IMAGE_DIR / "ボム"
        if folder.is_dir():
            if any(folder.glob("*.png")):
                names.append("ボム")
            for child in folder.iterdir():
                if child.is_dir() and any(child.glob("*.png")):
                    names.append(child.name)
        previous = locale.setlocale(locale.LC_COLLATE)
        try:
            for candidate in ("Japanese_Japan.932", "ja_JP.UTF-8"):
                try:
                    locale.setlocale(locale.LC_COLLATE, candidate)
                    break
                except locale.Error:
                    continue
            names.sort(key=locale.strxfrm)
        finally:
            locale.setlocale(locale.LC_COLLATE, previous)
        menu = QMenu(self.number_buttons[14])
        if not names:
            empty = menu.addAction("登録がありません")
            empty.setEnabled(False)
        else:
            for name in names:
                menu.addAction(name)
        button = self.number_buttons[14]
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if chosen is not None and chosen.isEnabled():
            QApplication.clipboard().setText(chosen.text(), QClipboard.Mode.Clipboard)

    def _move_saved_face(self, name: str) -> None:
        from app.named_tsum_test import VER01_IMAGE_DIR

        sources = [path for path in self.circle_strip.saved_paths() if path.is_file()]
        if not sources:
            return
        folder = VER01_IMAGE_DIR / name
        folder.mkdir(parents=True, exist_ok=True)
        for source in sources:
            target = folder / source.name
            if source.resolve() == target.resolve():
                continue
            if target.exists():
                source.unlink()
            else:
                source.rename(target)
        if self.circle_strip.showing_saved():
            self._show_saved_faces()

    def _show_saved_faces(self) -> None:
        import locale

        from app.named_tsum_test import VER01_IMAGE_DIR

        groups: list[tuple[str, list[tuple[QPixmap, Path]]]] = []
        if VER01_IMAGE_DIR.is_dir():
            folders = [folder for folder in VER01_IMAGE_DIR.iterdir() if folder.is_dir() and folder.name != "ボム"]
            for child in (VER01_IMAGE_DIR / "ボム").iterdir() if (VER01_IMAGE_DIR / "ボム").is_dir() else []:
                if child.is_dir():
                    folders.append(child)
            previous = locale.setlocale(locale.LC_COLLATE)
            try:
                for candidate in ("Japanese_Japan.932", "ja_JP.UTF-8"):
                    try:
                        locale.setlocale(locale.LC_COLLATE, candidate)
                        break
                    except locale.Error:
                        continue
                def face_order(folder: Path) -> tuple[int, str]:
                    if folder.name == "ツムではない":
                        rank = 2
                    elif folder.name == "ボム" or folder.parent.name == "ボム":
                        rank = 1
                    else:
                        rank = 0
                    return (rank, locale.strxfrm(folder.name))

                folders.sort(key=face_order)
            finally:
                locale.setlocale(locale.LC_COLLATE, previous)
            for folder in folders:
                tiles: list[tuple[QPixmap, Path]] = []
                for path in sorted(folder.glob("*.png")):
                    image = QPixmap(str(path))
                    if image.isNull():
                        continue
                    tiles.append(
                        (
                            image.scaled(
                                _CircleStrip.CELL,
                                _CircleStrip.CELL,
                                Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            ),
                            path,
                        )
                    )
                if tiles:
                    groups.append((folder.name, tiles))
        self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
        self.circle_strip.show_named(groups)

    def _show_not_tsum_images(self) -> None:
        from app.named_tsum_test import VER01_IMAGE_DIR

        folder = VER01_IMAGE_DIR / "ツムではない"
        tiles: list[QPixmap] = []
        if folder.is_dir():
            for path in sorted(folder.glob("*.png")):
                image = QPixmap(str(path))
                if image.isNull():
                    continue
                tiles.append(
                    image.scaled(
                        _CircleStrip.CELL,
                        _CircleStrip.CELL,
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
        self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
        self.circle_strip.show_images(tiles)

    def keyPressEvent(self, event) -> None:
        number = event.text()
        if number.isdigit() or number in {"b", "B"}:
            self._assign_picked_number("B" if number in {"b", "B"} else number)
            return
        super().keyPressEvent(event)

    def _assign_picked_number(self, number: str) -> None:
        piece = self.circle_strip.picked_piece()
        if piece is None or self._play_path is None:
            return
        if number == "0":
            if not self._write_not_tsum(piece):
                return
            self._play_pieces = [item for item in self._play_pieces if item is not piece]
            names = self.circle_strip.edited_names()
            pixmap = QPixmap(str(self._play_path))
            if not pixmap.isNull() and self._play_pieces:
                self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
                self.circle_strip.set_rows(pixmap, self._play_pieces, names)
            else:
                self.circle_strip.clear_rows()
                self.register_ver01_btn.setEnabled(False)
            self._refresh_file_marks()
            self._fit_play_image()
            return
        if number == "B":
            piece["kind"] = "bomb"
            piece["group"] = 0
            piece["tsum_name"] = ""
            pixmap = QPixmap(str(self._play_path))
            if pixmap.isNull():
                return
            self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
            self.circle_strip.set_rows(pixmap, self._play_pieces, self.circle_strip.edited_names())
            self.circle_strip.select_piece(piece)
            self._fit_play_image()
            return
        names = self.circle_strip.edited_names()
        if number not in names:
            names[number] = ""
        name = names[number].strip()
        piece["kind"] = "tsum"
        piece["group"] = int(number)
        piece["tsum_name"] = name
        pixmap = QPixmap(str(self._play_path))
        if pixmap.isNull():
            return
        self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
        self.circle_strip.set_rows(pixmap, self._play_pieces, names)
        self.circle_strip.select_piece(piece)
        self._fit_play_image()

    def _mark_circles(self, use_ver01: bool) -> None:
        if self._play_path is None:
            return
        from app.named_tsum_test import VER01_MODEL_PATH
        from app.predictor import Predictor

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            predictor = getattr(self, "_circle_predictor", None)
            if predictor is None or predictor.piece_model is None:
                predictor = Predictor(DATA_DIR / "models", load=False)
                predictor.reload(pump=None)
                self._circle_predictor = predictor
            if predictor.piece_model is None:
                QMessageBox.information(self, "Circle Mark", "ツムのモデルがありません。")
                return
            names: dict[str, str] | None = None
            if use_ver01:
                if not predictor.use_named_tsum_model(VER01_MODEL_PATH):
                    QMessageBox.information(self, "Circle Mark", "新しいモデルがありません。")
                    return
            elif predictor.named_prototypes is not None:
                predictor.reload(pump=None)
            boxes = predictor.predict_all(self._play_path)
            game = boxes.get("game")
            self._play_pieces = predictor.predict_pieces(self._play_path, game)
            if use_ver01:
                self._play_pieces = [
                    piece
                    for piece in self._play_pieces
                    if str(piece.get("tsum_name") or "").strip() != "ツムではない"
                ]
                self._number_rows()
                names = {}
                for piece in self._play_pieces:
                    if not is_tsum_kind(str(piece.get("kind") or "")):
                        continue
                    name = str(piece.get("tsum_name") or "").strip()
                    if name:
                        names[str(int(piece.get("group") or 1))] = name
            self._show_circle_info(names)
            self.register_ver01_btn.setEnabled(bool(self._play_pieces))
        except Exception as exc:
            QMessageBox.warning(self, "Circle Mark", str(exc) or "〇を付けられませんでした。")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._fit_play_image()

    def _show_circle_info(self, names: dict[str, str] | None = None) -> None:
        pixmap = QPixmap(str(self._play_path)) if self._play_path is not None else QPixmap()
        if pixmap.isNull() or not self._play_pieces:
            self.circle_strip.clear_rows()
            self.register_ver01_btn.setEnabled(False)
            return
        self.circle_strip.set_wrap_width(max(1, self.circle_scroll.viewport().width()))
        self.circle_strip.set_rows(pixmap, self._play_pieces, names if names is not None else self._group_names())

    def _register_ver01(self) -> None:
        from app.named_tsum_test import VER01_IMAGE_DIR

        if self._play_path is None or not self._play_pieces:
            return
        pixmap = QPixmap(str(self._play_path))
        if pixmap.isNull():
            return
        names = self.circle_strip.edited_names()
        saved = 0
        overwritten = 0
        stem = self._play_path.stem
        for piece in self._play_pieces:
            kind = str(piece.get("kind") or "")
            if kind == "bomb":
                name = names.get("B", "").strip() or "ボム"
                parent = VER01_IMAGE_DIR / "ボム"
            elif is_tsum_kind(kind):
                key = str(int(piece.get("group") or 1))
                name = names.get(key, "").strip()
                parent = VER01_IMAGE_DIR
            else:
                continue
            if not name:
                continue
            folder_name = "".join("_" if char in '\\/:*?"<>|' else char for char in name).strip()
            if not folder_name:
                continue
            folder = parent / folder_name
            folder.mkdir(parents=True, exist_ok=True)
            x, y = int(piece["x"]), int(piece["y"])
            radius = max(8, int(piece.get("r") or 16))
            span = max(12, int(round(radius * 1.05)))
            tile = pixmap.copy(QRect(x - span, y - span, span * 2, span * 2))
            if tile.isNull():
                continue
            target = folder / f"{stem}_{x}_{y}.png"
            if target.is_file():
                overwritten += 1
            tile.save(str(target))
            saved += 1
        current = self.file_list.currentItem()
        current_name = str(current.data(Qt.ItemDataRole.UserRole) or "") if current is not None else ""
        self._fill_file_list()
        if current_name:
            for row in range(self.file_list.count()):
                item = self.file_list.item(row)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == current_name:
                    self.file_list.setCurrentItem(item)
                    break
        if overwritten and overwritten == saved:
            verb = "上書き保存しました"
        elif overwritten:
            verb = f"登録しました。{overwritten} 枚は上書き保存です"
        else:
            verb = "登録しました"
        QMessageBox.information(self, "登録", f"{saved} 枚を {VER01_IMAGE_DIR} に{verb}。")

    def _sync_not_tsum_button(self) -> None:
        piece = self.circle_strip.picked_piece()
        self.not_tsum_btn.setEnabled(piece is not None)
        if piece is None:
            self._blink.stop()
            self._blink_on = False
        else:
            self._blink_on = True
            if not self._blink.isActive():
                self._blink.start()
        self._fit_play_image()

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        self._fit_play_image()

    def _write_not_tsum(self, piece: dict) -> bool:
        from app.named_tsum_test import VER01_IMAGE_DIR

        if self._play_path is None:
            return False
        pixmap = QPixmap(str(self._play_path))
        if pixmap.isNull():
            return False
        folder = VER01_IMAGE_DIR / "ツムではない"
        folder.mkdir(parents=True, exist_ok=True)
        x, y = int(piece["x"]), int(piece["y"])
        radius = max(8, int(piece.get("r") or 16))
        span = max(12, int(round(radius * 1.05)))
        tile = pixmap.copy(QRect(x - span, y - span, span * 2, span * 2))
        if tile.isNull():
            return False
        return tile.save(str(folder / f"{self._play_path.stem}_{x}_{y}.png"))

    def _refresh_file_marks(self) -> None:
        current = self.file_list.currentItem()
        current_name = str(current.data(Qt.ItemDataRole.UserRole) or "") if current is not None else ""
        self._fill_file_list()
        if not current_name:
            return
        for row in range(self.file_list.count()):
            item = self.file_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == current_name:
                self.file_list.setCurrentItem(item)
                break

    def _save_not_tsum(self) -> None:
        from app.named_tsum_test import VER01_IMAGE_DIR

        piece = self.circle_strip.picked_piece()
        if piece is None or not self._write_not_tsum(piece):
            if piece is not None:
                QMessageBox.warning(self, "ツムではない", "保存できませんでした。")
            return
        self._refresh_file_marks()
        QMessageBox.information(
            self, "ツムではない", f"1 枚を {VER01_IMAGE_DIR / 'ツムではない'} に保存しました。"
        )

    def _upload_ver01_model(self) -> None:
        from app.named_tsum_test import VER01_MODEL_PATH

        model = VER01_MODEL_PATH
        if not model.is_file():
            QMessageBox.warning(self, "モデルがありません", "送るモデルがありません。")
            return
        answer = QMessageBox.question(
            self,
            "サーバーに保存",
            "次のモデルを http://hokkai-syabusyabu.com/home_page/workshop/models に保存します。続けますか？\n"
            + model.name,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        spec = importlib.util.spec_from_file_location("workshop_server_sync", SERVER_SYNC_PATH)
        if spec is None or spec.loader is None:
            QMessageBox.critical(self, "保存できませんでした", f"サーバー同期が見つかりません。\n{SERVER_SYNC_PATH}")
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            module.run_with_progress(
                self,
                "サーバーに保存しています",
                lambda progress: self._send_ver01_model(module, model, progress),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存できませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "サーバーに保存しました", f"{model.name} を保存しました。")

    def _send_ver01_model(self, sync, model: Path, progress) -> None:
        progress(0, 1, model.name)
        sync.upload_model(model)
        progress(1, 1, model.name)

    def _ask_ver01_train(self) -> None:
        global _ver01_progress
        from app.named_tsum_test import estimate_ver01_seconds, ver01_rows

        running = _ver01_progress
        if running is not None and running.is_running():
            running.show()
            running.raise_()
            return
        rows = ver01_rows()
        if len(rows) < 2:
            QMessageBox.information(self, "学習", "登録された顔が足りません。")
            return
        settings = QSettings("workshop", "TsumTsumScreenTrainer")

        def stored(key: str, fallback: float) -> float:
            try:
                return float(settings.value(key, fallback) or fallback)
            except (TypeError, ValueError):
                return fallback

        import torch

        batch_rate = stored("train_sec_per_batch", 0.3 if torch.cuda.is_available() else 1.8)
        seconds = estimate_ver01_seconds(
            rows,
            stored("named_sec_per_face", 0.0),
            stored("named_passes", 1.0),
            batch_rate,
        )
        whole = int(round(seconds))
        minutes, sec = divmod(whole, 60)
        clock = f"{minutes}分{sec}秒" if minutes else f"{sec}秒"
        kinds = len({ja for ja, _en, _crop in rows})
        if not _ask_ver01_start(clock, len(rows), kinds):
            return
        window = _Ver01Progress(self)
        thread = _Ver01TrainThread(rows)
        window.attach(thread)
        _ver01_progress = window
        window.show()
        thread.start()

    def _number_rows(self) -> None:
        keys = sorted(
            {
                int(piece.get("group") or 1)
                for piece in self._play_pieces
                if is_tsum_kind(str(piece.get("kind") or ""))
            }
        )
        remap = {old: index + 1 for index, old in enumerate(keys)}
        for piece in self._play_pieces:
            if not is_tsum_kind(str(piece.get("kind") or "")):
                continue
            piece["group"] = remap[int(piece.get("group") or 1)]

    def _group_names(self) -> dict[str, str]:
        import torch

        from app.named_tsum_test import TEST_MODEL_PATH

        if getattr(self, "_name_proto", None) is None:
            self._name_proto = False
            self._name_list: list[str] = []
            if TEST_MODEL_PATH.is_file():
                checkpoint = torch.load(TEST_MODEL_PATH, map_location="cpu", weights_only=False)
                prototypes = checkpoint.get("prototypes") if isinstance(checkpoint, dict) else None
                raw_names = checkpoint.get("names") if isinstance(checkpoint, dict) else None
                if (
                    prototypes is not None
                    and isinstance(raw_names, list)
                    and len(raw_names) == int(prototypes.shape[0])
                ):
                    self._name_proto = torch.nn.functional.normalize(prototypes.float(), dim=1)
                    for item in raw_names:
                        if isinstance(item, dict):
                            self._name_list.append(str(item.get("ja") or "").strip())
                        else:
                            self._name_list.append("")
        proto = self._name_proto
        if proto is False or proto is None:
            return {}
        counts: dict[str, dict[str, int]] = {}
        for piece in self._play_pieces:
            if not is_tsum_kind(str(piece.get("kind") or "")):
                continue
            vec = piece.get("_vec")
            if not vec:
                continue
            values = torch.tensor(vec, dtype=torch.float32)
            norm = float(torch.linalg.vector_norm(values))
            if norm <= 0:
                continue
            index = int(torch.argmax(proto @ (values / norm)))
            name = self._name_list[index] if 0 <= index < len(self._name_list) else ""
            if not name:
                continue
            key = str(int(piece.get("group") or 1))
            bucket = counts.setdefault(key, {})
            bucket[name] = bucket.get(name, 0) + 1
        return {key: max(bucket, key=lambda item: bucket[item]) for key, bucket in counts.items()}

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        host = self.centralWidget()
        width = host.width()
        height = host.height()
        edge = 10
        file_w = max(1, int(width * 0.20))
        image_span = int(width * 0.40)
        image_w = max(1, int(image_span * 2 / 3))
        control_w = max(1, int(width * 0.15) + image_span - image_w)
        margin_y = max(edge, int(height * 0.05))
        frame_h = max(1, height - margin_y * 2)
        file_x = width - edge - file_w
        control_x = file_x - control_w
        image_x = control_x - image_w
        self.file_window.setGeometry(file_x, margin_y, file_w, frame_h)
        self.control_window.setGeometry(control_x, margin_y, control_w, frame_h)
        self.circle_strip.set_wrap_width(max(1, control_w - 4))
        self.image_window.setGeometry(image_x, margin_y, image_w, frame_h)
        play_pad = 24
        name_h = max(1, self.play_name.sizeHint().height())
        undo_h = 28
        play_top = undo_h + 8
        play_h = max(1, frame_h - play_top - name_h - 4)
        self.undo_circle_btn.setGeometry(play_pad, 4, 72, undo_h)
        self.play_window.setGeometry(
            play_pad,
            play_top,
            max(1, image_w - play_pad * 2),
            play_h,
        )
        self.play_name.setGeometry(play_pad, play_pad + play_h, max(1, image_w - play_pad * 2), name_h)
        self.play_name.raise_()
        self.undo_circle_btn.raise_()
        spare_w = max(1, image_x - edge)
        self.button_window.setGeometry(edge, margin_y, spare_w, frame_h)
        self._place_number_buttons()
        label_h = max(1, self.file_count.sizeHint().height())
        count_w = self.file_count.fontMetrics().horizontalAdvance(self.file_count.text()) + 12
        label_y = max(edge, margin_y - label_h)
        self.file_count.setGeometry(file_x, label_y, count_w, label_h)
        self.file_mark.setGeometry(file_x + count_w, label_y, max(1, file_w - count_w), label_h)
        self.file_count.raise_()
        self.file_mark.raise_()
        self.button_window.raise_()
        self.image_window.raise_()
        self.control_window.raise_()
        self.file_window.raise_()
        self.shortcut_btn.raise_()
        self._fit_play_image()

    def _place_number_buttons(self) -> None:
        if not self.number_buttons:
            return
        inner_w = max(1, self.button_window.width() - 2)
        inner_h = max(1, self.button_window.height() - 2)
        button_w = max(1, int(inner_w / 2 * 2 / 3))
        button_h = max(1, int(inner_h / 10))
        font = self.number_buttons[0].font()
        em = font.pixelSize()
        if em < 1:
            em = font.pointSizeF() * self.button_window.logicalDpiY() / 72
        gap_x = max(1, int(em * 0.5))
        gap_y = 3
        group_w = button_w * 2 + gap_x
        origin_x = 1 + max(0, (inner_w - group_w) // 2)
        origin_y = gap_y
        for index, button in enumerate(self.number_buttons):
            row, col = divmod(index, 2)
            button.setGeometry(
                origin_x + col * (button_w + gap_x),
                origin_y + row * (button_h + gap_y),
                button_w,
                button_h,
            )

    def _create_macos_launch_shortcut(self, desktop: Path) -> Path:
        app_path = desktop / "NamedModel.app"
        contents = app_path / "Contents"
        macos_dir = contents / "MacOS"
        if app_path.exists():
            import shutil

            shutil.rmtree(app_path)
        macos_dir.mkdir(parents=True, exist_ok=True)
        python = Path(sys.executable)
        launcher = macos_dir / "launch"
        launcher.write_text(
            "#!/bin/bash\n"
            f'cd "{APP_ROOT}"\n'
            f'exec "{python}" main.py {NAMED_MODEL_ARG}\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        (contents / "Info.plist").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>workshop.named-model</string>
  <key>CFBundleName</key><string>NamedModel</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
""",
            encoding="utf-8",
        )
        return app_path

    def create_launch_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        if sys.platform == "darwin":
            dest = self._create_macos_launch_shortcut(Path(desktop))
            QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{dest}")
            return
        lnk = Path(desktop) / "NamedModel.lnk"
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        script = APP_ROOT / "main.py"

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        arguments = f'"{script}" {NAMED_MODEL_ARG}'
        icon_line = ""
        if NAMED_MODEL_ICON.is_file():
            icon_line = f"$s.IconLocation = {ps_quote(str(NAMED_MODEL_ICON) + ',0')}\n"
        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(arguments)}\n"
            f"$s.WorkingDirectory = {ps_quote(str(APP_ROOT))}\n"
            "$s.WindowStyle = 1\n"
            "$s.Description = 'NamedModel'\n"
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
            err = (result.stderr or result.stdout or "ショートカットを作れませんでした。").strip()
            QMessageBox.critical(self, "アイコンを作れませんでした", err)
            return
        QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{lnk}")
