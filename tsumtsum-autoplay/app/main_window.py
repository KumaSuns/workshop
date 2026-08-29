from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget

from app.bluestacks import start_tsum, tsum_is_running
from app.intro import IntroWorker
from app.paths import APP_ROOT

APP_NAME = "ツムツム オートプレイ"


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
        self.start_btn = QPushButton("スタート")
        self.start_btn.clicked.connect(self.on_start)
        layout.addWidget(self.start_btn)
        self.shortcut_btn = QPushButton("起動アイコン作成")
        self.shortcut_btn.clicked.connect(self.create_launch_shortcut)
        layout.addWidget(self.shortcut_btn)
        self.status_label = QLabel("待機中")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)
        self._intro: IntroWorker | None = None
        self._front_timer = QTimer(self)
        self._front_timer.setInterval(800)
        self._front_timer.timeout.connect(self._keep_front)
        self._front_timer.start()

    def on_start(self) -> None:
        if self._intro is not None and self._intro.isRunning():
            return
        if tsum_is_running():
            QMessageBox.information(self, "スタート", "BlueStacks でツムツムはすでに起動しています。")
            return
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        try:
            start_tsum(desktop or "")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "起動できませんでした", str(exc))
            return
        self.start_btn.setEnabled(False)
        self.start_btn.setText("起動中…")
        self._set_status("起動しています")
        self._intro = IntroWorker(self)
        self._intro.status.connect(self._set_status)
        self._intro.succeeded.connect(self._on_intro_ok)
        self._intro.failed.connect(self._on_intro_fail)
        self._keep_front()
        self._intro.start()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self._keep_front()

    def _keep_front(self) -> None:
        self.raise_()

    def _on_intro_ok(self) -> None:
        self._restore_start_btn()
        self._set_status("プレイまで終わりました")
        QMessageBox.information(self, "スタート", "プレイまで終わりました。")

    def _on_intro_fail(self, message: str) -> None:
        self._restore_start_btn()
        self._set_status(message)
        QMessageBox.critical(self, "スタート", message)

    def _restore_start_btn(self) -> None:
        self.start_btn.setEnabled(True)
        self.start_btn.setText("スタート")

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
