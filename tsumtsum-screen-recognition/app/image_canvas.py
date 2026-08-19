from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView, QLabel

from app.regions import REGION_COLORS, REGION_LABELS

MIN_BOX = 8
CORNER = 14
EDGE_LEN = 36
EDGE_THICK = 12

HANDLE_CURSORS = {
    "nw": Qt.CursorShape.SizeFDiagCursor,
    "n": Qt.CursorShape.SizeVerCursor,
    "ne": Qt.CursorShape.SizeBDiagCursor,
    "e": Qt.CursorShape.SizeHorCursor,
    "se": Qt.CursorShape.SizeFDiagCursor,
    "s": Qt.CursorShape.SizeVerCursor,
    "sw": Qt.CursorShape.SizeBDiagCursor,
    "w": Qt.CursorShape.SizeHorCursor,
}


class ImageCanvas(QGraphicsView):
    regionCommitted = Signal(int, int, int, int)
    regionChanged = Signal(int, int, int, int)
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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)

        self._pixmap_item = None
        self._region: QRectF | None = None
        self._regions: dict[str, QRectF] = {}
        self._active_key = "game"
        self._status = "unlabeled"
        self._mode: str | None = None
        self._handle: str | None = None
        self._origin = QPointF()
        self._orig_rect = QRectF()
        self._pan_pos = QPointF()
        self._should_fit = True

        self._guide = QLabel(self)
        self._guide.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._guide.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._guide.setStyleSheet(
            "QLabel { background: rgba(12, 14, 18, 210); color: #f2f5f8; "
            "padding: 8px 14px; border-radius: 8px; font-size: 13px; }"
        )
        self._update_guide()

    def has_image(self) -> bool:
        return self._pixmap_item is not None

    def set_image(
        self,
        pixmap: QPixmap,
        region: QRectF | None = None,
        status: str = "unlabeled",
        regions: dict[str, QRectF] | None = None,
        active_key: str = "game",
    ) -> None:
        self._scene.clear()
        self._pixmap_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._should_fit = True
        self._mode = None
        self._active_key = active_key
        self._regions = {key: QRectF(rect) for key, rect in (regions or {}).items()}
        if region is not None and "game" not in self._regions:
            self._regions["game"] = QRectF(region)
        self._status = status
        self._region = self._regions.get(self._active_key)
        self.fit_to_view()
        self._update_guide()
        self.viewport().update()

    def set_active_key(self, key: str) -> None:
        self._sync_active()
        self._active_key = key
        self._region = self._regions.get(key)
        self._update_guide()
        self.viewport().update()

    def all_region_boxes(self) -> dict[str, dict[str, int]]:
        self._sync_active()
        boxes: dict[str, dict[str, int]] = {}
        for key, rect in self._regions.items():
            if rect is None or rect.width() < MIN_BOX or rect.height() < MIN_BOX:
                continue
            boxes[key] = {
                "x": int(round(rect.x())),
                "y": int(round(rect.y())),
                "w": int(round(rect.width())),
                "h": int(round(rect.height())),
            }
        return boxes

    def _sync_active(self) -> None:
        if self._region is None or self._region.width() < 1 or self._region.height() < 1:
            self._regions.pop(self._active_key, None)
        else:
            self._regions[self._active_key] = QRectF(self._region)

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._region = None
        self._regions = {}
        self._status = "unlabeled"
        self._mode = None
        self.resetTransform()
        self._update_guide()
        self.viewport().update()

    def set_region(self, region: QRectF | None, status: str = "labeled", emit: bool = False) -> None:
        self._status = status
        if region is None or region.isEmpty():
            self._region = None
            self._regions.pop(self._active_key, None)
        else:
            self._region = QRectF(self._clamp_rect(region))
            self._regions[self._active_key] = QRectF(self._region)
        self._update_guide()
        self.viewport().update()
        if emit:
            self._emit_region(self.regionChanged)

    def current_region(self) -> QRectF | None:
        return QRectF(self._region) if self._region else None

    def fit_to_view(self) -> None:
        if self._pixmap_item is None or self.viewport().width() < 10:
            return
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._should_fit = True
        self.viewport().update()

    def _update_guide(self) -> None:
        if self._pixmap_item is None:
            self._guide.setText("画像をドロップ  /  Ctrl+V で貼り付け  /  「画像を開く」")
        elif self._region is None:
            name = REGION_LABELS.get(self._active_key, "範囲")
            self._guide.setText(f"「{name}」をドラッグして囲んでください")
        else:
            name = REGION_LABELS.get(self._active_key, "範囲")
            self._guide.setText(f"「{name}」  四隅で拡大縮小  ・  辺の中央は縦だけ / 横だけ  ・  「この範囲を保存」")
        self._guide.adjustSize()
        self._place_guide()

    def _place_guide(self) -> None:
        margin = 12
        self._guide.move(max(margin, (self.width() - self._guide.width()) // 2), margin)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_guide()
        if self._should_fit:
            self.fit_to_view()

    def drawForeground(self, painter: QPainter, _rect: QRectF) -> None:
        if self._pixmap_item is None:
            return
        painter.save()
        painter.resetTransform()
        self._sync_active()
        font = QFont("Yu Gothic UI", 9, QFont.Weight.DemiBold)
        painter.setFont(font)
        for key, rect in self._regions.items():
            if rect is None or rect.width() < 1 or rect.height() < 1:
                continue
            view = QRectF(self._view_rect_from_scene(rect))
            accent = QColor(REGION_COLORS.get(key, "#5CFF9E"))
            if key == "game" and self._status == "predicted" and key == self._active_key:
                accent = QColor("#FFB020")
            active = key == self._active_key
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if active:
                painter.setPen(QPen(QColor(255, 255, 255, 230), 4))
                painter.drawRect(view)
            painter.setPen(QPen(accent, 2 if active else 1, Qt.PenStyle.SolidLine))
            painter.drawRect(view)
            label = REGION_LABELS.get(key, key)
            if active:
                label = f"{label}  {int(round(rect.width()))}×{int(round(rect.height()))}"
            metrics = painter.fontMetrics()
            text_w = metrics.horizontalAdvance(label) + 12
            text_h = metrics.height() + 6
            badge = QRect(int(view.left()), max(4, int(view.top()) - text_h - 2), text_w, text_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(12, 16, 20, 220))
            painter.drawRoundedRect(badge, 5, 5)
            painter.setPen(accent)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)
        if self._region is not None and self._region.width() >= 1:
            painter.setPen(QPen(QColor("white"), 2))
            painter.setBrush(QColor(REGION_COLORS.get(self._active_key, "#5CFF9E")))
            for name, handle in self._handle_rects_view().items():
                if name in {"n", "s", "e", "w"}:
                    painter.drawRoundedRect(handle, 4, 4)
                else:
                    painter.drawRect(handle)
        painter.restore()

    def _view_rect_from_scene(self, rect: QRectF) -> QRect:
        bounds = self.mapFromScene(rect).boundingRect()
        if isinstance(bounds, QRectF):
            return bounds.toRect()
        return QRect(bounds)

    def _viewport_pos(self, event: QMouseEvent) -> QPoint:
        return event.position().toPoint()

    def _handle_rects_view(self) -> dict[str, QRect]:
        if self._region is None:
            return {}
        r = self._view_rect_from_scene(self._region)
        cx, cy = r.center().x(), r.center().y()
        c = CORNER
        return {
            "nw": QRect(r.left() - c // 2, r.top() - c // 2, c, c),
            "ne": QRect(r.right() - c // 2, r.top() - c // 2, c, c),
            "se": QRect(r.right() - c // 2, r.bottom() - c // 2, c, c),
            "sw": QRect(r.left() - c // 2, r.bottom() - c // 2, c, c),
            "n": QRect(cx - EDGE_LEN // 2, r.top() - EDGE_THICK // 2, EDGE_LEN, EDGE_THICK),
            "s": QRect(cx - EDGE_LEN // 2, r.bottom() - EDGE_THICK // 2, EDGE_LEN, EDGE_THICK),
            "e": QRect(r.right() - EDGE_THICK // 2, cy - EDGE_LEN // 2, EDGE_THICK, EDGE_LEN),
            "w": QRect(r.left() - EDGE_THICK // 2, cy - EDGE_LEN // 2, EDGE_THICK, EDGE_LEN),
        }

    def _hit_handle(self, pos: QPoint) -> str | None:
        handles = self._handle_rects_view()
        for name in ("nw", "ne", "se", "sw", "n", "s", "e", "w"):
            rect = handles.get(name)
            if rect is not None and rect.adjusted(-6, -6, 6, 6).contains(pos):
                return name
        return None

    def _region_contains_view(self, pos: QPoint) -> bool:
        if self._region is None:
            return False
        return self._view_rect_from_scene(self._region).contains(pos)

    def _clamp_point(self, point: QPointF) -> QPointF:
        if self._pixmap_item is None:
            return point
        bounds = self._pixmap_item.boundingRect()
        return QPointF(
            min(max(point.x(), bounds.left()), bounds.right()),
            min(max(point.y(), bounds.top()), bounds.bottom()),
        )

    def _clamp_rect(self, rect: QRectF) -> QRectF:
        if self._pixmap_item is None:
            return rect
        bounds = self._pixmap_item.boundingRect()
        r = rect.normalized()
        x = min(max(r.x(), bounds.left()), bounds.right() - MIN_BOX)
        y = min(max(r.y(), bounds.top()), bounds.bottom() - MIN_BOX)
        w = min(max(r.width(), MIN_BOX), bounds.right() - x)
        h = min(max(r.height(), MIN_BOX), bounds.bottom() - y)
        return QRectF(x, y, w, h)

    def _emit_region(self, signal) -> None:
        if self._region is None:
            return
        signal.emit(
            int(round(self._region.x())),
            int(round(self._region.y())),
            int(round(self._region.width())),
            int(round(self._region.height())),
        )

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._pixmap_item is None:
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._should_fit = False
        self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._pixmap_item is None:
            return
        self.setFocus()
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._mode = "pan"
            self._pan_pos = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        view_pos = self._viewport_pos(event)
        scene_pos = self._clamp_point(self.mapToScene(view_pos))
        handle = self._hit_handle(view_pos)
        if handle and self._region is not None:
            self._mode = "resize"
            self._handle = handle
            self._orig_rect = QRectF(self._region)
            self.viewport().setCursor(HANDLE_CURSORS[handle])
            event.accept()
            return
        if self._region_contains_view(view_pos) and self._region is not None:
            self._mode = "move"
            self._origin = scene_pos
            self._orig_rect = QRectF(self._region)
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
            return
        self._mode = "draw"
        self._origin = scene_pos
        self._status = "labeled"
        self._region = QRectF(self._origin, self._origin)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self._update_guide()
        self.viewport().update()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._mode == "pan":
            delta = event.position() - self._pan_pos
            self._pan_pos = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            self._should_fit = False
            self.viewport().update()
            event.accept()
            return

        scene_pos = self._clamp_point(self.mapToScene(self._viewport_pos(event)))
        if self._mode == "draw":
            self._region = QRectF(self._origin, scene_pos).normalized()
            self.viewport().update()
            self._emit_region(self.regionChanged)
            event.accept()
            return
        if self._mode == "move" and self._region is not None:
            delta = scene_pos - self._origin
            self._region = self._clamp_rect(self._orig_rect.translated(delta))
            self.viewport().update()
            self._emit_region(self.regionChanged)
            event.accept()
            return
        if self._mode == "resize" and self._handle:
            self._region = self._resized_rect(scene_pos)
            self.viewport().update()
            self._emit_region(self.regionChanged)
            event.accept()
            return

        self._update_hover_cursor(self._viewport_pos(event))
        super().mouseMoveEvent(event)

    def _resized_rect(self, pos: QPointF) -> QRectF:
        r = QRectF(self._orig_rect)
        handle = self._handle or ""
        if handle in {"nw", "w", "sw"}:
            r.setLeft(pos.x())
        if handle in {"ne", "e", "se"}:
            r.setRight(pos.x())
        if handle in {"nw", "n", "ne"}:
            r.setTop(pos.y())
        if handle in {"sw", "s", "se"}:
            r.setBottom(pos.y())
        return self._clamp_rect(r)

    def _update_hover_cursor(self, view_pos: QPoint) -> None:
        handle = self._hit_handle(view_pos)
        if handle:
            self.viewport().setCursor(HANDLE_CURSORS[handle])
        elif self._region_contains_view(view_pos):
            self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._mode == "pan" and event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.RightButton,
        ):
            self._mode = None
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if self._mode in {"draw", "move", "resize"} and event.button() == Qt.MouseButton.LeftButton:
            if self._region is not None and self._region.width() >= MIN_BOX and self._region.height() >= MIN_BOX:
                self._region = self._clamp_rect(self._region)
                self._status = "labeled"
                self._sync_active()
                self._emit_region(self.regionCommitted)
            elif self._mode == "draw":
                self._region = None
                self._sync_active()
            self._mode = None
            self._handle = None
            self._update_guide()
            self.viewport().update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.fit_to_view()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:
        mods = event.modifiers()
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and not (
            mods & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            event.ignore()
            return
        if self._region is None:
            super().keyPressEvent(event)
            return
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        r = QRectF(self._region)
        key = event.key()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Left:
                r.setWidth(r.width() - step)
            elif key == Qt.Key.Key_Right:
                r.setWidth(r.width() + step)
            elif key == Qt.Key.Key_Up:
                r.setHeight(r.height() - step)
            elif key == Qt.Key.Key_Down:
                r.setHeight(r.height() + step)
            else:
                super().keyPressEvent(event)
                return
        else:
            if key == Qt.Key.Key_Left:
                r.translate(-step, 0)
            elif key == Qt.Key.Key_Right:
                r.translate(step, 0)
            elif key == Qt.Key.Key_Up:
                r.translate(0, -step)
            elif key == Qt.Key.Key_Down:
                r.translate(0, step)
            else:
                super().keyPressEvent(event)
                return
        self._region = self._clamp_rect(r)
        self._status = "labeled"
        self.viewport().update()
        self._emit_region(self.regionChanged)
        self._emit_region(self.regionCommitted)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        elif event.mimeData().hasImage():
            self.imageDropped.emit(event.mimeData().imageData())
            event.acceptProposedAction()
        else:
            event.ignore()
