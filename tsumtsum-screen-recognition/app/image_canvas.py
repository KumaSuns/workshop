from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView, QLabel

from app.regions import (
    PIECE_COLORS,
    PIECE_KEYS,
    PIECE_LABELS,
    REGION_COLORS,
    REGION_LABELS,
    SCENE_LABELS,
    is_piece_key,
    is_scene_key,
    piece_radius_from_game,
    tsum_group_color,
)
from app.tsum_chain import tsum_chain_candidates

MIN_BOX = 8
MIN_RADIUS = 8
DEFAULT_RADIUS = 36
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
    piecesChanged = Signal()
    pieceGroupChanged = Signal(int)
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
        self.viewport().setMouseTracking(True)
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
        self._pieces: list[dict[str, int]] = []
        self._selected_piece: int | None = None
        self._piece_group = 1
        self._piece_radius = {key: DEFAULT_RADIUS for key in PIECE_KEYS}
        self._hover_pos: QPointF | None = None
        self._visible_keys: set[str] | None = None
        self._trace_pts: list[QPointF] = []
        self._trace_group = 1
        self._trace_t = 0.0
        self._trace_timer = QTimer(self)
        self._trace_timer.setInterval(16)
        self._trace_timer.timeout.connect(self._on_trace_tick)

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
        pieces: list[dict[str, int]] | None = None,
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
        self._region = None if is_piece_key(active_key) or is_scene_key(active_key) else self._regions.get(self._active_key)
        self._pieces = [dict(piece) for piece in (pieces or [])]
        self._selected_piece = None
        self._hover_pos = None
        self.stop_chain_trace()
        game = self._game_rect()
        if game is not None:
            for key in PIECE_KEYS:
                self._piece_radius[key] = self._radius_from_game(key)
        self.fit_to_view()
        self._update_guide()
        self.viewport().update()

    def set_active_key(self, key: str) -> None:
        if not is_piece_key(self._active_key):
            self._sync_active()
        self._active_key = key
        if is_piece_key(key) or is_scene_key(key):
            self._region = None
            self._selected_piece = None
            self._hover_pos = None
            if is_scene_key(key):
                self.fit_to_view()
                self._update_guide()
                self.viewport().update()
                return
            game = self._game_rect()
            if game is not None:
                auto_r = self._radius_from_game(key)
                if self._piece_radius[key] == DEFAULT_RADIUS:
                    self._piece_radius[key] = auto_r
        else:
            self._region = self._regions.get(key)
            self._hover_pos = None
        self.fit_to_view()
        self._update_guide()
        self.viewport().update()

    def set_visible_keys(self, keys: list[str] | None) -> None:
        self._visible_keys = set(keys) if keys is not None else None
        self.viewport().update()

    def _key_is_visible(self, key: str) -> bool:
        if self._visible_keys is None:
            return True
        return key in self._visible_keys or key == self._active_key

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
        if is_piece_key(self._active_key) or is_scene_key(self._active_key):
            return
        if self._region is None or self._region.width() < 1 or self._region.height() < 1:
            self._regions.pop(self._active_key, None)
        else:
            self._regions[self._active_key] = QRectF(self._region)

    def all_pieces(self) -> list[dict[str, int]]:
        return [dict(piece) for piece in self._pieces]

    def set_piece_group(self, group: int) -> None:
        self._piece_group = max(1, min(12, int(group)))
        self._update_guide()
        self.pieceGroupChanged.emit(self._piece_group)
        self.viewport().update()

    def piece_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        bombs = 0
        for piece in self._pieces:
            if piece["kind"] == "bomb":
                bombs += 1
                continue
            key = f"ツム{piece.get('group', 1)}"
            counts[key] = counts.get(key, 0) + 1
        if bombs:
            counts["ボム"] = bombs
        return counts

    def chain_candidates(self) -> list[list[dict[str, int]]]:
        return tsum_chain_candidates(self._pieces)

    def start_chain_trace(self, index: int = 0) -> bool:
        candidates = tsum_chain_candidates(self._pieces)
        if index < 0 or index >= len(candidates):
            return False
        path = candidates[index]
        if len(path) < 2:
            return False
        self._trace_pts = [QPointF(int(piece["x"]), int(piece["y"])) for piece in path]
        self._trace_group = int(path[0].get("group") or 1)
        self._trace_t = 0.0
        self._trace_timer.start()
        self.viewport().update()
        return True

    def stop_chain_trace(self) -> None:
        self._trace_timer.stop()
        self._trace_pts = []
        self._trace_t = 0.0
        self.viewport().update()

    def _on_trace_tick(self) -> None:
        if len(self._trace_pts) < 2:
            self._trace_timer.stop()
            return
        last = float(len(self._trace_pts) - 1)
        self._trace_t = min(last, self._trace_t + 0.12)
        if self._trace_t >= last:
            self._trace_timer.stop()
        self.viewport().update()

    def _clear_chain_trace(self) -> None:
        if self._trace_pts or self._trace_timer.isActive():
            self.stop_chain_trace()

    def remove_selected_piece(self) -> bool:
        if self._selected_piece is None:
            return False
        return self._remove_piece_at(self._selected_piece)

    def _remove_piece_at(self, index: int) -> bool:
        if index < 0 or index >= len(self._pieces):
            return False
        self._pieces.pop(index)
        if self._selected_piece is not None:
            if self._selected_piece == index:
                self._selected_piece = None
            elif self._selected_piece > index:
                self._selected_piece -= 1
        self._clear_chain_trace()
        self.piecesChanged.emit()
        self._update_guide()
        self.viewport().update()
        return True

    def undo_last_piece(self, kind: str | None = None) -> bool:
        target = kind if kind in PIECE_KEYS else (self._active_key if is_piece_key(self._active_key) else None)
        if target is None:
            return False
        for index in range(len(self._pieces) - 1, -1, -1):
            if self._pieces[index].get("kind") == target:
                self._pieces.pop(index)
                if self._selected_piece is not None:
                    if self._selected_piece == index:
                        self._selected_piece = None
                    elif self._selected_piece > index:
                        self._selected_piece -= 1
                self._clear_chain_trace()
                self.piecesChanged.emit()
                self._update_guide()
                self.viewport().update()
                return True
        return False

    def has_piece_of_kind(self, kind: str) -> bool:
        return any(piece.get("kind") == kind for piece in self._pieces)

    def set_default_radius(self, kind: str, radius: int) -> None:
        self._piece_radius[kind] = max(MIN_RADIUS, int(radius))
        if self._selected_piece is not None:
            piece = self._pieces[self._selected_piece]
            if piece["kind"] == kind:
                piece["r"] = self._piece_radius[kind]
                self._clamp_piece(piece)
                self.piecesChanged.emit()
                self.viewport().update()

    def clear_pieces_of_kind(self, kind: str) -> None:
        self._pieces = [piece for piece in self._pieces if piece["kind"] != kind]
        self._selected_piece = None
        self._clear_chain_trace()
        self.piecesChanged.emit()
        self._update_guide()
        self.viewport().update()

    def clear_image(self) -> None:
        self._scene.clear()
        self._pixmap_item = None
        self._region = None
        self._regions = {}
        self._pieces = []
        self._selected_piece = None
        self._status = "unlabeled"
        self._mode = None
        self.stop_chain_trace()
        self.resetTransform()
        self._update_guide()
        self.viewport().update()

    def set_region(self, region: QRectF | None, status: str = "labeled", emit: bool = False) -> None:
        if is_piece_key(self._active_key):
            return
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

    def _game_rect(self) -> QRectF | None:
        rect = self._regions.get("game")
        if rect is None or rect.width() < MIN_BOX or rect.height() < MIN_BOX:
            return None
        return QRectF(rect)

    def _radius_from_game(self, kind: str) -> int:
        game = self._game_rect()
        if game is None:
            return DEFAULT_RADIUS
        return piece_radius_from_game(game.width(), kind)

    def radius_for_kind(self, kind: str) -> int:
        return self._radius_from_game(kind)

    def _effective_radius(self, piece: dict[str, int]) -> int:
        kind = str(piece.get("kind") or "tsum")
        expected = self._radius_from_game(kind)
        current = int(piece.get("r") or 0)
        if current < expected * 0.5:
            return expected
        return max(MIN_RADIUS, current)

    def fit_to_view(self) -> None:
        if self._pixmap_item is None or self.viewport().width() < 10:
            return
        target = self._scene.sceneRect()
        if is_piece_key(self._active_key):
            game = self._game_rect()
            if game is not None:
                pad = self._piece_radius.get(self._active_key, DEFAULT_RADIUS)
                target = game.adjusted(-pad, -pad, pad, pad)
        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)
        self._should_fit = True
        self.viewport().update()

    def _update_guide(self) -> None:
        if self._pixmap_item is None:
            self._guide.setText("画像をドロップ  /  Ctrl+V で貼り付け  /  「画像を開く」")
        elif is_scene_key(self._active_key):
            name = SCENE_LABELS.get(self._active_key, "画面")
            self._guide.setText(f"この画像が「{name}」なら保存してください。枠は不要です。")
        elif is_piece_key(self._active_key):
            name = PIECE_LABELS.get(self._active_key, "ツム")
            extra = f"  種類 {self._piece_group}" if self._active_key == "tsum" else ""
            if self._game_rect() is None:
                self._guide.setText(f"「{name}」の前に、ゲーム範囲を保存してください")
            else:
                self._guide.setText(
                    f"「{name}」{extra}  大きい〇がガイドです。ツムに合わせてクリック  ・  ホイールで大きさ  ・  右クリックで削除  ・  1つ戻す / Ctrl+Z"
                )
        elif self._region is None:
            name = REGION_LABELS.get(self._active_key, "範囲")
            self._guide.setText(f"「{name}」をドラッグして囲んでください")
        else:
            name = REGION_LABELS.get(self._active_key, "範囲")
            self._guide.setText(f"「{name}」  四隅で拡大縮小  ・  辺の中央は縦だけ / 横だけ  ・  選んでいる種類を保存")
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
        if is_piece_key(self._active_key):
            game = self._game_rect()
            if game is not None and self._pixmap_item is not None:
                image_view = QRectF(self._view_rect_from_scene(self._pixmap_item.boundingRect()))
                region_view = QRectF(self._view_rect_from_scene(game))
                dim = QPainterPath()
                dim.addRect(image_view)
                hole = QPainterPath()
                hole.addRect(region_view)
                painter.fillPath(dim.subtracted(hole), QColor(0, 0, 0, 170))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#5CFF9E"), 2))
                painter.drawRect(region_view)
            self._draw_pieces(painter)
            painter.restore()
            return
        for key, rect in self._regions.items():
            if rect is None or rect.width() < 1 or rect.height() < 1:
                continue
            if not self._key_is_visible(key):
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
        self._draw_pieces(painter)
        if (
            not is_piece_key(self._active_key)
            and self._region is not None
            and self._region.width() >= 1
        ):
            painter.setPen(QPen(QColor("white"), 2))
            painter.setBrush(QColor(REGION_COLORS.get(self._active_key, "#5CFF9E")))
            for name, handle in self._handle_rects_view().items():
                if name in {"n", "s", "e", "w"}:
                    painter.drawRoundedRect(handle, 4, 4)
                else:
                    painter.drawRect(handle)
        painter.restore()

    def _draw_pieces(self, painter: QPainter) -> None:
        font = QFont("Yu Gothic UI", 8, QFont.Weight.DemiBold)
        painter.setFont(font)
        for index, piece in enumerate(self._pieces):
            kind = piece["kind"]
            if not self._key_is_visible(kind):
                continue
            center = self.mapFromScene(QPointF(piece["x"], piece["y"]))
            radius = self._piece_view_radius(piece)
            if kind == "tsum":
                accent = QColor(tsum_group_color(int(piece.get("group") or 1)))
            else:
                accent = QColor(PIECE_COLORS.get(kind, "#FFE066"))
            selected = index == self._selected_piece and is_piece_key(self._active_key)
            fill = QColor(accent)
            fill.setAlpha(50)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawEllipse(center, radius, radius)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if selected:
                painter.setPen(QPen(QColor(255, 255, 255, 230), 4))
                painter.drawEllipse(center, radius + 1, radius + 1)
            painter.setPen(QPen(accent, 3))
            painter.drawEllipse(center, radius, radius)
            if kind == "bomb":
                text = "B"
            else:
                text = str(piece.get("group", 1))
            metrics = painter.fontMetrics()
            badge = QRect(
                center.x() - metrics.horizontalAdvance(text) // 2 - 4,
                center.y() - metrics.height() // 2 - 2,
                metrics.horizontalAdvance(text) + 8,
                metrics.height() + 4,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(12, 16, 20, 200))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setPen(accent)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        self._draw_piece_guide(painter)
        self._draw_chain_trace(painter)

    def _draw_chain_trace(self, painter: QPainter) -> None:
        if len(self._trace_pts) < 2:
            return
        last = len(self._trace_pts) - 1
        t = max(0.0, min(float(last), self._trace_t))
        views = [QPointF(self.mapFromScene(pt)) for pt in self._trace_pts]
        path = QPainterPath()
        path.moveTo(views[0])
        whole = int(t)
        frac = t - whole
        for index in range(1, whole + 1):
            path.lineTo(views[index])
        if whole < last:
            start = views[whole]
            end = views[whole + 1]
            current = QPointF(
                start.x() + (end.x() - start.x()) * frac,
                start.y() + (end.y() - start.y()) * frac,
            )
            path.lineTo(current)
        else:
            current = views[-1]
        color = QColor(tsum_group_color(self._trace_group))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(QColor(255, 255, 255, 220), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(path)
        painter.setPen(
            QPen(color, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
        painter.setBrush(color)
        painter.drawEllipse(current, 9, 9)

    def _draw_piece_guide(self, painter: QPainter) -> None:
        if (
            not is_piece_key(self._active_key)
            or self._hover_pos is None
            or self._mode == "move-piece"
        ):
            return
        if self._hit_piece(self._hover_pos) is not None:
            return
        game = self._game_rect()
        if game is not None and not game.contains(self._hover_pos):
            return
        kind = self._active_key
        radius = self._piece_radius.get(kind, DEFAULT_RADIUS)
        if kind == "tsum":
            color = QColor(tsum_group_color(self._piece_group))
        else:
            color = QColor(PIECE_COLORS.get(kind, "#FFE066"))
        dummy = {"x": int(self._hover_pos.x()), "y": int(self._hover_pos.y()), "r": int(radius), "kind": kind}
        self._clamp_piece(dummy)
        center = self.mapFromScene(QPointF(dummy["x"], dummy["y"]))
        view_r = self._piece_view_radius(dummy)
        fill = QColor(color)
        fill.setAlpha(70)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(center, view_r, view_r)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(color, 4, Qt.PenStyle.DashLine))
        painter.drawEllipse(center, view_r, view_r)
        painter.setPen(QPen(color, 2))
        painter.drawLine(center.x() - 8, center.y(), center.x() + 8, center.y())
        painter.drawLine(center.x(), center.y() - 8, center.x(), center.y() + 8)

    def _piece_view_radius(self, piece: dict[str, int]) -> int:
        radius = self._effective_radius(piece)
        a = self.mapFromScene(QPointF(piece["x"], piece["y"]))
        b = self.mapFromScene(QPointF(piece["x"] + radius, piece["y"]))
        return max(MIN_RADIUS, int(round((QPointF(b) - QPointF(a)).manhattanLength())))

    def _hit_piece(self, scene_pos: QPointF) -> int | None:
        hit = None
        best = 10**9
        for index, piece in enumerate(self._pieces):
            if not self._key_is_visible(str(piece.get("kind") or "")):
                continue
            dx = scene_pos.x() - piece["x"]
            dy = scene_pos.y() - piece["y"]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= self._effective_radius(piece) + 4 and dist < best:
                best = dist
                hit = index
        return hit

    def _add_piece(self, scene_pos: QPointF) -> None:
        kind = self._active_key
        radius = self._piece_radius.get(kind, DEFAULT_RADIUS)
        piece = {
            "x": int(round(scene_pos.x())),
            "y": int(round(scene_pos.y())),
            "r": int(radius),
            "kind": kind,
            "group": self._piece_group if kind == "tsum" else 0,
        }
        self._clamp_piece(piece)
        self._pieces.append(piece)
        self._selected_piece = len(self._pieces) - 1
        self._clear_chain_trace()
        self.piecesChanged.emit()
        self._update_guide()
        self.viewport().update()

    def _clamp_piece(self, piece: dict[str, int]) -> None:
        if self._pixmap_item is None:
            return
        bounds = self._game_rect() if is_piece_key(self._active_key) else None
        if bounds is None:
            if self._pixmap_item is None:
                return
            bounds = self._pixmap_item.boundingRect()
        radius = max(MIN_RADIUS, int(piece["r"]))
        piece["r"] = min(radius, int(min(bounds.width(), bounds.height()) / 2))
        piece["x"] = int(min(max(piece["x"], bounds.left()), bounds.right() - 1))
        piece["y"] = int(min(max(piece["y"], bounds.top()), bounds.bottom() - 1))

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
        if is_piece_key(self._active_key) and self._mode != "move-piece":
            step = 2 if event.angleDelta().y() > 0 else -2
            hover_hit = self._hit_piece(self._hover_pos) if self._hover_pos is not None else None
            if hover_hit is not None:
                piece = self._pieces[hover_hit]
                piece["r"] = max(MIN_RADIUS, piece["r"] + step)
                self._clamp_piece(piece)
                self._piece_radius[piece["kind"]] = piece["r"]
                self._selected_piece = hover_hit
                self.piecesChanged.emit()
            else:
                kind = self._active_key
                self._piece_radius[kind] = max(MIN_RADIUS, self._piece_radius.get(kind, DEFAULT_RADIUS) + step)
            self.viewport().update()
            event.accept()
            return
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
        self._should_fit = False
        self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._pixmap_item is None:
            return
        self.setFocus()
        if event.button() == Qt.MouseButton.RightButton and is_piece_key(self._active_key):
            scene_pos = self._clamp_point(self.mapToScene(self._viewport_pos(event)))
            hit = self._hit_piece(scene_pos)
            if hit is not None:
                self._remove_piece_at(hit)
                event.accept()
                return
        if event.button() in (Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self._mode = "pan"
            self._pan_pos = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if is_scene_key(self._active_key):
            event.accept()
            return

        view_pos = self._viewport_pos(event)
        scene_pos = self._clamp_point(self.mapToScene(view_pos))
        if is_piece_key(self._active_key) and event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_piece(scene_pos)
            if hit is not None:
                self._mode = "move-piece"
                self._selected_piece = hit
                self._origin = scene_pos
                piece = self._pieces[hit]
                self._orig_rect = QRectF(piece["x"], piece["y"], piece["r"], piece["r"])
                self._clear_chain_trace()
                self.viewport().setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                game = self._game_rect()
                if game is not None and not game.contains(scene_pos):
                    event.accept()
                    return
                self._add_piece(scene_pos)
                self._mode = "move-piece"
                self._origin = scene_pos
                piece = self._pieces[self._selected_piece or 0]
                self._orig_rect = QRectF(piece["x"], piece["y"], piece["r"], piece["r"])
            self._update_guide()
            self.viewport().update()
            event.accept()
            return
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
        if is_piece_key(self._active_key) and self._mode not in {"move-piece", "pan"}:
            self._hover_pos = scene_pos
            self.viewport().update()
        if self._mode == "move-piece" and self._selected_piece is not None:
            delta = scene_pos - self._origin
            if abs(delta.x()) < 0.5 and abs(delta.y()) < 0.5:
                event.accept()
                return
            piece = self._pieces[self._selected_piece]
            piece["x"] = int(round(self._orig_rect.x() + delta.x()))
            piece["y"] = int(round(self._orig_rect.y() + delta.y()))
            self._clamp_piece(piece)
            self.viewport().update()
            self.piecesChanged.emit()
            event.accept()
            return
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
        if self._mode == "move-piece" and event.button() == Qt.MouseButton.LeftButton:
            self._mode = None
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.piecesChanged.emit()
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

    def leaveEvent(self, event) -> None:
        self._hover_pos = None
        self.viewport().update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        mods = event.modifiers()
        if is_piece_key(self._active_key):
            key = event.key()
            if key in (Qt.Key.Key_Backspace, Qt.Key.Key_X) and self.remove_selected_piece():
                event.accept()
                return
            if (
                key == Qt.Key.Key_Z
                and not (mods & Qt.KeyboardModifier.ControlModifier)
                and self.undo_last_piece()
            ):
                event.accept()
                return
            if self._active_key == "tsum" and Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
                self.set_piece_group(key - Qt.Key.Key_1 + 1)
                event.accept()
                return
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
