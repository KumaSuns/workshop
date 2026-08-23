from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.scene_labels import OTHER_KEY, SceneLabels


class KindPickDialog(QDialog):
    def __init__(self, labels: SceneLabels, current: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("種類を直す")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("この画像の種類"))
        self.combo = QComboBox()
        self.combo.addItem(labels.name_of(OTHER_KEY), OTHER_KEY)
        for key, name in labels.kinds():
            self.combo.addItem(name, key)
        index = self.combo.findData(current)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        layout.addWidget(self.combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_kind(self) -> str:
        return str(self.combo.currentData() or OTHER_KEY)


class SceneTrainImagesWindow(QMainWindow):
    def __init__(self, host: QMainWindow) -> None:
        super().__init__(host)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("学習画像を見る")
        self.resize(1100, 720)
        self.setMinimumSize(720, 480)
        self._host = host
        self._full_pixmap: QPixmap | None = None
        self._build_ui()
        self.reload()

    def _labels(self) -> SceneLabels:
        return getattr(self._host, "scene_labels")

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        top = QFrame()
        top.setObjectName("panel")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel("学習画像を見る")
        title.setObjectName("title")
        hint = QLabel("種類を選ぶと、学習に使っている画像が出ます。違う種類なら直して、使わないなら外します。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        top_layout.addWidget(title)
        top_layout.addWidget(hint)
        layout.addWidget(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.addWidget(QLabel("種類"))
        self.kind_list = QListWidget()
        self.kind_list.currentItemChanged.connect(self._on_kind_changed)
        left_layout.addWidget(self.kind_list, 1)
        split.addWidget(left)

        mid = QFrame()
        mid.setObjectName("panel")
        mid_layout = QVBoxLayout(mid)
        mid_layout.setContentsMargins(12, 12, 12, 12)
        self.file_title = QLabel("画像")
        mid_layout.addWidget(self.file_title)
        self.file_list = QListWidget()
        self.file_list.currentItemChanged.connect(self._on_file_changed)
        mid_layout.addWidget(self.file_list, 1)
        split.addWidget(mid)

        right = QFrame()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        self.preview_title = QLabel("プレビュー")
        right_layout.addWidget(self.preview_title)
        self.preview = QLabel("種類を選ぶと、画像が出ます")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(280, 240)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.preview, 1)
        btn_row = QHBoxLayout()
        self.rekind_btn = QPushButton("種類を直す")
        self.remove_btn = QPushButton("学習から外す")
        btn_row.addWidget(self.rekind_btn)
        btn_row.addWidget(self.remove_btn)
        right_layout.addLayout(btn_row)
        split.addWidget(right)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 2)
        split.setSizes([220, 280, 560])
        layout.addWidget(split, 1)
        self.setCentralWidget(root)

        self.rekind_btn.clicked.connect(self.rekind_current)
        self.remove_btn.clicked.connect(self.remove_current)

    def reload(self, select_kind: str | None = None) -> None:
        labels = self._labels()
        current = select_kind or self._current_kind()
        picker = getattr(self._host, "_selected_kind", None)
        if current is None and callable(picker):
            current = picker()
        counts = labels.counts()
        keep_path = None
        current_file = self.file_list.currentItem()
        if current_file is not None:
            keep_path = current_file.data(Qt.ItemDataRole.UserRole)
        self.kind_list.blockSignals(True)
        self.kind_list.clear()
        for key in labels.classes():
            item = QListWidgetItem(f"{labels.name_of(key)}  {counts.get(key, 0)}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.kind_list.addItem(item)
        self.kind_list.blockSignals(False)
        row = 0
        if current:
            found = self._kind_row(current)
            if found >= 0:
                row = found
        if self.kind_list.count():
            self.kind_list.setCurrentRow(row)
        self._fill_files(keep_path=str(keep_path) if keep_path else None)
        self._update_buttons()

    def _kind_row(self, key: str) -> int:
        for row in range(self.kind_list.count()):
            item = self.kind_list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
                return row
        return -1

    def _current_kind(self) -> str | None:
        item = self.kind_list.currentItem()
        if item is None:
            return None
        key = item.data(Qt.ItemDataRole.UserRole)
        return str(key) if key else None

    def _current_path(self) -> Path | None:
        item = self.file_list.currentItem()
        if item is None:
            return None
        raw = item.data(Qt.ItemDataRole.UserRole)
        if not raw:
            return None
        path = Path(str(raw))
        return path if path.is_file() else None

    def _on_kind_changed(self, *_args) -> None:
        self._fill_files()

    def _fill_files(self, keep_path: str | None = None) -> None:
        kind = self._current_kind()
        labels = self._labels()
        self.file_list.blockSignals(True)
        self.file_list.clear()
        items = labels.items_of(kind) if kind else []
        self.file_title.setText(f"画像  {len(items)} 枚")
        select = 0
        for index, sample in enumerate(items):
            path = Path(sample["path"])
            row = QListWidgetItem(path.name)
            row.setData(Qt.ItemDataRole.UserRole, str(path))
            self.file_list.addItem(row)
            if keep_path and str(path) == keep_path:
                select = index
        self.file_list.blockSignals(False)
        if self.file_list.count():
            self.file_list.setCurrentRow(select)
        else:
            self._full_pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("この種類の画像はまだありません")
            self.preview_title.setText("プレビュー")
        self._update_buttons()

    def _on_file_changed(self, *_args) -> None:
        path = self._current_path()
        if path is None:
            self._full_pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("画像を開けませんでした")
            self.preview_title.setText("プレビュー")
            self._update_buttons()
            return
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._full_pixmap = None
            self.preview.setPixmap(QPixmap())
            self.preview.setText("画像を開けませんでした")
            self.preview_title.setText(path.name)
            self._update_buttons()
            return
        self._full_pixmap = pixmap
        self.preview_title.setText(path.name)
        self._fit_preview()
        self._update_buttons()

    def _fit_preview(self) -> None:
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return
        self.preview.setPixmap(
            self._full_pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_preview()

    def _update_buttons(self) -> None:
        has_file = self._current_path() is not None
        self.rekind_btn.setEnabled(has_file)
        self.remove_btn.setEnabled(has_file)

    def rekind_current(self) -> None:
        path = self._current_path()
        kind = self._current_kind()
        if path is None or kind is None:
            return
        labels = self._labels()
        dialog = KindPickDialog(labels, kind, self)
        dialog.setStyleSheet(self.styleSheet())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_kind = dialog.selected_kind()
        if new_kind == kind:
            return
        try:
            if not labels.set_kind(path, new_kind):
                QMessageBox.warning(self, "直せませんでした", "この画像は学習データにありません。")
                return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "直せませんでした", str(exc))
            return
        self._notify_host()
        self.reload(select_kind=kind)

    def remove_current(self) -> None:
        path = self._current_path()
        if path is None:
            return
        answer = QMessageBox.question(
            self,
            "学習から外す",
            f"「{path.name}」を学習から外しますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        kind = self._current_kind()
        try:
            if not self._labels().remove(path):
                QMessageBox.warning(self, "外せませんでした", "この画像は学習データにありません。")
                return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "外せませんでした", str(exc))
            return
        self._notify_host()
        self.reload(select_kind=kind)

    def _notify_host(self) -> None:
        refresh = getattr(self._host, "_refresh_teach_label", None)
        if callable(refresh):
            refresh()
        update = getattr(self._host, "_update_buttons", None)
        if callable(update):
            update()
