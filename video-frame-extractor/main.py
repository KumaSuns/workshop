from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QDir, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

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


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Video Frame Extractor")
    app.setOrganizationName("workshop")

    lock = QLockFile(str(Path(QDir.tempPath()) / f"{IPC_NAME}.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        if _activate_running():
            sys.exit(0)
        sys.exit(0)
    app._instance_lock = lock
    QLocalServer.removeServer(IPC_NAME)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
