from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PySide6.QtNetwork import QLocalSocket

IPC_NAME = "workshop-tsumtsum-screen-recognition"
TSUMTSUM_MAIN = Path(__file__).resolve().parents[1].parent / "tsumtsum-screen-recognition" / "main.py"


def send_images_to_tsumtsum(paths: list[Path]) -> str:
    if not paths:
        raise ValueError("渡す画像がありません")
    payload = json.dumps({"paths": [str(path) for path in paths]}, ensure_ascii=False) + "\n"
    sock = QLocalSocket()
    sock.connectToServer(IPC_NAME)
    if sock.waitForConnected(600):
        sock.write(payload.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(1500)
        sock.waitForReadyRead(2000)
        sock.disconnectFromServer()
        if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            sock.waitForDisconnected(500)
        return "sent"
    if not TSUMTSUM_MAIN.exists():
        raise FileNotFoundError(f"ツムツムアプリが見つかりません。\n{TSUMTSUM_MAIN}")
    kwargs: dict = {"cwd": str(TSUMTSUM_MAIN.parent)}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, str(TSUMTSUM_MAIN), *[str(path) for path in paths]], **kwargs)
    return "launched"
