from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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

from app.coin_teach import (
    COIN_KIND_LABELS,
    MIN_DIGIT_SAMPLES,
    coin_teaching_counts,
    list_coin_teaching,
    remove_coin_teaching,
    update_coin_teaching,
)
from app.preview_label import ImagePreview

SAVED_COIN_COLOR = "#ff9f43"


class CoinTrainImagesWindow(QMainWindow):
    def __init__(self, host: QMainWindow) -> None:
        super().__init__(host)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("コイン学習画像を見る")
        self.resize(1100, 720)
        self.setMinimumSize(720, 480)
        self._host = host
        self._full_pixmap: QPixmap | None = None
        self._build_ui()
        self.reload()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        top = QFrame()
        top.setObjectName("panel")
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel("コイン学習画像を見る")
        title.setObjectName("title")
        hint = QLabel(
            "coin と result の、枠や数字を保存した画像です。"
            "枠はドラッグして囲み直せます。数字も直して、合っているものだけ保存します。"
            "使わないものは外します。"
        )
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
        self.kind_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        self.file_list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.file_list.currentItemChanged.connect(self._on_file_changed)
        mid_layout.addWidget(self.file_list, 1)
        split.addWidget(mid)

        right = QFrame()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 12, 12, 12)
        self.preview_title = QLabel("プレビュー")
        right_layout.addWidget(self.preview_title)
        self.preview = ImagePreview("種類を選ぶと、画像が出ます")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(280, 240)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.preview, 1)
        self.coin_edit = QLineEdit()
        self.coin_edit.setPlaceholderText("この枠の数字")
        right_layout.addWidget(self.coin_edit)
        save_row = QHBoxLayout()
        save_row.setSpacing(6)
        self.box_save_btn = QPushButton("枠を保存")
        self.number_save_btn = QPushButton("数字を保存")
        self.save_btn = QPushButton("枠と数字を保存")
        save_row.addWidget(self.box_save_btn, 1)
        save_row.addWidget(self.number_save_btn, 1)
        save_row.addWidget(self.save_btn, 1)
        right_layout.addLayout(save_row)
        self.remove_btn = QPushButton("学習から外す")
        right_layout.addWidget(self.remove_btn)
        split.addWidget(right)

        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 2)
        split.setSizes([220, 280, 560])
        layout.addWidget(split, 1)
        self.setCentralWidget(root)

        self.preview.box_changed.connect(self._on_box_changed)
        self.box_save_btn.clicked.connect(self.save_box)
        self.number_save_btn.clicked.connect(self.save_number)
        self.save_btn.clicked.connect(self.save_both)
        self.coin_edit.returnPressed.connect(self.save_number)
        self.coin_edit.textEdited.connect(lambda *_args: self._set_saved_color(False))
        self.remove_btn.clicked.connect(self.remove_current)
        for button in (self.box_save_btn, self.number_save_btn, self.save_btn, self.remove_btn):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def reload(self, select_kind: str | None = None) -> None:
        current = select_kind or self._current_kind() or "coin"
        keep_id = None
        current_file = self.file_list.currentItem()
        if current_file is not None:
            keep_id = current_file.data(Qt.ItemDataRole.UserRole)
            if isinstance(keep_id, dict):
                keep_id = keep_id.get("id")
        counts = coin_teaching_counts()
        self.kind_list.blockSignals(True)
        self.kind_list.clear()
        for key, name in COIN_KIND_LABELS.items():
            item = QListWidgetItem(f"{name}  {counts.get(key, 0)}")
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.kind_list.addItem(item)
        row = 0
        found = self._kind_row(current)
        if found >= 0:
            row = found
        if self.kind_list.count():
            self.kind_list.setCurrentRow(row)
        self.kind_list.blockSignals(False)
        self._fill_files(keep_id=str(keep_id) if keep_id else None)
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

    def _current_item(self) -> dict | None:
        item = self.file_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _on_kind_changed(self, *_args) -> None:
        self._fill_files()
        self.kind_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _fill_files(self, keep_id: str | None = None) -> None:
        kind = self._current_kind()
        focus = self.focusWidget()
        self.file_list.blockSignals(True)
        self.file_list.clear()
        items = list_coin_teaching(kind) if kind else []
        self.file_title.setText(f"画像  {len(items)} 枚")
        select = 0
        for index, sample in enumerate(items):
            digits = sample.get("digits") or ""
            extra = f"  {digits}" if digits else "  枠のみ"
            row = QListWidgetItem(f"{sample['name']}{extra}")
            row.setData(Qt.ItemDataRole.UserRole, sample)
            self.file_list.addItem(row)
            if keep_id and sample.get("id") == keep_id:
                select = index
        self.file_list.blockSignals(False)
        if self.file_list.count():
            self.file_list.setCurrentRow(select)
            item = self.file_list.item(select)
            if item is not None:
                self.file_list.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)
            self._on_file_changed()
        else:
            self._show_empty_preview("この種類の画像はまだありません")
        if focus is self.kind_list:
            self.kind_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_file_changed(self, *_args) -> None:
        sample = self._current_item()
        if sample is None:
            self._show_empty_preview("画像を開けませんでした")
            return
        path = Path(sample["path"])
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            self._show_empty_preview("画像を開けませんでした", title=path.name)
            return
        self._full_pixmap = pixmap
        self.preview.editable = True
        self.preview.set_image(pixmap, sample.get("box"))
        self.preview_title.setText(path.name)
        digits = sample.get("digits") or ""
        self.coin_edit.setEnabled(True)
        self.coin_edit.setText(self._format_number(digits))
        self._set_saved_color(bool(digits))
        self._update_buttons()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)

    def _update_buttons(self) -> None:
        has = self.file_list.currentRow() >= 0
        self.coin_edit.setEnabled(has)
        self.box_save_btn.setEnabled(has)
        self.number_save_btn.setEnabled(has)
        self.save_btn.setEnabled(has)
        self.remove_btn.setEnabled(has)

    def _format_number(self, number: str) -> str:
        digits = "".join(char for char in (number or "") if char.isdigit())
        if not digits:
            return ""
        return f"{int(digits):,}"

    def _set_saved_color(self, saved: bool) -> None:
        self.coin_edit.setStyleSheet(f"color: {SAVED_COIN_COLOR};" if saved else "")

    def _current_box(self) -> dict | None:
        return self.preview.box() or (self._current_item() or {}).get("box")

    def _on_box_changed(self, box: dict) -> None:
        sample = self._current_item()
        if sample is None:
            return
        number = ""
        getter = getattr(self._host, "_coin_reader_instance", None)
        if callable(getter):
            try:
                number = getter().read_box(Path(sample["path"]), box)
            except Exception:
                number = ""
        self.coin_edit.setText(self._format_number(number))
        self._set_saved_color(False)

    def save_box(self) -> None:
        self._save_parts(persist_box=True, save_number=False)

    def save_number(self) -> None:
        self._save_parts(persist_box=False, save_number=True)

    def save_both(self) -> None:
        self._save_parts(persist_box=True, save_number=True)

    def _save_parts(self, persist_box: bool, save_number: bool) -> None:
        sample = self._current_item()
        kind = self._current_kind()
        if sample is None or kind is None:
            return
        box = self._current_box()
        if persist_box or save_number:
            if box is None:
                QMessageBox.information(self, "枠がありません", "プレビューをドラッグして、コインの数字を囲んでください。")
                return
        try:
            count = update_coin_teaching(
                str(sample["id"]),
                kind,
                box=box if (persist_box or save_number) else None,
                number=self.coin_edit.text() if save_number else None,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存できませんでした", str(exc))
            return
        if box is not None:
            sample["box"] = dict(box)
            if persist_box:
                self._persist_host_box(kind, box)
        if save_number:
            digits = "".join(char for char in self.coin_edit.text() if char.isdigit())
            sample["digits"] = digits
            self.coin_edit.setText(self._format_number(digits))
            self._set_saved_color(True)
        else:
            saved = "".join(char for char in str(sample.get("digits") or "") if char.isdigit())
            current = "".join(char for char in self.coin_edit.text() if char.isdigit())
            self._set_saved_color(bool(saved) and saved == current)
        item = self.file_list.currentItem()
        if item is not None:
            extra = f"  {sample.get('digits')}" if sample.get("digits") else "  枠のみ"
            item.setText(f"{sample['name']}{extra}")
            item.setData(Qt.ItemDataRole.UserRole, sample)
        self._notify_host()
        extra = "「コイン数字を学習する」が使えます。" if count >= MIN_DIGIT_SAMPLES else f"学習にはあと {MIN_DIGIT_SAMPLES - count} 枚です。"
        if save_number and persist_box:
            message = f"枠と数字 {self.coin_edit.text()} を保存しました。いま {count} 枚。{extra}"
        elif save_number:
            message = f"数字 {self.coin_edit.text()} を保存しました。いま {count} 枚。{extra}"
        else:
            message = "枠の位置を保存しました。次の解析から使います。"
        self.statusBar().showMessage(message, 6000)

    def _persist_host_box(self, key: str, box: dict) -> None:
        remember = getattr(self._host, "_remember_session_box", None)
        if not callable(remember) or self._full_pixmap is None or self._full_pixmap.isNull():
            return
        try:
            remember(key, box, self._full_pixmap.width(), self._full_pixmap.height(), persist=True)
        except Exception:
            pass

    def remove_current(self) -> None:
        sample = self._current_item()
        kind = self._current_kind()
        if sample is None or kind is None:
            QMessageBox.information(self, "画像がありません", "外す画像を一覧から選んでください。")
            return
        try:
            ok = remove_coin_teaching(str(sample["id"]), kind)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "外せませんでした", str(exc))
            return
        if not ok:
            QMessageBox.warning(self, "外せませんでした", "この画像は学習データにありません。")
            return
        row = self.file_list.currentRow()
        self.file_list.blockSignals(True)
        taken = self.file_list.takeItem(row)
        del taken
        self.file_list.blockSignals(False)
        self._refresh_kind_counts()
        if self.file_list.count():
            next_row = min(row, self.file_list.count() - 1)
            self.file_list.setCurrentRow(next_row)
            self._on_file_changed()
        else:
            self._show_empty_preview("この種類の画像はもうありません")
        self._notify_host()
        self.statusBar().showMessage(
            f"「{sample.get('name') or '画像'}」を学習から外しました。残り {self.file_list.count()} 枚",
            4000,
        )
        self.file_list.setFocus(Qt.FocusReason.OtherFocusReason)

    def _refresh_kind_counts(self) -> None:
        counts = coin_teaching_counts()
        for row in range(self.kind_list.count()):
            item = self.kind_list.item(row)
            if item is None:
                continue
            key = str(item.data(Qt.ItemDataRole.UserRole) or "")
            item.setText(f"{COIN_KIND_LABELS.get(key, key)}  {counts.get(key, 0)}")
        self.file_title.setText(f"画像  {self.file_list.count()} 枚")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.focusWidget() is self.coin_edit:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            self.remove_current()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_empty_preview(self, message: str, title: str = "プレビュー") -> None:
        self._full_pixmap = None
        self.preview.editable = False
        self.preview.set_image(None)
        self.preview.setText(message)
        self.preview_title.setText(title)
        self.coin_edit.setText("")
        self.coin_edit.setEnabled(False)
        self._set_saved_color(False)
        self._update_buttons()

    def _notify_host(self) -> None:
        setattr(self._host, "_skip_coin_train_images_reload", True)
        try:
            refresh = getattr(self._host, "_refresh_teach_label", None)
            if callable(refresh):
                refresh()
            update = getattr(self._host, "_update_buttons", None)
            if callable(update):
                update()
            reader = getattr(self._host, "_coin_reader", None)
            if reader is not None:
                try:
                    reader.reload()
                except Exception:
                    pass
        finally:
            setattr(self._host, "_skip_coin_train_images_reload", False)
