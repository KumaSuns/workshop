from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

from PySide6.QtCore import QDir, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow
from app.paths import IPC_NAME


def _initial_paths(argv: list[str]) -> list[str]:
    if "--import-json" in argv:
        index = argv.index("--import-json")
        if index + 1 < len(argv):
            payload = json.loads(Path(argv[index + 1]).read_text(encoding="utf-8"))
            return [str(path) for path in payload.get("paths", [])]
    return [arg for arg in argv[1:] if not arg.startswith("-") and Path(arg).exists()]


def _handoff_to_running(paths: list[str]) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(IPC_NAME)
    if not sock.waitForConnected(400):
        return False
    payload = json.dumps({"paths": paths}, ensure_ascii=False) + "\n"
    sock.write(payload.encode("utf-8"))
    sock.waitForBytesWritten(800)
    sock.waitForReadyRead(800)
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
    app.setApplicationName("TsumTsum Screen Trainer")
    app.setOrganizationName("workshop")
    paths = _initial_paths(sys.argv)

    lock = _acquire_instance_lock()
    if lock is None:
        if _handoff_to_running(paths):
            sys.exit(0)
        QMessageBox.information(
            None,
            "すでに起動しています",
            "ツムツム ゲーム範囲トレーナーは、すでに開いています。",
        )
        sys.exit(0)
    app._instance_lock = lock
    QLocalServer.removeServer(IPC_NAME)

    window = MainWindow()
    window.showMaximized()
    if paths:
        QTimer.singleShot(0, lambda: window.import_incoming_paths(paths))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
