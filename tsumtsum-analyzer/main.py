from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

from PySide6.QtCore import QDir, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.paths import ANALYZE_ROOT, APP_ROOT, IPC_NAME

_WINDOW_TITLE = "ツムツム解析"


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


def _lock_pid(lock: QLockFile) -> int:
    try:
        pid, _hostname, _app = lock.getLockInfo()
    except Exception:
        return 0
    return int(pid or 0)


def _analyzer_hwnd(pid: int) -> int:
    if pid <= 0 or os.name != "nt":
        return 0
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if int(proc.value) != pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value == _WINDOW_TITLE:
            found.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(enum_proc(visit), 0)
    return found[0] if found else 0


def _raise_hwnd(hwnd: int) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)


def _end_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )


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


def _resolve_lock() -> QLockFile | None:
    lock = _acquire_instance_lock()
    if lock is not None:
        return lock
    held = QLockFile(str(Path(QDir.tempPath()) / f"{IPC_NAME}.lock"))
    pid = _lock_pid(held)
    hwnd = _analyzer_hwnd(pid)
    if hwnd:
        if os.name == "nt":
            try:
                import ctypes

                ctypes.windll.user32.AllowSetForegroundWindow(pid)
            except Exception:
                pass
        _activate_running()
        _raise_hwnd(hwnd)
        return None
    _end_pid(pid)
    for _ in range(20):
        if _lock_holder_dead(held):
            break
        time.sleep(0.1)
    held.removeStaleLockFile()
    return _acquire_instance_lock()


def _serve(window) -> QLocalServer:
    QLocalServer.removeServer(IPC_NAME)
    server = QLocalServer()
    server.listen(IPC_NAME)

    def on_connection() -> None:
        sock = server.nextPendingConnection()
        window.showMaximized()
        window.raise_()
        window.activateWindow()
        if sock is not None:
            sock.waitForReadyRead(200)
            sock.disconnectFromServer()
            sock.deleteLater()

    server.newConnection.connect(on_connection)
    return server


def main() -> None:
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(ANALYZE_ROOT))
    from tsumtsum_analyze.roots import set_roots
    from app.paths import ASSETS_DIR, DATA_DIR

    set_roots(data_dir=DATA_DIR, assets_dir=ASSETS_DIR)

    app = QApplication(sys.argv)
    app.setApplicationName("TsumTsum Analyzer")
    app.setOrganizationName("workshop")
    icon = APP_ROOT / "app.ico"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))

    lock = _resolve_lock()
    if lock is None:
        sys.exit(0)
    app._instance_lock = lock

    from app.main_window import MainWindow

    window = MainWindow()
    app._instance_server = _serve(window)
    window.showMaximized()
    window.raise_()
    window.activateWindow()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
