from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QPushButton, QVBoxLayout


class TrainOverlay(QFrame):
    cancelRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("trainOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QFrame#trainOverlay {
                background: rgba(12, 14, 18, 210);
                border: none;
            }
            QLabel#trainTitle {
                color: #f2f5f8;
                font-size: 28px;
                font-weight: 700;
            }
            QLabel#trainDetail {
                color: #d7dde6;
                font-size: 16px;
            }
            QProgressBar {
                background: #101216;
                border: 1px solid #3a4250;
                border-radius: 8px;
                text-align: center;
                color: #e8eaed;
                min-height: 22px;
                font-size: 13px;
            }
            QProgressBar::chunk { background: #5b6cff; border-radius: 8px; }
            QPushButton#trainCancel {
                background: #c23b4a;
                color: #f2f5f8;
                font-size: 16px;
                font-weight: 700;
                border: none;
                border-radius: 10px;
                padding: 10px 28px;
                min-width: 140px;
            }
            QPushButton#trainCancel:hover { background: #e04b5c; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch(1)
        self.title = QLabel("学習中です")
        self.title.setObjectName("trainTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.detail = QLabel("画像を読んでいます…")
        self.detail.setObjectName("trainDetail")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        layout.addWidget(self.bar)
        self.cancel_btn = QPushButton("中止")
        self.cancel_btn.setObjectName("trainCancel")
        self.cancel_btn.clicked.connect(self.cancelRequested.emit)
        layout.addWidget(self.cancel_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        self.hide()

    def start(self) -> None:
        self.title.setText("学習中です")
        self.detail.setText("画像を読んでいます…")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("中止")
        self._place()
        self.show()
        self.raise_()

    def set_progress(self, current: int, total: int, message: str) -> None:
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(current)
        self.detail.setText(message)
        self._place()

    def set_cancelling(self) -> None:
        self.title.setText("中止しています")
        self.detail.setText("この epoch が終わるまで待っています…")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("中止しています…")

    def stop(self) -> None:
        self.hide()

    def _place(self) -> None:
        host = self.parentWidget()
        if host is not None:
            self.setGeometry(host.rect())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()
