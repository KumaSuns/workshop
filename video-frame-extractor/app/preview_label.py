from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap, QResizeEvent
from PySide6.QtWidgets import QLabel


class ImagePreview(QLabel):
    box_changed = Signal(dict)

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._source: QPixmap | None = None
        self._box: dict[str, int] | None = None
        self._drag_origin: QPoint | None = None
        self.editable = False

    def set_image(self, pixmap: QPixmap | None, box: dict[str, int] | None = None) -> None:
        self._source = pixmap
        self._box = dict(box) if box else None
        self._render()

    def box(self) -> dict[str, int] | None:
        return dict(self._box) if self._box else None

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._render()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self.editable:
            return
        pos = self._to_image(event.position().toPoint())
        if pos is None:
            return
        self._drag_origin = pos
        self._box = {"x": pos.x(), "y": pos.y(), "w": 1, "h": 1}
        self._render()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is None or self._source is None:
            return
        pos = self._to_image(event.position().toPoint())
        if pos is None:
            return
        x0, y0 = self._drag_origin.x(), self._drag_origin.y()
        x1, y1 = pos.x(), pos.y()
        x = max(0, min(x0, x1))
        y = max(0, min(y0, y1))
        w = max(1, abs(x1 - x0))
        h = max(1, abs(y1 - y0))
        w = min(w, self._source.width() - x)
        h = min(h, self._source.height() - y)
        self._box = {"x": x, "y": y, "w": w, "h": h}
        self._render()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is None:
            return
        self._drag_origin = None
        if self._box is not None and self._box["w"] >= 4 and self._box["h"] >= 4:
            self.box_changed.emit(dict(self._box))

    def _pixmap_rect(self) -> QRect:
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return QRect()
        return QRect(
            (self.width() - pixmap.width()) // 2,
            (self.height() - pixmap.height()) // 2,
            pixmap.width(),
            pixmap.height(),
        )

    def _to_image(self, pos: QPoint) -> QPoint | None:
        if self._source is None or self._source.isNull():
            return None
        rect = self._pixmap_rect()
        if not rect.contains(pos):
            return None
        x = int((pos.x() - rect.x()) * self._source.width() / max(rect.width(), 1))
        y = int((pos.y() - rect.y()) * self._source.height() / max(rect.height(), 1))
        x = max(0, min(x, self._source.width() - 1))
        y = max(0, min(y, self._source.height() - 1))
        return QPoint(x, y)

    def _render(self) -> None:
        if self._source is None or self._source.isNull():
            self.setPixmap(QPixmap())
            return
        scaled = self._source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if self._box is not None and scaled.width() > 0 and scaled.height() > 0:
            painter = QPainter(scaled)
            painter.setPen(QPen(QColor("#3DDC97"), 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            sx = scaled.width() / self._source.width()
            sy = scaled.height() / self._source.height()
            painter.drawRect(
                int(self._box["x"] * sx),
                int(self._box["y"] * sy),
                max(2, int(self._box["w"] * sx)),
                max(2, int(self._box["h"] * sy)),
            )
            painter.end()
        self.setPixmap(scaled)
