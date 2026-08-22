from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from PySide6.QtCore import QDir, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow
from app.paths import IPC_NAME


def _activate_running() -> bool:
    sock = QLocalSocket()
    sock.connectToServer(IPC_NAME)
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps({"action": "activate"}, ensure_ascii=False).encode("utf-8") + b"\n")
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
    app = QApplication(sys.argv)
    app.setApplicationName("Video Frame Extractor")
    app.setOrganizationName("workshop")

    lock = _acquire_instance_lock()
    if lock is None:
        if _activate_running():
            sys.exit(0)
        QMessageBox.information(
            None,
            "すでに起動しています",
            "動画フレーム抜き出しは、すでに開いています。",
        )
        sys.exit(0)
    app._instance_lock = lock
    QLocalServer.removeServer(IPC_NAME)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
