from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

MIN_BOX = 16


class ImageCanvas(QGraphicsView):
    regionCommitted = Signal(int, int, int, int)
    filesDropped = Signal(list)
    imageDropped = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

        self._pixmap_item = None
        self._rect_item: QGraphicsRectItem | None = None
        self._caption: QGraphicsSimpleTextItem | None = None
        self._drawing = False
        self._panning = False
        self._origin = QPointF()
        self._pan_pos = QPointF()
        self._should_fit = True
        self._status = "unlabeled"

    def has_image(self) -> bool:
        return self._pixmap_item is not None

    def set_image(self, pixmap: QPixmap, region: QRectF | None = None, status: str = "unlabeled") -> None:
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._rect_item = QGraphicsRectItem()
        self._rect_item.setZValue(1)
        self._scene.addItem(self._rect_item)
        self._caption = QGraphicsSimpleTextItem()
        self._caption.setFlag(
            QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations
        )
        self._caption.setZValue(2)
        self._caption.setFont(QFont("Yu Gothic UI", 10, QFont.Weight.DemiBold))
        self._scene.addItem(self._caption)
        self._should_fit = True
        self.set_region(region, status)
        self.fit_to_view()

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._rect_item = None
        self._caption = None
        self._status = "unlabeled"
        self.resetTransform()

    def set_region(self, region: QRectF | None, status: str = "labeled") -> None:
        self._status = status
        if self._rect_item is None:
            return
        if region is None or region.isEmpty():
            self._rect_item.setVisible(False)
            if self._caption:
                self._caption.setVisible(False)
            return
        self._apply_style(status)
        self._rect_item.setRect(region)
        self._rect_item.setVisible(True)
        self._update_caption()

    def current_region(self) -> QRectF | None:
        if self._rect_item is None or not self._rect_item.isVisible():
            return None
        return self._rect_item.rect()

    def fit_to_view(self) -> None:
        if self._pixmap_item is None or self.viewport().width() < 10:
            return
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._should_fit = True

    def _apply_style(self, status: str) -> None:
        if self._rect_item is None or self._caption is None:
            return
        if status == "predicted":
            color = QColor("#FFB020")
            pen = QPen(color, 2, Qt.PenStyle.DashLine)
            self._caption.setText("予測  違っていたら囲み直してください")
        else:
            color = QColor("#3DDC97")
            pen = QPen(color, 2, Qt.PenStyle.SolidLine)
            self._caption.setText("ゲーム範囲")
        pen.setCosmetic(True)
        self._rect_item.setPen(pen)
        fill = QColor(color)
        fill.setAlpha(40)
        self._rect_item.setBrush(fill)
        self._caption.setBrush(color)

    def _update_caption(self) -> None:
        if self._caption is None or self._rect_item is None:
            return
        rect = self._rect_item.rect()
        if rect.isEmpty():
            self._caption.setVisible(False)
            return
        self._caption.setVisible(True)
        self._caption.setPos(rect.left() + 6, rect.top() + 6)

    def _clamp(self, point: QPointF) -> QPointF:
        if self._pixmap_item is None:
            return point
        bounds = self._pixmap_item.boundingRect()
        return QPointF(
            min(max(point.x(), bounds.left()), bounds.right()),
            min(max(point.y(), bounds.top()), bounds.bottom()),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._should_fit:
            self.fit_to_view()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pixmap_item is None:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._should_fit = False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._pixmap_item is None:
            return
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._panning = True
            self._pan_pos = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            self._origin = self._clamp(self.mapToScene(event.position().toPoint()))
            self.set_region(QRectF(self._origin, self._origin), "labeled")
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position() - self._pan_pos
            self._pan_pos = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            self._should_fit = False
            event.accept()
            return
        if self._drawing and self._rect_item is not None:
            pos = self._clamp(self.mapToScene(event.position().toPoint()))
            self._rect_item.setRect(QRectF(self._origin, pos).normalized())
            self._update_caption()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning and event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._panning = False
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if self._drawing and event.button() == Qt.MouseButton.LeftButton:
            self._drawing = False
            rect = self._rect_item.rect() if self._rect_item else QRectF()
            if rect.width() >= MIN_BOX and rect.height() >= MIN_BOX:
                self.regionCommitted.emit(
                    int(round(rect.x())),
                    int(round(rect.y())),
                    int(round(rect.width())),
                    int(round(rect.height())),
                )
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.fit_to_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [
            url.toLocalFile()
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        elif event.mimeData().hasImage():
            self.imageDropped.emit(event.mimeData().imageData())
            event.acceptProposedAction()
        else:
            event.ignore()
