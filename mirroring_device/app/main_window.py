from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.capture import capture_mirror
from app.screens import current_screen_name

APP_ROOT = Path(__file__).resolve().parent.parent


def letsview_known() -> bool | None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Letsview.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=flags,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return "letsview.exe" in result.stdout.lower()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("画面ミラー")
        self._placed = False
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(960, 1080)
        else:
            geo = screen.availableGeometry()
            self.resize(max(1, int(geo.width()) // 2), max(1, int(geo.height())))

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        row = QHBoxLayout()
        self._check_btn = QPushButton("LetsView")
        self._check_btn.clicked.connect(self._on_letsview)
        self._known_label = QLabel("")
        row.addWidget(self._check_btn)
        row.addWidget(self._known_label)
        row.addStretch(1)
        self._capture_btn = QPushButton("キャプチャー")
        self._capture_btn.clicked.connect(self._capture)
        row.addWidget(self._capture_btn)
        self._close_btn = QPushButton("閉じる")
        self._close_btn.clicked.connect(self.close)
        row.addWidget(self._close_btn)
        layout.addLayout(row)
        self._screen_frame = QFrame()
        self._screen_frame.setFrameShape(QFrame.Shape.Box)
        frame_row = QVBoxLayout(self._screen_frame)
        frame_row.setContentsMargins(12, 8, 12, 8)
        self._screen_name = QLabel("－")
        self._screen_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_row.addWidget(self._screen_name)
        layout.addWidget(self._screen_frame)
        self._shot = QImage()
        self._view = QLabel()
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._view, 1)
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("画面"))
        self._name = QLineEdit()
        name_row.addWidget(self._name, 1)
        self._save_btn = QPushButton("登録")
        self._save_btn.clicked.connect(self._register)
        name_row.addWidget(self._save_btn)
        self._saved_label = QLabel("")
        name_row.addWidget(self._saved_label)
        layout.addLayout(name_row)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self._shortcut_btn = QPushButton("起動アイコン作成")
        self._shortcut_btn.clicked.connect(self._create_launch_shortcut)
        bottom.addWidget(self._shortcut_btn)
        layout.addLayout(bottom)
        self.setCentralWidget(root)
        self._blink_on = False
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink_letsview)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._placed:
            return
        self._placed = True
        QTimer.singleShot(0, self._place_right_half)

    def _place_right_half(self) -> None:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        extra_w = max(0, frame.width() - self.width())
        extra_h = max(0, frame.height() - self.height())
        client_w = max(1, area.width() // 2 - extra_w)
        client_h = max(1, area.height() - extra_h)
        self.resize(client_w, client_h)
        frame = self.frameGeometry()
        self.move(area.left() + area.width() - frame.width(), area.top())

    def _on_letsview(self) -> None:
        if not self._blink_timer.isActive():
            self._blink_letsview()
            self._blink_timer.start(500)
        self._show_current_screen()

    def _blink_letsview(self) -> None:
        self._blink_on = not self._blink_on
        if self._blink_on:
            self._check_btn.setStyleSheet("background: #ffe066; color: #222222;")
            return
        self._check_btn.setStyleSheet("")

    def _show_current_screen(self) -> None:
        image = capture_mirror()
        if image is None:
            self._screen_name.setText("画面が取れません")
            return
        name = current_screen_name(image)
        self._screen_name.setText(name if name else "－")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._show_shot()

    def _capture(self) -> None:
        image = capture_mirror()
        if image is None:
            self._shot = QImage()
            self._view.clear()
            self._saved_label.setText("画面が取れません")
            return
        self._shot = image
        self._saved_label.setText("")
        self._show_shot()

    def _show_shot(self) -> None:
        if self._shot.isNull():
            return
        target = self._view.size()
        if target.width() < 2 or target.height() < 2:
            return
        pixmap = QPixmap.fromImage(self._shot).scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._view.setPixmap(pixmap)

    def _register(self) -> None:
        name = self._name.text().strip()
        if self._shot.isNull():
            self._saved_label.setText("先にキャプチャーしてください")
            return
        if not name:
            self._saved_label.setText("画面の名前を入れてください")
            return
        folder = APP_ROOT / "data" / "captures"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = folder / f"{stamp}.png"
        if not self._shot.save(str(path), "PNG"):
            self._saved_label.setText("登録できませんでした")
            return
        record = APP_ROOT / "data" / "screens.jsonl"
        line = {"name": name, "file": path.name, "at": stamp}
        with record.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._saved_label.setText(f"{name} を登録しました")
        self._screen_name.setText(name)

    def _show_letsview(self) -> None:
        known = letsview_known()
        if known is None:
            self._known_label.setText("分かりません")
            return
        self._known_label.setText("認知しています" if known else "認知していません")

    def _create_launch_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        lnk = Path(desktop) / "画面ミラー.lnk"
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
            "$s.Description = '画面ミラー'\n"
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
