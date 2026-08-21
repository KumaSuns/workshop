from __future__ import annotations

import json
import sys
from pathlib import Path

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


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("TsumTsum Screen Trainer")
    app.setOrganizationName("workshop")
    paths = _initial_paths(sys.argv)

    lock = QLockFile(str(Path(QDir.tempPath()) / f"{IPC_NAME}.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
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
