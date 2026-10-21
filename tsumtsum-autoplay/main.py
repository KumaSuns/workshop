from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow
from app.paths import APP_ROOT, IPC_NAME


def _windows_app_id() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "workshop.tsumtsum-autoplay"
    )


def _app_icon() -> QIcon:
    path = APP_ROOT / "launch.ico"
    if not path.is_file():
        path = APP_ROOT / "app.ico"
    icon = QIcon()
    if path.is_file():
        icon.addFile(str(path))
        pix = QPixmap(str(path))
        if not pix.isNull():
            icon.addPixmap(pix)
    return icon


def _games_from_argv() -> int | None:
    if "--games" not in sys.argv:
        return None
    index = sys.argv.index("--games") + 1
    if index >= len(sys.argv):
        return None
    text = sys.argv[index]
    if text.isdigit() and int(text) > 0:
        return int(text)
    return None


def _activate_running(action: str = "activate", games: int | None = None, hidden: bool = False) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(IPC_NAME)
    if not sock.waitForConnected(400):
        return False
    payload = {"action": action}
    if games is not None:
        payload["games"] = games
    if hidden:
        payload["hidden"] = True
    sock.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
    sock.waitForBytesWritten(800)
    sock.disconnectFromServer()
    return True


def _lock_holder_dead(lock: QLockFile) -> bool:
    try:
        pid, _hostname, _app = lock.getLockInfo()
    except Exception:
        return False
    if pid <= 0:
        return True
    try:
        os.kill(int(pid), 0)
        return False
    except OSError:
        return True


def _acquire_instance_lock() -> QLockFile | None:
    lock = QLockFile(str(Path(QDir.tempPath()) / f"{IPC_NAME}.lock"))
    if lock.tryLock(100):
        return lock
    if _lock_holder_dead(lock):
        lock.removeStaleLockFile()
        if lock.tryLock(100):
            return lock
    if lock.removeStaleLockFile() and lock.tryLock(100):
        return lock
    return None


def main() -> None:
    _windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("TsumTsum Autoplay")
    app.setOrganizationName("workshop")
    icon = _app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    lock = _acquire_instance_lock()
    start_loop = "--loop" in sys.argv
    hidden = "--hidden" in sys.argv
    games = _games_from_argv() if start_loop else None
    if lock is None:
        if _activate_running("loop" if start_loop else "activate", games, hidden):
            sys.exit(0)
        QMessageBox.information(
            None,
            "すでに起動しています",
            "ツムツム オートプレイは、すでに開いています。",
        )
        sys.exit(0)
    app._instance_lock = lock
    QLocalServer.removeServer(IPC_NAME)
    window = MainWindow()
    if hidden:
        window.hide()
    else:
        window.show()
    if start_loop:
        QTimer.singleShot(0, lambda: window.on_loop_play(games))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
