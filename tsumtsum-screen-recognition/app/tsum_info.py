from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.paths import USE_TSUM_META, USE_TSUM_REGISTRY, USE_TSUMS_IMAGES

KIND_LABELS = (
    ("normal", "通常"),
    ("set", "セットツム"),
    ("pair", "ペアツム"),
    ("transform", "変身ツム"),
)
KIND_IDS = {key for key, _label in KIND_LABELS}
_BAD_DIR = re.compile(r'[<>:"/\\|?*]+')


def _name_only(text: str) -> str:
    return " ".join((text or "").split())


def _dir_name(name: str) -> str:
    cleaned = _BAD_DIR.sub("", _name_only(name)).strip(" .")
    return cleaned or "tsum"


def load_registry() -> dict[str, str]:
    if not USE_TSUM_REGISTRY.is_file():
        return {}
    try:
        payload = json.loads(USE_TSUM_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in payload.items()
        if str(key).strip() and str(value).strip()
    }


def save_registry(registry: dict[str, str]) -> None:
    USE_TSUM_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    USE_TSUM_REGISTRY.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_meta() -> dict[str, dict[str, object]]:
    if not USE_TSUM_META.is_file():
        return {}
    try:
        payload = json.loads(USE_TSUM_META.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    meta: dict[str, dict[str, object]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            meta[str(key)] = value
    return meta


def save_meta(meta: dict[str, dict[str, object]]) -> None:
    USE_TSUM_META.parent.mkdir(parents=True, exist_ok=True)
    USE_TSUM_META.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def kind_label(kind: str) -> str:
    for key, label in KIND_LABELS:
        if key == kind:
            return label
    return "通常"


def charm_label(charm: bool | None) -> str:
    if charm is True:
        return "チャームツム"
    if charm is False:
        return "チャームツムではない"
    return "－"


def listed_tsums() -> list[dict[str, object]]:
    registry = load_registry()
    meta = load_meta()
    rows: list[dict[str, object]] = []
    for en_name, ja_name in sorted(registry.items(), key=lambda item: str(item[1]).casefold()):
        info = meta.get(en_name) or {}
        kind = str(info.get("kind") or "normal")
        if kind not in KIND_IDS:
            kind = "normal"
        charm_raw = info.get("charm")
        charm = charm_raw if isinstance(charm_raw, bool) else None
        rows.append(
            {
                "ja": ja_name,
                "en": en_name,
                "kind": kind,
                "charm": charm,
            }
        )
    return rows


def upsert_tsum(ja: str, en: str, kind: str, charm: bool, old_en: str = "") -> str:
    ja_name = _name_only(ja)
    en_name = _dir_name(en)
    if not ja_name:
        raise ValueError("名前を入力してください。")
    if not en_name:
        raise ValueError("英語名を入力してください。")
    if kind not in KIND_IDS:
        raise ValueError("タイプを選んでください。")
    registry = load_registry()
    meta = load_meta()
    if old_en and old_en != en_name and old_en in registry:
        del registry[old_en]
        meta.pop(old_en, None)
    registry[en_name] = ja_name
    meta[en_name] = {"kind": kind, "charm": bool(charm)}
    folder = USE_TSUMS_IMAGES / en_name
    folder.mkdir(parents=True, exist_ok=True)
    keep = folder / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    save_registry(registry)
    save_meta(meta)
    return en_name


def delete_tsum(en: str) -> None:
    en_name = _dir_name(en)
    if not en_name:
        return
    registry = load_registry()
    meta = load_meta()
    registry.pop(en_name, None)
    meta.pop(en_name, None)
    save_registry(registry)
    save_meta(meta)


class TsumInfoWindow(QDialog):
    def __init__(self, parent: QWidget | None = None, stylesheet: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("ツム情報登録")
        self.setModal(False)
        if stylesheet:
            self.setStyleSheet(stylesheet)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setMinimumSize(720, 520)
        self._selected_en = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["名前", "英語名", "タイプ", "チャーム"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_select)
        layout.addWidget(self.table, 1)

        form = QVBoxLayout()
        form.setSpacing(6)
        form.addWidget(QLabel("名前"))
        self.ja_edit = QLineEdit()
        self.ja_edit.setPlaceholderText("ガジェット")
        form.addWidget(self.ja_edit)
        form.addWidget(QLabel("英語名"))
        self.en_edit = QLineEdit()
        self.en_edit.setPlaceholderText("Gadget")
        form.addWidget(self.en_edit)

        form.addWidget(QLabel("タイプ"))
        self.kind_group = QButtonGroup(self)
        kind_row = QHBoxLayout()
        for kind_id, label in KIND_LABELS:
            button = QRadioButton(label)
            button.setProperty("kind_id", kind_id)
            self.kind_group.addButton(button)
            kind_row.addWidget(button)
        kind_row.addStretch(1)
        form.addLayout(kind_row)

        form.addWidget(QLabel("チャーム"))
        self.charm_group = QButtonGroup(self)
        charm_row = QHBoxLayout()
        self.charm_yes = QRadioButton("チャームツム")
        self.charm_no = QRadioButton("チャームツムではない")
        self.charm_group.addButton(self.charm_yes)
        self.charm_group.addButton(self.charm_no)
        charm_row.addWidget(self.charm_yes)
        charm_row.addWidget(self.charm_no)
        charm_row.addStretch(1)
        form.addLayout(charm_row)
        layout.addLayout(form)

        bar = QHBoxLayout()
        self.new_btn = QPushButton("新規")
        self.save_btn = QPushButton("登録する")
        self.save_btn.setObjectName("accent")
        self.delete_btn = QPushButton("削除")
        self.close_btn = QPushButton("閉じる")
        bar.addWidget(self.new_btn)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.delete_btn)
        bar.addStretch(1)
        bar.addWidget(self.close_btn)
        layout.addLayout(bar)

        self.new_btn.clicked.connect(self._clear_form)
        self.save_btn.clicked.connect(self._save)
        self.delete_btn.clicked.connect(self._delete)
        self.close_btn.clicked.connect(self.close)

        self.reload()
        self._clear_form()

    def reload(self) -> None:
        rows = listed_tsums()
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for row in rows:
            index = self.table.rowCount()
            self.table.insertRow(index)
            values = (
                str(row["ja"]),
                str(row["en"]),
                kind_label(str(row["kind"])),
                charm_label(row["charm"] if isinstance(row["charm"], bool) else None),
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setData(Qt.ItemDataRole.UserRole, str(row["en"]))
                self.table.setItem(index, col, item)
        self.table.blockSignals(False)

    def _clear_form(self) -> None:
        self._selected_en = ""
        self.ja_edit.clear()
        self.en_edit.clear()
        self.kind_group.setExclusive(False)
        for button in self.kind_group.buttons():
            button.setChecked(False)
        self.kind_group.setExclusive(True)
        self.charm_group.setExclusive(False)
        self.charm_yes.setChecked(False)
        self.charm_no.setChecked(False)
        self.charm_group.setExclusive(True)
        self.table.clearSelection()
        self.ja_edit.setFocus()

    def _on_select(self) -> None:
        items = self.table.selectedItems()
        if not items:
            return
        row = items[0].row()
        ja_item = self.table.item(row, 0)
        en_item = self.table.item(row, 1)
        if ja_item is None or en_item is None:
            return
        en = str(en_item.data(Qt.ItemDataRole.UserRole) or en_item.text())
        self._selected_en = en
        self.ja_edit.setText(ja_item.text())
        self.en_edit.setText(en)
        meta = load_meta().get(en) or {}
        kind = str(meta.get("kind") or "normal")
        if kind not in KIND_IDS:
            kind = "normal"
        for button in self.kind_group.buttons():
            button.setChecked(str(button.property("kind_id") or "") == kind)
        charm = meta.get("charm")
        if charm is True:
            self.charm_yes.setChecked(True)
        elif charm is False:
            self.charm_no.setChecked(True)
        else:
            self.charm_group.setExclusive(False)
            self.charm_yes.setChecked(False)
            self.charm_no.setChecked(False)
            self.charm_group.setExclusive(True)

    def _save(self) -> None:
        kind_button = self.kind_group.checkedButton()
        if kind_button is None:
            QMessageBox.information(self, "ツム情報登録", "タイプを選んでください。")
            return
        if self.charm_group.checkedButton() is None:
            QMessageBox.information(
                self, "ツム情報登録", "チャームツムかどうかを選んでください。"
            )
            return
        kind = str(kind_button.property("kind_id") or "")
        try:
            saved_en = upsert_tsum(
                self.ja_edit.text(),
                self.en_edit.text(),
                kind,
                self.charm_group.checkedButton() is self.charm_yes,
                old_en=self._selected_en,
            )
        except ValueError as exc:
            QMessageBox.information(self, "ツム情報登録", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存できませんでした", str(exc))
            return
        self.reload()
        self._select_en(saved_en)

    def _delete(self) -> None:
        en = self._selected_en or _dir_name(self.en_edit.text())
        if not en:
            QMessageBox.information(self, "ツム情報登録", "削除するツムを選んでください。")
            return
        ja = _name_only(self.ja_edit.text()) or en
        answer = QMessageBox.question(
            self,
            "削除",
            f"{ja} を一覧から削除しますか？\n画像フォルダは残します。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            delete_tsum(en)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "削除できませんでした", str(exc))
            return
        self.reload()
        self._clear_form()

    def _select_en(self, en: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item is None:
                continue
            key = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
            if key == en:
                self.table.selectRow(row)
                self.table.scrollToItem(item)
                return
