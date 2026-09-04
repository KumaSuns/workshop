from __future__ import annotations

import io
import socket
import threading
import time

import qrcode
import uvicorn
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import auth
from app.awake import stay_awake
from app.server import BIND_HOST, PORT, create_app
from app.tunnel import Tunnel


class ServerThread(QThread):
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._server: uvicorn.Server | None = None

    def run(self) -> None:
        config = uvicorn.Config(
            create_app(),
            host=BIND_HOST,
            port=PORT,
            log_level="warning",
            ws_max_size=16 * 1024 * 1024,
        )
        self._server = uvicorn.Server(config)
        try:
            self._server.run()
        except Exception as exc:
            self.failed.emit(str(exc))

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True


class MainWindow(QMainWindow):
    status_text = Signal(str)
    public_url = Signal(str)
    fail_text = Signal(str)
    progress = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PC 遠隔操作")
        self._server: ServerThread | None = None
        self._tunnel = Tunnel()
        self._password = auth.load_or_create_password()
        root = QWidget()
        layout = QVBoxLayout(root)
        self._status = QLabel("停止中")
        layout.addWidget(self._status)
        self._bar = QProgressBar()
        self._bar.setTextVisible(False)
        self._bar.hide()
        layout.addWidget(self._bar)
        layout.addWidget(QLabel("パスワードは 9090"))
        self._pass = QLineEdit(self._password)
        self._pass.setReadOnly(True)
        layout.addWidget(self._pass)
        layout.addWidget(QLabel("アドレス"))
        self._public = QLineEdit()
        self._public.setReadOnly(True)
        self._public.setPlaceholderText("準備しています")
        layout.addWidget(self._public)
        self._public_qr = QLabel()
        self._public_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._public_qr)
        start = QPushButton("開始")
        start.clicked.connect(self._start)
        layout.addWidget(start)
        stop = QPushButton("停止")
        stop.clicked.connect(self._stop)
        layout.addWidget(stop)
        layout.addStretch(1)
        self.setCentralWidget(root)
        self.status_text.connect(self._status.setText)
        self.public_url.connect(self._set_public)
        self.fail_text.connect(self._on_fail)
        self.progress.connect(self._set_progress)
        self._awake_timer = QTimer(self)
        self._awake_timer.setInterval(30000)
        self._awake_timer.timeout.connect(lambda: stay_awake(True))
        stay_awake(True)
        self._awake_timer.start()
        self.resize(420, 720)
        QTimer.singleShot(0, self._start)

    def _start(self) -> None:
        if self._server is not None:
            return
        self._server = ServerThread()
        self._server.failed.connect(self.fail_text)
        self._server.start()
        self._status.setText("開始しています")
        self._set_progress(0, 0)
        threading.Thread(target=self._open_public, daemon=True).start()

    def _open_public(self) -> None:
        try:
            self.status_text.emit("待ち受けを確認しています")
            _wait_port("127.0.0.1", PORT)
            self.status_text.emit("アドレスを出しています")
            self.progress.emit(0, 0)
            self._tunnel.start(f"http://127.0.0.1:{PORT}")
        except Exception as exc:
            self.progress.emit(-1, 0)
            self.status_text.emit("アドレスが出ませんでした")
            self.public_url.emit("")
            self.fail_text.emit(str(exc))
            return
        self.progress.emit(-1, 0)
        self.public_url.emit(self._tunnel.url)
        self.status_text.emit("公開中")

    def _set_progress(self, value: int, maximum: int) -> None:
        if value < 0:
            self._bar.hide()
            self._bar.setRange(0, 1)
            self._bar.setValue(0)
            return
        self._bar.show()
        if maximum <= 0:
            self._bar.setRange(0, 0)
            return
        self._bar.setRange(0, maximum)
        self._bar.setValue(min(value, maximum))

    def _set_public(self, url: str) -> None:
        self._public.setText(url)
        self._public_qr.setPixmap(_qr_pixmap(url) if url else QPixmap())

    def _on_fail(self, text: str) -> None:
        QMessageBox.warning(self, "PC 遠隔操作", text)

    def _stop(self) -> None:
        self._tunnel.stop()
        if self._server is not None:
            self._server.stop()
            self._server.wait(3000)
            self._server = None
        self._public.clear()
        self._public_qr.clear()
        self._set_progress(-1, 0)
        self._status.setText("停止中")

    def closeEvent(self, event) -> None:
        self._awake_timer.stop()
        stay_awake(False)
        self._stop()
        super().closeEvent(event)


def _wait_port(host: str, port: int) -> None:
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("待ち受けが始まりませんでした。")


def _qr_pixmap(text: str) -> QPixmap:
    image = qrcode.make(text)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    pix = QPixmap()
    pix.loadFromData(buf.getvalue())
    return pix.scaled(
        180,
        180,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
