from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, QEvent
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.bluestacks import halt_input, start_tsum, tsum_is_running
from app.intro import IntroWorker
from app.paths import APP_ROOT
from app.play import PlayWorker

APP_NAME = "ツムツム オートプレイ"
_STOP_HOTKEY = 1
_WM_HOTKEY = 0x0312
_VK_Q = 0x51
_MOD_NOREPEAT = 0x4000


class DebugWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("デバッグ")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(400)
        layout.addWidget(self._log)
        self.resize(420, 480)
        self._on_stop = None

    def append(self, text: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._log.appendPlainText(f"{now}  {text}")
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Q and not event.isAutoRepeat() and self._on_stop:
            self._on_stop()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        icon = self._ensure_app_icon()
        if icon is not None:
            self.setWindowIcon(QIcon(str(icon)))
        root = QWidget()
        layout = QVBoxLayout(root)
        self.play_btn = QPushButton("PLAY")
        self.play_btn.clicked.connect(self.on_play)
        layout.addWidget(self.play_btn)
        self.now_btn = QPushButton("今すぐプレイ")
        self.now_btn.clicked.connect(self.on_play_now)
        layout.addWidget(self.now_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.on_stop)
        layout.addWidget(self.stop_btn)
        self.shortcut_btn = QPushButton("起動アイコン作成")
        self.shortcut_btn.clicked.connect(self.create_launch_shortcut)
        layout.addWidget(self.shortcut_btn)
        self.status_label = QLabel("待機中")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)
        self._stop = threading.Event()
        self._intro: IntroWorker | None = None
        self._play: PlayWorker | None = None
        self._debug = DebugWindow()
        self._debug._on_stop = self.on_stop
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._front_timer = QTimer(self)
        self._front_timer.setInterval(800)
        self._front_timer.timeout.connect(self._keep_front)
        self._front_timer.start()
        self._debug.append("待機中")

    def on_play(self) -> None:
        if self._is_busy():
            return
        self._stop.clear()
        self._set_running(True)
        self._set_status("PLAY")
        if not tsum_is_running():
            desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
            try:
                start_tsum(desktop or "")
            except Exception as exc:  # noqa: BLE001
                self._set_running(False)
                QMessageBox.critical(self, "起動できませんでした", str(exc))
                return
            self._set_status("起動しています")
            self._start_intro()
            return
        self._start_play()

    def on_play_now(self) -> None:
        if self._is_busy():
            return
        if not tsum_is_running():
            QMessageBox.information(self, "今すぐプレイ", "ツムツムが起動していません。")
            return
        self._stop.clear()
        self._set_running(True)
        self._set_status("今すぐプレイ")
        self._start_play(start_match=True)

    def on_stop(self) -> None:
        if not self._is_busy():
            return
        if self._stop.is_set():
            halt_input()
            return
        self._stop.set()
        if self._intro is not None:
            self._intro.requestInterruption()
        if self._play is not None:
            self._play.requestInterruption()
        halt_input()
        self._set_status("停止しています")

    def _is_busy(self) -> bool:
        intro_on = self._intro is not None and self._intro.isRunning()
        play_on = self._play is not None and self._play.isRunning()
        return intro_on or play_on

    def _set_running(self, running: bool) -> None:
        self.play_btn.setEnabled(not running)
        self.now_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        if running:
            self._front_timer.stop()
            self._register_stop_hotkey()
        else:
            self._unregister_stop_hotkey()
            self._front_timer.start()
            self._keep_front()

    def _start_intro(self) -> None:
        self._intro = IntroWorker(self._stop, self)
        self._intro.status.connect(self._set_status)
        self._intro.succeeded.connect(self._on_intro_ok)
        self._intro.failed.connect(self._on_intro_fail)
        self._intro.stopped.connect(self._on_stopped)
        self._keep_front()
        self._intro.start()

    def _start_play(self, start_match: bool = False) -> None:
        self._play = PlayWorker(self._stop, self, start_match=start_match)
        self._play.status.connect(self._set_status)
        self._play.failed.connect(self._on_play_fail)
        self._play.stopped.connect(self._on_stopped)
        self._play.completed.connect(self._on_play_done)
        self._keep_front()
        self._play.start()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self._debug.append(text)

    def _keep_front(self) -> None:
        self.raise_()
        if self._debug.isVisible():
            self._debug.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._debug.show()
        geo = self.frameGeometry()
        self._debug.move(geo.right() + 8, geo.top())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Q and not event.isAutoRepeat():
            self.on_stop()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Q:
            if not event.isAutoRepeat() and self._is_busy():
                self.on_stop()
                return True
        return super().eventFilter(watched, event)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32":
            raw = bytes(eventType) if not isinstance(eventType, (bytes, bytearray)) else eventType
            if raw.startswith(b"windows_generic_MSG"):
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == _WM_HOTKEY and int(msg.wParam) == _STOP_HOTKEY:
                    QTimer.singleShot(0, self.on_stop)
                    return True, 0
        return super().nativeEvent(eventType, message)

    def _register_stop_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        ctypes.windll.user32.RegisterHotKey(
            int(self.winId()), _STOP_HOTKEY, _MOD_NOREPEAT, _VK_Q
        )

    def _unregister_stop_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        ctypes.windll.user32.UnregisterHotKey(int(self.winId()), _STOP_HOTKEY)

    def closeEvent(self, event) -> None:
        self._unregister_stop_hotkey()
        self._debug.close()
        super().closeEvent(event)

    def _on_intro_ok(self) -> None:
        if self._stop.is_set():
            self._on_stopped()
            return
        self._start_play()

    def _on_intro_fail(self, message: str) -> None:
        self._set_running(False)
        self._set_status(message)
        QMessageBox.critical(self, "PLAY", message)

    def _on_play_fail(self, message: str) -> None:
        self._set_running(False)
        self._set_status(message)
        QMessageBox.critical(self, "PLAY", message)

    def _on_play_done(self) -> None:
        self._set_running(False)
        if self.status_label.text() != "TIME UP":
            self._set_status("TIME UP")

    def _on_stopped(self) -> None:
        self._set_running(False)
        self._set_status("停止しました")

    def create_launch_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        if sys.platform == "darwin":
            dest = self._create_macos_launch_shortcut(Path(desktop))
            QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{dest}")
            return
        lnk = Path(desktop) / f"{APP_NAME}.lnk"
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        script = APP_ROOT / "main.py"
        icon = self._ensure_app_icon()

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        icon_line = f"$s.IconLocation = {ps_quote(str(icon) + ',0')}" if icon else ""
        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(chr(34) + str(script) + chr(34))}\n"
            f"$s.WorkingDirectory = {ps_quote(str(APP_ROOT))}\n"
            "$s.WindowStyle = 1\n"
            f"$s.Description = {ps_quote(APP_NAME)}\n"
            f"{icon_line}\n"
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

    def _create_macos_launch_shortcut(self, desktop: Path) -> Path:
        app_path = desktop / f"{APP_NAME}.app"
        contents = app_path / "Contents"
        macos_dir = contents / "MacOS"
        if app_path.exists():
            import shutil

            shutil.rmtree(app_path)
        macos_dir.mkdir(parents=True, exist_ok=True)
        launcher = macos_dir / "launch"
        launcher.write_text(
            "#!/bin/bash\n"
            f'cd "{APP_ROOT}"\n'
            f'exec "{sys.executable}" main.py\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        (contents / "Info.plist").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>workshop.tsumtsum-autoplay</string>
  <key>CFBundleName</key><string>ツムツム オートプレイ</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
""",
            encoding="utf-8",
        )
        return app_path

    def _ensure_app_icon(self) -> Path | None:
        path = APP_ROOT / "app.ico"
        return path if path.exists() else None
