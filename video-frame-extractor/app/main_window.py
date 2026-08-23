from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QImage, QPixmap, QShortcut, QKeySequence, QDragEnterEvent, QDropEvent
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.extractor import (
    RANGE_END,
    RANGE_START,
    VIDEO_EXTENSIONS,
    VideoInfo,
    format_timecode,
    grab_frame,
    read_video_info,
    sample_points,
    extracted_file_for,
    write_image,
)
from app.worker import ExtractWorker, SceneExtractWorker
from app.scene_scan import REJECT_HASH_LIMIT, hashes_too_close, scene_ahash_path
from app.handoff import send_images_to_tsumtsum
from app.data_sync import (
    copy_data_folder,
    ensure_scene_packed,
    import_data_folder,
    is_same_or_inside,
    resolve_data_dir,
    resolved,
    trainer_data_dir,
)
from app.paths import IMAGE_EXTENSIONS, IPC_NAME, TRAINER_IPC_NAME
from app.scene_labels import MIN_SCENE_SAMPLES, OTHER_KEY, SceneLabels, scene_model_ready
from app.scene_train import SceneTrainWorker
from app.train_overlay import TrainOverlay
from app.coin_read import CoinReader
from app.coin_teach import (
    MIN_DIGIT_SAMPLES,
    DigitTrainWorker,
    digit_teaching_count,
    save_coin_teaching,
)
from app.preview_label import ImagePreview
from app.scene_still_window import SceneStillWindow
from app.scene_train_images_window import SceneTrainImagesWindow

STYLESHEET = """
QMainWindow, QWidget {
    background: #16181d;
    color: #e8eaed;
    font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLabel#title { font-size: 18px; font-weight: 700; }
QLabel#hint { color: #9aa3b2; }
QPushButton {
    background: #2a303b;
    color: #e8eaed;
    border: none;
    padding: 4px 8px;
    border-radius: 6px;
    min-height: 0px;
}
QPushButton:hover { background: #3a4250; }
QPushButton:disabled { color: #6b7380; background: #22262e; }
QPushButton#primary { background: #5b6cff; font-weight: 600; }
QPushButton#primary:hover { background: #6e7dff; }
QListWidget {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
    padding: 6px;
    outline: none;
}
QListWidget::item { padding: 4px; border-radius: 8px; }
QListWidget::item:selected { background: #2c3344; }
QFrame#panel {
    background: #1c2028;
    border: 1px solid #2a303b;
    border-radius: 12px;
}
QSpinBox, QComboBox, QLineEdit {
    background: #101216;
    color: #e8eaed;
    border: 1px solid #2a303b;
    border-radius: 6px;
    padding: 6px 10px;
    min-width: 80px;
}
QProgressBar {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 6px;
    text-align: center;
    color: #e8eaed;
}
QProgressBar::chunk { background: #5b6cff; border-radius: 6px; }
QLabel#preview, QFrame#infoPane {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 10px;
}
QLabel#infoCaption { color: #9aa3b2; font-size: 12px; }
QLabel#infoValue { color: #f2f5f8; font-size: 16px; font-weight: 700; }
QFrame#kindsPane {
    background: #101216;
    border: 1px solid #2a303b;
    border-radius: 12px;
}
QLabel#kindsCaption { color: #9aa3b2; font-size: 12px; }
QLabel#kindsValue { color: #f2f5f8; font-size: 16px; font-weight: 600; }
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("動画フレーム抜き出し")
        self.resize(1480, 900)
        self.setMinimumSize(1280, 800)
        self.setAcceptDrops(True)
        self.setStyleSheet(STYLESHEET)

        self.info: VideoInfo | None = None
        self.worker: ExtractWorker | SceneExtractWorker | SceneTrainWorker | DigitTrainWorker | None = None
        self.scene_labels = SceneLabels()
        self._settings = QSettings("workshop", "VideoFrameExtractor")
        self.output_dir = Path(__file__).resolve().parent.parent / "output"
        saved_out = str(self._settings.value("last_output_dir", "") or "")
        if saved_out and Path(saved_out).is_dir():
            self.output_dir = Path(saved_out)
        self._cap = None
        self._full_pixmap: QPixmap | None = None
        self._saved_by_index: dict[int, Path] = {}
        self._preview_point = None
        self._ipc_buffers: dict[int, bytes] = {}
        self._coin_reader: CoinReader | None = None
        self._coin_cache: dict[tuple[str, int, str], str] = {}
        self._coin_box_cache: dict[tuple[str, int, str], dict[str, int]] = {}
        self._preview_coin_box: dict[str, int] | None = None
        self._scene_still: SceneStillWindow | None = None
        self._train_images: SceneTrainImagesWindow | None = None

        self._start_ipc()
        self._build_ui()
        QShortcut(QKeySequence.StandardKey.Open, self, self.open_video)

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        top = QFrame()
        top.setObjectName("panel")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(16, 12, 16, 12)
        title_box = QVBoxLayout()
        title = QLabel("動画フレーム抜き出し")
        title.setObjectName("title")
        self.hint_label = QLabel(
            f"動画をドロップまたは「動画を開く」。開いただけでは抜き出しません。"
            f"再生時間の {int(RANGE_START*100)}%〜{int(RANGE_END*100)}% から、枚数を指定して「指定枚数を出す」を押します。"
            "1枚のときは再生時間の中心（50%）です。"
            "探したい画面は種類を追加し、用意した画像を取り込んで学習します。"
            "間違った画面は「これは違う」で、正しい種類か「どちらでもない」を選びます。"
        )
        self.hint_label.setObjectName("hint")
        self.hint_label.setWordWrap(True)
        title_box.addWidget(title)
        title_box.addWidget(self.hint_label)
        top_layout.addLayout(title_box, 1)
        self.open_btn = QPushButton("動画を開く")
        self.folder_btn = QPushButton("保存先")
        top_layout.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignTop)
        top_layout.addWidget(self.folder_btn, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(top)

        kinds_pane = QFrame()
        kinds_pane.setObjectName("kindsPane")
        kinds_layout = QVBoxLayout(kinds_pane)
        kinds_layout.setContentsMargins(16, 10, 16, 10)
        kinds_layout.setSpacing(4)
        kinds_cap = QLabel("解析する画面")
        kinds_cap.setObjectName("kindsCaption")
        self.extract_kinds_label = QLabel()
        self.extract_kinds_label.setObjectName("kindsValue")
        self.extract_kinds_label.setWordWrap(True)
        kinds_layout.addWidget(kinds_cap)
        kinds_layout.addWidget(self.extract_kinds_label)
        layout.addWidget(kinds_pane)

        body = QSplitter(Qt.Orientation.Horizontal)
        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(6)
        self.info_label = QLabel("まだ動画がありません")
        self.info_label.setObjectName("hint")
        self.info_label.setWordWrap(True)
        left_layout.addWidget(self.info_label)

        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("抜き出す枚数"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 300)
        self.count_spin.setValue(10)
        count_row.addWidget(self.count_spin)
        count_row.addStretch(1)
        left_layout.addLayout(count_row)
        self.sample_btn = QPushButton("指定枚数を出す")
        self.sample_btn.setObjectName("primary")
        left_layout.addWidget(self.sample_btn)

        self.extract_btn = QPushButton("画像に抜き出す")
        self.extract_btn.setObjectName("primary")
        self.scene_still_btn = QPushButton("CAPTURE")
        extract_grid = QGridLayout()
        extract_grid.setHorizontalSpacing(6)
        extract_grid.setVerticalSpacing(6)
        extract_grid.addWidget(self.extract_btn, 0, 0)
        extract_grid.addWidget(self.scene_still_btn, 0, 1)
        left_layout.addLayout(extract_grid)

        kind_row = QHBoxLayout()
        kind_row.addWidget(QLabel("種類"))
        self.kind_combo = QComboBox()
        kind_row.addWidget(self.kind_combo, 1)
        self.add_kind_btn = QPushButton("種類を追加")
        kind_row.addWidget(self.add_kind_btn)
        left_layout.addLayout(kind_row)
        self.teach_label = QLabel()
        self.teach_label.setObjectName("hint")
        self.teach_label.setWordWrap(True)
        left_layout.addWidget(self.teach_label)
        self.teach_btn = QPushButton("この画像はこの種類")
        self.import_btn = QPushButton("用意した画像を取り込む")
        left_layout.addWidget(self.teach_btn)
        left_layout.addWidget(self.import_btn)
        teach_row2 = QHBoxLayout()
        teach_row2.setSpacing(6)
        self.other_btn = QPushButton("どちらでもない")
        self.scene_train_btn = QPushButton("学習する")
        teach_row2.addWidget(self.other_btn, 1)
        teach_row2.addWidget(self.scene_train_btn, 1)
        left_layout.addLayout(teach_row2)
        self.browse_train_btn = QPushButton("学習画像を見る")
        left_layout.addWidget(self.browse_train_btn)
        self.folder_label = QLabel(f"保存先: {self.output_dir}")
        self.folder_label.setObjectName("hint")
        self.folder_label.setWordWrap(True)
        left_layout.addWidget(self.folder_label)
        self.copy_data_btn = QPushButton("DATAをアップ")
        self.import_data_btn = QPushButton("DATA DOWNLOAD")
        self.server_save_btn = QPushButton("サーバーに保存")
        self.server_load_btn = QPushButton("サーバーから開く")
        self.server_settings_btn = QPushButton("サーバー接続")
        data_grid = QGridLayout()
        data_grid.setHorizontalSpacing(6)
        data_grid.setVerticalSpacing(6)
        data_grid.addWidget(self.copy_data_btn, 0, 0)
        data_grid.addWidget(self.import_data_btn, 0, 1)
        data_grid.addWidget(self.server_save_btn, 1, 0)
        data_grid.addWidget(self.server_load_btn, 1, 1)
        data_grid.addWidget(self.server_settings_btn, 2, 0, 1, 2)
        left_layout.addLayout(data_grid)
        left_layout.addStretch(1)
        left.setMinimumWidth(260)

        preview_col = QFrame()
        preview_col.setObjectName("panel")
        preview_layout = QVBoxLayout(preview_col)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(6)
        self.preview_title = QLabel("プレビュー")
        preview_layout.addWidget(self.preview_title)
        self.preview = ImagePreview("動画を開いて、「指定枚数を出す」を押すと右に出ます")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(280, 280)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview, 1)
        self.coin_box_hint = QLabel("緑の枠がコインを読んでいる場所です。枠が違うときは、ドラッグして囲み直してください。")
        self.coin_box_hint.setObjectName("hint")
        self.coin_box_hint.setWordWrap(True)
        preview_layout.addWidget(self.coin_box_hint)
        coin_fix = QHBoxLayout()
        coin_fix.setSpacing(6)
        self.coin_edit = QLineEdit()
        self.coin_edit.setPlaceholderText("この枠の数字")
        self.coin_save_btn = QPushButton("この数字を覚える")
        self.coin_train_btn = QPushButton("コイン数字を学習する")
        coin_fix.addWidget(self.coin_edit, 1)
        coin_fix.addWidget(self.coin_save_btn)
        coin_fix.addWidget(self.coin_train_btn)
        preview_layout.addLayout(coin_fix)
        self._set_coin_fix_visible(False)

        info_col = QFrame()
        info_col.setObjectName("panel")
        info_layout = QVBoxLayout(info_col)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info_layout.setSpacing(8)
        info_layout.addWidget(QLabel("動画の情報"))
        self.result_btn = QPushButton("resultを抜き出す")
        self.scene_btn = QPushButton("解析")
        self.scene_btn.setObjectName("primary")
        scene_row = QHBoxLayout()
        scene_row.setSpacing(6)
        scene_row.addWidget(self.result_btn, 1)
        scene_row.addWidget(self.scene_btn, 1)
        info_layout.addLayout(scene_row)
        self.video_time_value = self._add_info_block(info_layout, "動画の時間")
        self.go_timeup_value = self._add_info_block(info_layout, "GO → TIME UP")
        self.play_coin_value = self._add_info_block(info_layout, "coin のコイン")
        self.result_coin_value = self._add_info_block(info_layout, "result のコイン")
        self.coin_ratio_value = self._add_info_block(info_layout, "コイン倍率")
        self.wrong_btn = QPushButton("これは違う")
        self.right_btn = QPushButton("合っている")
        self.send_one_btn = QPushButton("指定した枚数をツムツムに渡す")
        self.send_all_btn = QPushButton("一覧をすべて渡す")
        info_layout.addWidget(self.wrong_btn)
        info_layout.addWidget(self.right_btn)
        info_layout.addWidget(self.send_one_btn)
        info_layout.addWidget(self.send_all_btn)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        info_layout.addWidget(self.progress)
        info_layout.addStretch(1)
        info_col.setMinimumWidth(220)

        points_col = QFrame()
        points_col.setObjectName("panel")
        points_layout = QVBoxLayout(points_col)
        points_layout.setContentsMargins(12, 12, 12, 12)
        points_layout.setSpacing(6)
        points_layout.addWidget(QLabel("抜き出し位置（クリックでプレビュー）"))
        self.point_list = QListWidget()
        self.point_list.setViewMode(QListView.ViewMode.ListMode)
        self.point_list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.point_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.point_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        points_layout.addWidget(self.point_list, 1)
        points_col.setMinimumWidth(260)

        body.addWidget(left)
        body.addWidget(preview_col)
        body.addWidget(points_col)
        body.addWidget(info_col)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 3)
        body.setStretchFactor(2, 2)
        body.setStretchFactor(3, 1)
        body.setSizes([320, 560, 360, 240])
        body.splitterMoved.connect(lambda *_: self._fit_preview())
        layout.addWidget(body, 1)
        self.setCentralWidget(root)
        self._train_fx = TrainOverlay(root)
        self._train_fx.cancelRequested.connect(self.cancel_scene_train)
        self.statusBar().showMessage("準備完了")

        self.open_btn.clicked.connect(self.open_video)
        self.folder_btn.clicked.connect(self.choose_folder)
        self.sample_btn.clicked.connect(self.refresh_points)
        self.extract_btn.clicked.connect(self.start_extract)
        self.scene_btn.clicked.connect(self.start_scene_extract)
        self.result_btn.clicked.connect(self.start_result_extract)
        self.scene_still_btn.clicked.connect(self.open_scene_still)
        self.wrong_btn.clicked.connect(self.reject_current_scene)
        self.right_btn.clicked.connect(self.accept_current_scene)
        self.add_kind_btn.clicked.connect(self.add_scene_kind)
        self.teach_btn.clicked.connect(self.teach_current_kind)
        self.import_btn.clicked.connect(self.import_prepared_images)
        self.other_btn.clicked.connect(lambda: self.teach_current(OTHER_KEY))
        self.scene_train_btn.clicked.connect(self.start_scene_train)
        self.browse_train_btn.clicked.connect(self.open_train_images)
        self.preview.box_changed.connect(self.on_coin_box_changed)
        self.coin_save_btn.clicked.connect(self.save_current_coin)
        self.coin_train_btn.clicked.connect(self.start_digit_train)
        self.coin_edit.returnPressed.connect(self.save_current_coin)
        self._fill_kind_combo()
        self.point_list.currentItemChanged.connect(self.on_point_selected)
        self.send_one_btn.clicked.connect(self.send_current_to_tsumtsum)
        self.send_all_btn.clicked.connect(self.send_all_to_tsumtsum)
        self.copy_data_btn.clicked.connect(self.copy_data_folder)
        self.import_data_btn.clicked.connect(self.import_data_folder)
        self.server_save_btn.clicked.connect(self.upload_data_to_server)
        self.server_load_btn.clicked.connect(self.download_data_from_server)
        self.server_settings_btn.clicked.connect(self.edit_server_settings)
        self._update_buttons()

    def _add_info_block(self, layout: QVBoxLayout, caption: str) -> QLabel:
        box = QFrame()
        box.setObjectName("infoPane")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(10, 8, 10, 8)
        box_layout.setSpacing(2)
        cap = QLabel(caption)
        cap.setObjectName("infoCaption")
        value = QLabel("—")
        value.setObjectName("infoValue")
        value.setWordWrap(True)
        value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        box_layout.addWidget(cap)
        box_layout.addWidget(value, 1)
        layout.addWidget(box, 1)
        return value

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        ready = self.info is not None and not busy
        self.extract_btn.setEnabled(ready)
        self.sample_btn.setEnabled(ready)
        self.scene_btn.setEnabled(ready)
        self.result_btn.setEnabled(ready and bool(self.scene_labels.keys_named("result")))
        self.scene_still_btn.setEnabled(self.info is not None)
        self.open_btn.setEnabled(not busy)
        self.count_spin.setEnabled(not busy)
        has_point = ready and self.point_list.currentItem() is not None
        reviewing = has_point and self._current_is_found_scene()
        self.wrong_btn.setEnabled(reviewing)
        self.right_btn.setEnabled(reviewing)
        self.send_one_btn.setEnabled(ready)
        self.send_all_btn.setEnabled(ready and self.point_list.count() > 0)
        has_kind = self._selected_kind() is not None
        self.teach_btn.setEnabled(has_point and has_kind)
        self.import_btn.setEnabled(not busy and has_kind)
        self.other_btn.setEnabled(has_point)
        self.add_kind_btn.setEnabled(not busy)
        self.kind_combo.setEnabled(not busy)
        self.copy_data_btn.setEnabled(not busy)
        self.import_data_btn.setEnabled(not busy)
        self.server_save_btn.setEnabled(not busy)
        self.server_load_btn.setEnabled(not busy)
        self.server_settings_btn.setEnabled(not busy)
        training = isinstance(self.worker, SceneTrainWorker)
        digit_training = isinstance(self.worker, DigitTrainWorker)
        self.scene_train_btn.setEnabled(not busy or training)
        self.scene_train_btn.setText("中止" if training else "学習する")
        coin_ready = has_point and self._coin_box_key_for_point(self._current_point()) is not None
        self.coin_save_btn.setEnabled(coin_ready and not busy)
        self.coin_train_btn.setEnabled((not busy or digit_training) and digit_teaching_count() >= MIN_DIGIT_SAMPLES)
        self.coin_train_btn.setText("中止" if digit_training else "コイン数字を学習する")
        self.coin_edit.setEnabled(coin_ready and not busy)
        self._refresh_teach_label()

    def _fill_kind_combo(self) -> None:
        current = self._selected_kind()
        self.kind_combo.blockSignals(True)
        self.kind_combo.clear()
        self.kind_combo.addItem(self.scene_labels.name_of(OTHER_KEY), OTHER_KEY)
        for key, name in self.scene_labels.kinds():
            self.kind_combo.addItem(name, key)
        if current:
            index = self.kind_combo.findData(current)
            if index >= 0:
                self.kind_combo.setCurrentIndex(index)
        self.kind_combo.blockSignals(False)
        self.scene_btn.setText("解析")
        self._refresh_extract_kinds()

    def _refresh_extract_kinds(self) -> None:
        names = [name for key, name in self.scene_labels.kinds() if key not in self.scene_labels.hidden_keys()]
        if not names:
            self.extract_kinds_label.setText("まだありません")
            return
        self.extract_kinds_label.setText("  /  ".join(names))

    def _selected_kind(self) -> str | None:
        key = self.kind_combo.currentData()
        return str(key) if key else None

    def _found_scene_points(self) -> list:
        points = []
        for point in self._list_points():
            kind = getattr(point, "kind", "sample")
            if kind in self.scene_labels.extract_keys():
                points.append(point)
        return points

    def _current_is_found_scene(self) -> bool:
        item = self.point_list.currentItem()
        if item is None:
            return False
        point = item.data(Qt.ItemDataRole.UserRole)
        kind = getattr(point, "kind", "sample") if point is not None else "sample"
        return kind in self.scene_labels.extract_keys()

    def _refresh_teach_label(self) -> None:
        counts = self.scene_labels.counts()
        parts = [f"{self.scene_labels.name_of(key)} {counts.get(key, 0)}" for key in self.scene_labels.classes()]
        self.teach_label.setText("  ".join(parts) + f"  （学習は各{MIN_SCENE_SAMPLES}枚）")
        if self._train_images is not None:
            self._train_images.reload()

    def _dialog_dir(self, key: str, fallback: Path | None = None) -> str:
        saved = str(self._settings.value(f"last_dir/{key}", "") or "")
        if not saved:
            saved = str(self._settings.value(f"last_{key}_dir", "") or "")
        if saved and Path(saved).is_dir():
            return saved
        if fallback is not None and Path(fallback).is_dir():
            return str(fallback)
        return str(Path.home())

    def _remember_dialog_dir(self, key: str, path: str | Path) -> None:
        target = Path(path)
        folder = target if target.is_dir() else target.parent
        if folder.is_dir():
            self._settings.setValue(f"last_dir/{key}", str(folder.resolve()))

    def open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "動画を開く",
            self._dialog_dir("video"),
            "Video (*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv)",
        )
        if path:
            self._remember_dialog_dir("video", path)
            self.load_video(Path(path))

    def choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "保存先フォルダ", self._dialog_dir("output", self.output_dir))
        if path:
            self.output_dir = Path(path)
            self._remember_dialog_dir("output", self.output_dir)
            self._settings.setValue("last_output_dir", str(self.output_dir))
            self.folder_label.setText(f"保存先: {self.output_dir}")
            if self._scene_still is not None and self.info is not None:
                self._scene_still.output_dir = self.output_dir

    def load_video(self, path: Path) -> None:
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            QMessageBox.warning(self, "未対応の形式", f"{path.suffix} には対応していません。")
            return
        try:
            self.info = read_video_info(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "読み込みに失敗", str(exc))
            return
        self._release_cap()
        self._saved_by_index = {}
        self._coin_cache = {}
        self._coin_box_cache = {}
        self._preview_coin_box = None
        self.info_label.setText(
            f"{path.name}\n"
            f"{self.info.width} × {self.info.height}  /  {self.info.fps:.2f} fps\n"
            f"再生時間 {self.info.format_duration()}  /  {self.info.frame_count} フレーム\n"
            f"抜き出し範囲 {int(RANGE_START*100)}%〜{int(RANGE_END*100)}%"
        )
        self._clear_points()
        self._preview_opened_video()
        self._update_buttons()
        self._remember_dialog_dir("video", path)
        self._settings.setValue("last_video_dir", str(path.parent.resolve()))
        self._settings.setValue("last_video_path", str(path.resolve()))
        self.statusBar().showMessage(
            f"{path.name} を読み込みました。枚数を指定して「指定枚数を出す」を押してください。",
            5000,
        )
        if self._scene_still is not None:
            self._scene_still.set_video(self.info, self.output_dir)

    def _clear_points(self) -> None:
        self.point_list.blockSignals(True)
        self.point_list.clear()
        self.point_list.blockSignals(False)
        self._saved_by_index = {}
        self._preview_point = None
        self._full_pixmap = None
        self._preview_coin_box = None
        if hasattr(self, "preview"):
            self.preview.editable = False
            self._set_coin_fix_visible(False)
        self._fit_point_list()
        self._refresh_info_pane()

    def _preview_opened_video(self) -> None:
        if self.info is None:
            return
        last = max(self.info.frame_count - 1, 0)
        frame = self._read_frame(int(round(0.5 * last)))
        if frame is None:
            self.preview.setText("動画は開きました。枚数を指定して「指定枚数を出す」を押してください")
            self.preview_title.setText("プレビュー")
            self._preview_coin_box = None
            self.preview.editable = False
            self._set_coin_fix_visible(False)
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()
        self._full_pixmap = QPixmap.fromImage(image)
        self._preview_coin_box = None
        self.preview.editable = False
        self._set_coin_fix_visible(False)
        self.preview_title.setText("プレビュー  開いただけです。枚数を指定して「指定枚数を出す」")
        self._fit_preview()

    def refresh_points(self) -> None:
        self.point_list.blockSignals(True)
        self.point_list.clear()
        if self.info is None:
            self.point_list.blockSignals(False)
            self._fit_point_list()
            return
        points = sample_points(self.info, self.count_spin.value())
        for point in points:
            extra = ""
            kind = getattr(point, "kind", "sample")
            if kind and kind not in {"sample", OTHER_KEY}:
                extra = f"{self.scene_labels.name_of(kind)} {point.score:.0%}"
            self.point_list.addItem(self._point_item(point, extra))
        self.point_list.blockSignals(False)
        self._relink_extracted_files()
        if self.point_list.count():
            self.point_list.setCurrentRow(0)
        self._fit_point_list()
        QTimer.singleShot(0, self._fit_point_list)
        self._refresh_info_pane()

    def _point_item(self, point, extra: str = "") -> QListWidgetItem:
        label = f"  {extra}" if extra else ""
        text = f"{point.index}    {format_timecode(point.seconds)}    {point.percent * 100:.1f}%{label}"
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, point)
        return item

    def _fit_point_list(self) -> None:
        self.point_list.setMinimumHeight(0)
        self.point_list.setMaximumHeight(16777215)

    def _relink_extracted_files(self) -> None:
        found: dict[int, Path] = {}
        if self.info is not None:
            for index in range(1, self.count_spin.value() + 1):
                match = extracted_file_for(self.output_dir, self.info.path.stem, index)
                if match is not None:
                    found[index] = match
        self._saved_by_index = found

    def on_point_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        point = current.data(Qt.ItemDataRole.UserRole)
        if point is None:
            return
        self.show_point(point)
        self._update_buttons()

    def show_point(self, point) -> None:
        saved = self._saved_by_index.get(point.index)
        pixmap = None
        source = "動画"
        if saved is not None and saved.exists():
            pixmap = QPixmap(str(saved))
            source = "保存済み"
        if pixmap is None or pixmap.isNull():
            frame = self._read_frame(point.frame)
            if frame is None:
                self.preview.setText("この位置の画像を取得できませんでした")
                self.preview_title.setText("プレビュー")
                self._preview_coin_box = None
                self.preview.editable = False
                self._set_coin_fix_visible(False)
                return
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb.shape
            image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(image)
        self._full_pixmap = pixmap
        self._preview_point = point
        extra = ""
        kind = getattr(point, "kind", "sample")
        if kind and kind not in {"sample", OTHER_KEY}:
            extra = f"  {self.scene_labels.name_of(kind)}  {point.score:.0%}"
        self.preview_title.setText(
            f"プレビュー  {point.index} / {format_timecode(point.seconds)}  ({point.percent * 100:.1f}%){extra}  {source}"
        )
        self._sync_coin_preview(point)
        self._fit_preview()
        self.statusBar().showMessage(
            f"{point.index}枚目  {format_timecode(point.seconds)}  ({point.percent * 100:.1f}%)",
            3000,
        )

    def _coin_box_key_for_point(self, point) -> str | None:
        kind = str(getattr(point, "kind", "") or "")
        if not kind or kind in {"sample", OTHER_KEY}:
            return None
        name = self.scene_labels.name_of(kind).lower()
        if kind in self.scene_labels.keys_named("result") or name == "result":
            return "result_coin"
        if kind in self.scene_labels.keys_named("coin", "コイン") or name in {"coin", "コイン"}:
            return "coin"
        return None

    def _coin_reader_instance(self) -> CoinReader:
        if self._coin_reader is None:
            self._coin_reader = CoinReader()
        return self._coin_reader

    def _coin_cache_key(self, point, box_key: str) -> tuple[str, int, str]:
        return (str(self.info.path) if self.info else "", int(point.frame), box_key)

    def _read_point_coin(self, point, box_key: str) -> str:
        cache_key = self._coin_cache_key(point, box_key)
        if cache_key in self._coin_cache:
            return self._coin_cache[cache_key]
        number = ""
        try:
            path = self._point_image_path(point)
            box, number = self._coin_reader_instance().inspect_path(path, box_key)
            if box is not None:
                self._coin_box_cache[cache_key] = box
        except Exception:
            number = ""
        self._coin_cache[cache_key] = number
        return number

    def _current_point(self):
        item = self.point_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _set_coin_fix_visible(self, visible: bool) -> None:
        self.coin_box_hint.setVisible(visible)
        self.coin_edit.setVisible(visible)
        self.coin_save_btn.setVisible(visible)
        self.coin_train_btn.setVisible(visible)

    def _format_coin_edit(self, number: str) -> str:
        digits = "".join(char for char in (number or "") if char.isdigit())
        if not digits:
            return ""
        return f"{int(digits):,}"

    def _sync_coin_preview(self, point) -> None:
        key = self._coin_box_key_for_point(point)
        if key is None:
            self._preview_coin_box = None
            self.preview.editable = False
            self._set_coin_fix_visible(False)
            return
        cache_key = self._coin_cache_key(point, key)
        number = self._read_point_coin(point, key)
        box = self._coin_box_cache.get(cache_key)
        if box is None:
            try:
                path = self._point_image_path(point)
                box, number = self._coin_reader_instance().inspect_path(path, key)
                if box is not None:
                    self._coin_box_cache[cache_key] = box
                self._coin_cache[cache_key] = number
            except Exception:
                box = None
        self._preview_coin_box = box
        self.preview.editable = True
        self._set_coin_fix_visible(True)
        self.coin_edit.setText(self._format_coin_edit(number))
        self._refresh_info_pane()

    def on_coin_box_changed(self, box: dict) -> None:
        point = self._current_point()
        key = self._coin_box_key_for_point(point) if point is not None else None
        if point is None or key is None:
            return
        cache_key = self._coin_cache_key(point, key)
        self._preview_coin_box = dict(box)
        self._coin_box_cache[cache_key] = dict(box)
        try:
            path = self._point_image_path(point)
            number = self._coin_reader_instance().read_box(path, box)
        except Exception:
            number = ""
        self._coin_cache[cache_key] = number
        self.coin_edit.setText(self._format_coin_edit(number))
        self._refresh_info_pane()

    def save_current_coin(self) -> None:
        point = self._current_point()
        key = self._coin_box_key_for_point(point) if point is not None else None
        if point is None or key is None:
            return
        box = self.preview.box() or self._preview_coin_box
        if box is None:
            QMessageBox.information(self, "枠がありません", "プレビューをドラッグして、コインの数字を囲んでください。")
            return
        try:
            path = self._point_image_path(point)
            count = save_coin_teaching(path, box, key, self.coin_edit.text())
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "覚えられませんでした", str(exc))
            return
        digits = "".join(char for char in self.coin_edit.text() if char.isdigit())
        cache_key = self._coin_cache_key(point, key)
        self._coin_cache[cache_key] = digits
        self._coin_box_cache[cache_key] = dict(box)
        self._preview_coin_box = dict(box)
        self.coin_edit.setText(self._format_coin_edit(digits))
        self._refresh_info_pane()
        self._update_buttons()
        extra = "「コイン数字を学習する」が使えます。" if count >= MIN_DIGIT_SAMPLES else f"学習にはあと {MIN_DIGIT_SAMPLES - count} 枚です。"
        self.statusBar().showMessage(f"コイン {self._format_coin_edit(digits)} を覚えました。いま {count} 枚。{extra}", 6000)

    def start_digit_train(self) -> None:
        if isinstance(self.worker, DigitTrainWorker):
            self.worker.requestInterruption()
            self.coin_train_btn.setEnabled(False)
            self.coin_train_btn.setText("中止しています…")
            self.statusBar().showMessage("コイン数字の学習を中止しています")
            return
        if self.worker is not None:
            return
        count = digit_teaching_count()
        if count < MIN_DIGIT_SAMPLES:
            QMessageBox.information(
                self,
                "まだ足りません",
                f"コイン数字の学習には {MIN_DIGIT_SAMPLES} 枚以上必要です。いま {count} 枚です。",
            )
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 20)
        self.progress.setValue(0)
        self.worker = DigitTrainWorker()
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_digits_trained)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()
        self.statusBar().showMessage("コイン数字を学習しています")

    def on_digits_trained(self, metrics: dict) -> None:
        self.worker = None
        self.progress.setVisible(False)
        if self._coin_reader is not None:
            self._coin_reader.reload()
        self._coin_cache = {}
        self._coin_box_cache = {}
        self._update_buttons()
        acc = float(metrics.get("acc") or 0)
        samples = int(metrics.get("samples") or 0)
        QMessageBox.information(
            self,
            "学習完了",
            f"コイン数字を {samples} 枚で学習しました。精度 {acc:.0%}\n次の解析から使います。",
        )
        point = self._current_point()
        if point is not None:
            self._sync_coin_preview(point)
            self._fit_preview()
        self.statusBar().showMessage(f"コイン数字を学習しました  精度 {acc:.0%}", 5000)

    def _go_timeup_spans(self, points: list) -> list[float]:
        go_keys = set(self.scene_labels.keys_named("go"))
        timeup_keys = set(self.scene_labels.keys_named("timeup", "time up", "time_up"))
        goes = sorted((p for p in points if getattr(p, "kind", "") in go_keys), key=lambda p: p.seconds)
        timeups = sorted((p for p in points if getattr(p, "kind", "") in timeup_keys), key=lambda p: p.seconds)
        used: set[int] = set()
        spans: list[float] = []
        for go in goes:
            nxt = next((item for item in timeups if item.seconds > go.seconds and id(item) not in used), None)
            if nxt is None:
                continue
            used.add(id(nxt))
            spans.append(max(0.0, nxt.seconds - go.seconds))
        return spans

    def _coin_int(self, text: str) -> int | None:
        digits = "".join(char for char in (text or "") if char.isdigit())
        if not digits:
            return None
        return int(digits)

    def _format_ratio(self, result: int, coin: int) -> str:
        if coin <= 0:
            return "—"
        times = result / coin
        if abs(times - round(times)) < 0.05:
            return f"{int(round(times))}倍"
        return f"{times:.2f}倍"

    def _refresh_info_pane(self, read_coins: bool = False) -> None:
        if self.info is None:
            self.video_time_value.setText("—")
            self.go_timeup_value.setText("—")
            self.play_coin_value.setText("—")
            self.result_coin_value.setText("—")
            self.coin_ratio_value.setText("—")
            return
        self.video_time_value.setText(self.info.format_duration())
        points = self._list_points()
        spans = self._go_timeup_spans(points)
        if spans:
            if len(spans) == 1:
                self.go_timeup_value.setText(format_timecode(spans[0]))
            else:
                lines = [f"{index}回目  {format_timecode(span)}" for index, span in enumerate(spans, start=1)]
                self.go_timeup_value.setText("\n".join(lines))
        else:
            self.go_timeup_value.setText("—")

        coin_points = [point for point in points if self._coin_box_key_for_point(point) == "coin"]
        result_points = [point for point in points if self._coin_box_key_for_point(point) == "result_coin"]
        if read_coins and (coin_points or result_points):
            pending = coin_points + result_points
            self.play_coin_value.setText("読み取り中…")
            self.result_coin_value.setText("読み取り中…")
            QApplication.processEvents()
            self.coin_ratio_value.setText("—")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                for index, point in enumerate(pending, start=1):
                    key = self._coin_box_key_for_point(point)
                    if key:
                        self._read_point_coin(point, key)
                    self.statusBar().showMessage(f"コインを読んでいます {index}/{len(pending)}")
                    QApplication.processEvents()
            except Exception:
                pass
            finally:
                QApplication.restoreOverrideCursor()

        def _join(values: list[str]) -> str:
            shown = [value for value in values if value]
            return "\n".join(shown) if shown else "—"

        coin_texts = [
            self._coin_cache.get(self._coin_cache_key(point, "coin"), "") for point in coin_points
        ]
        result_texts = [
            self._coin_cache.get(self._coin_cache_key(point, "result_coin"), "")
            for point in result_points
        ]
        self.play_coin_value.setText(_join(coin_texts))
        self.result_coin_value.setText(_join(result_texts))
        self.coin_ratio_value.setText(self._ratio_text(coin_points, result_points))

    def _ratio_text(self, coin_points: list, result_points: list) -> str:
        coins: list[tuple[float, int]] = []
        for point in sorted(coin_points, key=lambda item: item.seconds):
            number = self._coin_int(self._coin_cache.get(self._coin_cache_key(point, "coin"), ""))
            if number is not None:
                coins.append((point.seconds, number))
        results: list[tuple[float, int]] = []
        for point in sorted(result_points, key=lambda item: item.seconds):
            number = self._coin_int(self._coin_cache.get(self._coin_cache_key(point, "result_coin"), ""))
            if number is not None:
                results.append((point.seconds, number))
        if not coins or not results:
            return "—"
        lines: list[str] = []
        for seconds, result_number in results:
            previous = [item for item in coins if item[0] <= seconds]
            play_number = previous[-1][1] if previous else coins[0][1]
            lines.append(self._format_ratio(result_number, play_number))
        return "\n".join(lines)

    def _read_frame(self, frame_index: int):
        if self.info is None:
            return None
        image = None
        if self._cap is not None and self._cap.isOpened():
            image = grab_frame(self._cap, frame_index, self.info.fps)
        if image is None:
            self._release_cap()
            self._cap = cv2.VideoCapture(str(self.info.path))
            if self._cap.isOpened():
                image = grab_frame(self._cap, frame_index, self.info.fps)
        return image

    def _fit_preview(self) -> None:
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return
        self.preview.set_image(self._full_pixmap, self._preview_coin_box)

    def _release_cap(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._full_pixmap is not None and not self._full_pixmap.isNull():
            self._fit_preview()
        if hasattr(self, "point_list"):
            self._fit_point_list()
        if hasattr(self, "_train_fx"):
            self._train_fx._place()

    def _point_image_path(self, point) -> Path:
        saved = self._saved_by_index.get(point.index)
        if saved is None and self.info is not None:
            saved = extracted_file_for(self.output_dir, self.info.path.stem, point.index)
            if saved is not None:
                self._saved_by_index[point.index] = saved
        if saved is not None and saved.exists():
            return saved
        if self.info is None:
            raise ValueError("動画がありません")
        dest = self.output_dir / f"{self.info.path.stem}_{point.index:03d}_{int(point.percent * 100):02d}pct.png"
        if (
            self._preview_point is not None
            and self._preview_point.index == point.index
            and self._full_pixmap is not None
            and not self._full_pixmap.isNull()
        ):
            if self._full_pixmap.save(str(dest), "PNG"):
                return dest
        frame = self._read_frame(point.frame)
        if frame is None:
            raise ValueError(f"{point.index}枚目の画像を取得できませんでした")
        write_image(dest, frame)
        return dest

    def _list_points(self) -> list:
        points = []
        for row in range(self.point_list.count()):
            item = self.point_list.item(row)
            point = item.data(Qt.ItemDataRole.UserRole)
            if point is not None:
                points.append(point)
        return points

    def send_current_to_tsumtsum(self) -> None:
        if self.info is None:
            QMessageBox.information(self, "動画がありません", "先に動画を開いてください。")
            return
        self.refresh_points()
        points = sample_points(self.info, self.count_spin.value())
        if not points:
            QMessageBox.information(self, "画像がありません", "抜き出す枚数を確認してください。")
            return
        self._handoff_points(points)

    def send_all_to_tsumtsum(self) -> None:
        points = self._list_points()
        if not points:
            QMessageBox.information(self, "画像がありません", "先に動画を開いてください。")
            return
        self._handoff_points(points)

    def _handoff_points(self, points: list) -> None:
        try:
            paths = [self._point_image_path(point) for point in points]
            result = send_images_to_tsumtsum(paths)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "渡せませんでした", str(exc))
            return
        count = len(paths)
        kinds = {getattr(point, "kind", "sample") for point in points}
        extract_keys = set(self.scene_labels.extract_keys())
        if kinds and kinds <= extract_keys:
            teach = "探した画面を確認してください。"
        else:
            teach = "四角を囲んで「この範囲を保存」してください。"
        if result == "sent":
            message = f"{count} 枚をツムツムアプリに渡しました。そちらで{teach}"
        else:
            message = f"ツムツムアプリを開いて {count} 枚を取り込みました。{teach}"
        self.statusBar().showMessage(message, 6000)
        QMessageBox.information(self, "渡しました", message)

    def start_extract(self) -> None:
        if self.info is None or self.worker is not None:
            return
        self.refresh_points()
        points = sample_points(self.info, self.count_spin.value())
        self.progress.setVisible(True)
        self.progress.setRange(0, len(points))
        self.progress.setValue(0)
        self.worker = ExtractWorker(self.info, points, self.output_dir)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()
        self.statusBar().showMessage("抜き出し中です…")

    def start_scene_extract(self) -> None:
        keys = set(self.scene_labels.extract_keys()) | set(self.scene_labels.hidden_keys())
        self._start_kind_extract(keys or None, self.scene_labels.extract_names())

    def start_result_extract(self) -> None:
        keys = self.scene_labels.keys_named("result")
        if not keys:
            QMessageBox.information(
                self,
                "resultがありません",
                "種類に result がありません。先に「種類を追加」してください。",
            )
            return
        self._start_kind_extract(set(keys), self.scene_labels.names_of(keys))

    def open_scene_still(self) -> None:
        start_frame = None
        if self._preview_point is not None:
            start_frame = int(getattr(self._preview_point, "frame", 0) or 0)
        if self._scene_still is None:
            window = SceneStillWindow(self)
            window.setStyleSheet(self.styleSheet())
            window.destroyed.connect(self._clear_scene_still)
            self._scene_still = window
        if self.info is not None:
            self._scene_still.set_video(self.info, self.output_dir, start_frame=start_frame)
        else:
            self._scene_still.output_dir = self.output_dir
        self._scene_still.show()
        self._scene_still.raise_()
        self._scene_still.activateWindow()

    def _clear_scene_still(self, *_args) -> None:
        self._scene_still = None

    def open_train_images(self) -> None:
        if self._train_images is None:
            window = SceneTrainImagesWindow(self)
            window.setStyleSheet(self.styleSheet())
            window.destroyed.connect(self._clear_train_images)
            self._train_images = window
        self._train_images.reload(select_kind=self._selected_kind())
        self._train_images.show()
        self._train_images.raise_()
        self._train_images.activateWindow()

    def _clear_train_images(self, *_args) -> None:
        self._train_images = None

    def _start_kind_extract(self, want_kinds: set[str] | None, names: str) -> None:
        if self.info is None or self.worker is not None:
            return
        if not scene_model_ready():
            QMessageBox.information(
                self,
                "まだ学習していません",
                "種類ごとに用意した画像を取り込み、「どちらでもない」も教えてから"
                f"それぞれ {MIN_SCENE_SAMPLES} 枚以上そろえて「学習する」を押してください。",
            )
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, max(self.info.frame_count, 1))
        self.progress.setValue(0)
        self.worker = SceneExtractWorker(
            self.info,
            self.output_dir,
            want_kinds=want_kinds,
            search_names=names,
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_scene_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()
        self.statusBar().showMessage(f"{names}を探しています…")

    def add_scene_kind(self) -> None:
        name, ok = QInputDialog.getText(self, "種類を追加", "画面の名前")
        if not ok:
            return
        try:
            key = self.scene_labels.add_kind(name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.information(self, "追加できません", str(exc))
            return
        self._fill_kind_combo()
        if self._scene_still is not None:
            self._scene_still._fill_kind_combo()
        index = self.kind_combo.findData(key)
        if index >= 0:
            self.kind_combo.setCurrentIndex(index)
        self._update_buttons()
        self.statusBar().showMessage(f"「{self.scene_labels.name_of(key)}」を追加しました", 4000)

    def teach_current_kind(self) -> None:
        kind = self._selected_kind()
        if kind:
            self.teach_current(kind)

    def import_prepared_images(self) -> None:
        kind = self._selected_kind()
        if kind is None:
            return
        name = self.scene_labels.name_of(kind)
        files, _ = QFileDialog.getOpenFileNames(
            self,
            f"「{name}」の画像を取り込む",
            self._dialog_dir(f"import_{kind}", Path(self._dialog_dir("import"))),
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        paths = [Path(path) for path in files if Path(path).suffix.lower() in IMAGE_EXTENSIONS]
        if not paths:
            return
        self._remember_dialog_dir(f"import_{kind}", paths[0])
        self._remember_dialog_dir("import", paths[0])
        added = self.scene_labels.add_many(paths, kind)
        self._update_buttons()
        counts = self.scene_labels.counts()
        QMessageBox.information(
            self,
            "取り込みました",
            f"「{name}」に {added} 枚取り込みました。\nいま {counts.get(kind, 0)} 枚です。",
        )
        self.statusBar().showMessage(f"「{name}」 {counts.get(kind, 0)} 枚", 5000)

    def teach_current(self, kind: str) -> bool:
        item = self.point_list.currentItem()
        if item is None:
            return False
        point = item.data(Qt.ItemDataRole.UserRole)
        if point is None:
            return False
        try:
            path = self._point_image_path(point)
            self.scene_labels.add(path, kind)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "教えられませんでした", str(exc))
            return False
        self._saved_by_index[point.index] = path
        self._update_buttons()
        name = self.scene_labels.name_of(kind)
        count = self.scene_labels.counts().get(kind, 0)
        self.statusBar().showMessage(f"「{name}」として覚えました。いま {count} 枚です", 5000)
        return True

    def reject_current_scene(self) -> None:
        item = self.point_list.currentItem()
        if item is None:
            return
        point = item.data(Qt.ItemDataRole.UserRole)
        if point is None:
            return
        detected = str(getattr(point, "kind", "") or "")
        options: list[tuple[str, str]] = [(OTHER_KEY, self.scene_labels.name_of(OTHER_KEY))]
        for key in self.scene_labels.extract_keys():
            if key == detected:
                continue
            options.append((key, self.scene_labels.name_of(key)))
        names = [name for _key, name in options]
        picked, ok = QInputDialog.getItem(
            self,
            "これは違う",
            "では、どれですか？",
            names,
            0,
            False,
        )
        if not ok or not picked:
            return
        kind = next(key for key, name in options if name == picked)
        if not self.teach_current(kind):
            return
        if kind == OTHER_KEY:
            self._remove_current_point()
            self.statusBar().showMessage(
                f"「{self.scene_labels.name_of(OTHER_KEY)}」として覚えました。残り {self.point_list.count()} 枚",
                5000,
            )
            return
        point.kind = kind
        extra = f"{self.scene_labels.name_of(kind)} {point.score:.0%}"
        item.setText(self._point_item(point, extra).text())
        self.show_point(point)
        self._update_buttons()
        self._refresh_info_pane(read_coins=True)
        self.statusBar().showMessage(f"「{self.scene_labels.name_of(kind)}」に直して覚えました", 5000)

    def _scene_hash_for_point(self, point) -> int | None:
        if point is None:
            return None
        try:
            return scene_ahash_path(self._point_image_path(point))
        except Exception:
            return None

    def _remove_points_like(self, rejected_hash: int | None) -> int:
        if rejected_hash is None:
            return 0
        removed = 0
        for row in range(self.point_list.count() - 1, -1, -1):
            item = self.point_list.item(row)
            if item is None:
                continue
            digest = self._scene_hash_for_point(item.data(Qt.ItemDataRole.UserRole))
            if digest is None or not hashes_too_close(digest, rejected_hash, REJECT_HASH_LIMIT):
                continue
            self.point_list.takeItem(row)
            removed += 1
        if self.point_list.count():
            self.point_list.setCurrentRow(min(self.point_list.currentRow(), self.point_list.count() - 1))
            if self.point_list.currentRow() < 0:
                self.point_list.setCurrentRow(0)
        self._update_buttons()
        self._refresh_info_pane()
        return removed

    def accept_current_scene(self) -> None:
        item = self.point_list.currentItem()
        if item is None:
            return
        point = item.data(Qt.ItemDataRole.UserRole)
        kind = getattr(point, "kind", None) if point is not None else None
        if not kind or kind in {"sample", OTHER_KEY}:
            return
        if not self.teach_current(kind):
            return
        self._remove_current_point()
        self.statusBar().showMessage(
            f"「{self.scene_labels.name_of(kind)}」で合っています。残り {self.point_list.count()} 枚",
            5000,
        )

    def _remove_current_point(self) -> None:
        row = self.point_list.currentRow()
        item = self.point_list.takeItem(row)
        del item
        if self.point_list.count():
            self.point_list.setCurrentRow(min(row, self.point_list.count() - 1))
        self._update_buttons()
        self._refresh_info_pane()

    def start_scene_train(self) -> None:
        if isinstance(self.worker, SceneTrainWorker):
            self.cancel_scene_train()
            return
        if self.worker is not None:
            return
        missing = self.scene_labels.missing_for_train()
        if missing:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("まだ足りません")
            box.setText(
                f"それぞれ {MIN_SCENE_SAMPLES} 枚以上必要です。\n" + "\n".join(missing)
            )
            other_count = self.scene_labels.counts().get(OTHER_KEY, 0)
            import_btn = None
            if other_count < MIN_SCENE_SAMPLES:
                import_btn = box.addButton("どちらでもない画像を取り込む", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if import_btn is not None and box.clickedButton() is import_btn:
                index = self.kind_combo.findData(OTHER_KEY)
                if index >= 0:
                    self.kind_combo.setCurrentIndex(index)
                self.import_prepared_images()
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, 40)
        self.progress.setValue(0)
        self.worker = SceneTrainWorker(self.scene_labels)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_scene_trained)
        self.worker.failed.connect(self.on_failed)
        self._train_fx.start()
        QApplication.processEvents()
        self.worker.start()
        self._update_buttons()
        self.statusBar().showMessage("学習中です")

    def cancel_scene_train(self) -> None:
        if not isinstance(self.worker, SceneTrainWorker) or not self.worker.isRunning():
            return
        self._train_fx.set_cancelling()
        self.worker.requestInterruption()
        self.scene_train_btn.setEnabled(False)
        self.scene_train_btn.setText("中止しています…")
        self.statusBar().showMessage("学習を中止しています")

    def on_scene_trained(self, metrics: dict) -> None:
        self.worker = None
        self.progress.setVisible(False)
        self._train_fx.stop()
        self._update_buttons()
        acc = float(metrics.get("acc") or 0)
        samples = int(metrics.get("samples") or 0)
        QMessageBox.information(
            self,
            "学習完了",
            f"{samples} 枚で学習しました。精度 {acc:.0%}\n「解析」が使えます。探す種類は上の枠に出ています。",
        )
        self.statusBar().showMessage(f"学習しました  精度 {acc:.0%}", 5000)

    def on_scene_finished(self, paths: list[str]) -> None:
        points = getattr(self.worker, "found_points", []) if self.worker is not None else []
        names = getattr(self.worker, "search_names", "") if self.worker is not None else ""
        self.worker = None
        self.progress.setVisible(False)
        names = names or self.scene_labels.extract_names()
        show = set(self.scene_labels.extract_keys())
        hidden = set(self.scene_labels.hidden_keys())
        hidden_hits = [point for point in points if getattr(point, "kind", "") in hidden]
        points = [point for point in points if getattr(point, "kind", "") in show]
        self._saved_by_index = {}
        for point, path in zip(points, paths):
            self._saved_by_index[point.index] = Path(path)
        if points:
            self.point_list.blockSignals(True)
            self.point_list.clear()
            for point in points:
                name = self.scene_labels.name_of(point.kind)
                self.point_list.addItem(self._point_item(point, f"{name} {point.score:.0%}"))
            self.point_list.blockSignals(False)
            if self.point_list.count():
                self.point_list.setCurrentRow(0)
            self._fit_point_list()
            QTimer.singleShot(0, self._fit_point_list)
        self._update_buttons()
        self._refresh_info_pane(read_coins=bool(points))
        if not points:
            if hidden_hits:
                hidden_names = self.scene_labels.names_of(
                    list(dict.fromkeys(point.kind for point in hidden_hits))
                )
                QMessageBox.information(
                    self,
                    "見つかりませんでした",
                    f"{names} の画面は見つかりませんでした。\n"
                    f"「{hidden_names}」は見つかりましたが、今は結果に出さない種類です。",
                )
                self.statusBar().showMessage(f"{hidden_names} は結果に出していません", 5000)
            else:
                QMessageBox.information(self, "見つかりませんでした", f"{names} の画面は見つかりませんでした。")
                self.statusBar().showMessage(f"{names} は見つかりませんでした", 5000)
            return
        QMessageBox.information(
            self,
            "見つかりました",
            f"{names} を {len(points)} 枚見つけました。\n"
            "間違っていたら「これは違う」で正しい種類を選ぶか、「合っている」を押してください。\n"
            "直したあと「学習する」と、次から精度が上がります。",
        )
        self.statusBar().showMessage(f"{len(points)} 枚見つかりました。間違いは「これは違う」", 6000)

    def on_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        if isinstance(self.worker, SceneTrainWorker):
            self._train_fx.set_progress(current, total, name)
        self.statusBar().showMessage(name)
        QApplication.processEvents()

    def on_finished(self, paths: list[str]) -> None:
        self.worker = None
        self.progress.setVisible(False)
        self._update_buttons()
        self._saved_by_index = {
            index + 1: Path(path) for index, path in enumerate(paths)
        }
        if self.point_list.currentItem() is not None:
            self.on_point_selected(self.point_list.currentItem(), None)
        folder = self.output_dir
        self.statusBar().showMessage(f"{len(paths)} 枚を保存しました", 5000)
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("抜き出し完了")
        box.setText(f"{len(paths)} 枚の画像を保存しました。\n{folder}")
        open_btn = box.addButton("フォルダを開く", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self._open_folder(folder)

    def on_failed(self, message: str) -> None:
        self.worker = None
        self.progress.setVisible(False)
        self._train_fx.stop()
        self._update_buttons()
        if "中止" in message:
            QMessageBox.information(self, "学習を中止", "学習を中止しました。")
            self.statusBar().showMessage("学習を中止しました", 4000)
            return
        QMessageBox.critical(self, "失敗しました", message)

    def _open_folder(self, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        videos = [path for path in paths if path.suffix.lower() in VIDEO_EXTENSIONS]
        if videos:
            self.load_video(videos[0])
            event.acceptProposedAction()
            return
        images = [path for path in paths if path.suffix.lower() in IMAGE_EXTENSIONS]
        kind = self._selected_kind()
        if images and kind:
            added = self.scene_labels.add_many(images, kind)
            self._update_buttons()
            name = self.scene_labels.name_of(kind)
            count = self.scene_labels.counts().get(kind, 0)
            QMessageBox.information(
                self,
                "取り込みました",
                f"「{name}」に {added} 枚取り込みました。\nいま {count} 枚です。",
            )
            self.statusBar().showMessage(f"「{name}」 {count} 枚", 5000)
            event.acceptProposedAction()
            return
        event.ignore()

    def _notify_trainer(self, action: str) -> None:
        sock = QLocalSocket()
        sock.connectToServer(TRAINER_IPC_NAME)
        if not sock.waitForConnected(400):
            return
        sock.write(json.dumps({"action": action}, ensure_ascii=False).encode("utf-8") + b"\n")
        sock.waitForBytesWritten(800)
        sock.disconnectFromServer()

    def _reload_scene_bundle(self) -> None:
        self.scene_labels.reload()
        self._fill_kind_combo()
        self._update_buttons()
        self.statusBar().showMessage("画面の学習データを取り込みました", 5000)

    def copy_data_folder(self) -> None:
        if self.worker is not None:
            return
        dest_parent = QFileDialog.getExistingDirectory(self, "貼り付ける場所を選ぶ", self._dialog_dir("copy_data"))
        if not dest_parent:
            return
        self._remember_dialog_dir("copy_data", dest_parent)
        data_dir = trainer_data_dir()
        dest_parent_path = Path(dest_parent)
        dest = dest_parent_path / data_dir.name
        if is_same_or_inside(dest, data_dir) or is_same_or_inside(dest_parent_path, data_dir):
            QMessageBox.warning(
                self,
                "コピーできません",
                "今使っている data と同じ場所、またはその中にはコピーできません。",
            )
            return
        if dest.exists():
            answer = QMessageBox.question(
                self,
                "すでにあります",
                f"{dest}\nすでに data フォルダがあります。中身を置き換えますか？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            packed = ensure_scene_packed(data_dir)
            if not data_dir.exists():
                raise FileNotFoundError(f"コピーするフォルダがありません。\n{data_dir}")
            dest = copy_data_folder(data_dir, dest_parent_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "コピーに失敗", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        extra = f"\n画面の学習画像 {packed.get('images', 0)} 枚"
        if packed.get("missing"):
            extra += f"（見つからない画像 {packed['missing']} 枚は除きました）"
        self.statusBar().showMessage(f"dataをコピーしました: {dest}", 5000)
        QMessageBox.information(
            self,
            "コピーしました",
            f"ツムの data と、画面の学習データをコピーしました。\n{dest}{extra}",
        )

    def import_data_folder(self) -> None:
        if self.worker is not None:
            return
        chosen = QFileDialog.getExistingDirectory(self, "取り込む data を選ぶ", self._dialog_dir("import_data"))
        if not chosen:
            return
        self._remember_dialog_dir("import_data", chosen)
        data_dir = trainer_data_dir()
        source = resolve_data_dir(Path(chosen))
        if source is None:
            QMessageBox.warning(
                self,
                "dataではありません",
                "index.json か、画像の入った images か、モデルの入った models か、画面の学習データがあるフォルダを選んでください。",
            )
            return
        if resolved(source) == resolved(data_dir):
            QMessageBox.information(self, "同じ場所です", "今使っている data と同じ場所です。")
            return
        if is_same_or_inside(data_dir, source):
            QMessageBox.warning(
                self,
                "取り込めません",
                "今使っている data を含むフォルダは取り込めません。",
            )
            return
        answer = QMessageBox.question(
            self,
            "dataを取り込む",
            "今のツムの画像・枠・モデルと、画面の学習データを、選んだ data で置き換えます。続けますか？\n"
            "画面の学習データが入っていない古い data のときは、今の画面学習はそのまま残します。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._notify_trainer("release-data")
        QApplication.processEvents()
        time.sleep(0.2)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            import_data_folder(data_dir, source)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "取り込みに失敗", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._reload_scene_bundle()
        self._notify_trainer("reload-data")
        QMessageBox.information(self, "取り込みました", "ツムの data と、画面の学習データを取り込みました。")

    def edit_server_settings(self) -> None:
        from app.server_sync import edit_settings

        if edit_settings(self):
            self.statusBar().showMessage("サーバー接続を保存しました", 4000)

    def upload_data_to_server(self) -> None:
        if self.worker is not None:
            return
        import importlib

        from app import server_sync

        importlib.reload(server_sync)

        answer = QMessageBox.question(
            self,
            "サーバーに保存",
            "今のPCの内容でサーバーを上書きします。管理画面で種類を直したあとは、先に「サーバーから開く」をしてください。続けますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        data_dir = trainer_data_dir()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            packed = ensure_scene_packed(data_dir)
            if not data_dir.exists():
                raise FileNotFoundError(f"送るフォルダがありません。\n{data_dir}")
            report = server_sync.run_with_progress(
                self,
                "サーバーに保存しています",
                lambda progress: server_sync.upload_data_dir(data_dir, progress),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存できませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        extra = f"画面の学習画像 {packed.get('images', 0)} 枚"
        title, body = server_sync.format_upload_report(report, extra)
        QMessageBox.information(self, title, body)

    def download_data_from_server(self) -> None:
        if self.worker is not None:
            return
        answer = QMessageBox.question(
            self,
            "サーバーから開く",
            "サーバーの画像・種類・モデルで、今のPCの内容を置き換えます。管理画面で直した種類も、ここで取り込まれます。続けますか？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        import shutil
        import tempfile

        from app import server_sync

        data_dir = trainer_data_dir()
        tmp = Path(tempfile.mkdtemp(prefix="workshop_dl_"))
        self._notify_trainer("release-data")
        QApplication.processEvents()
        time.sleep(0.2)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            server_sync.run_with_progress(
                self,
                "サーバーから開いています",
                lambda progress: server_sync.download_data_dir(tmp, progress),
            )
            import_data_folder(data_dir, tmp)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "開けませんでした", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            shutil.rmtree(tmp, ignore_errors=True)
        self._reload_scene_bundle()
        self._notify_trainer("reload-data")
        QMessageBox.information(self, "開きました", "サーバーの画像とモデルを取り込みました。")

    def _start_ipc(self) -> None:
        self._ipc_server = QLocalServer(self)
        self._ipc_server.newConnection.connect(self._on_ipc_connection)
        if self._ipc_server.listen(IPC_NAME):
            return
        QLocalServer.removeServer(IPC_NAME)
        self._ipc_server.listen(IPC_NAME)

    def _on_ipc_connection(self) -> None:
        sock = self._ipc_server.nextPendingConnection()
        if sock is None:
            return
        self._ipc_buffers[id(sock)] = b""
        sock.readyRead.connect(lambda s=sock: self._on_ipc_ready(s))
        sock.disconnected.connect(lambda s=sock: self._ipc_buffers.pop(id(s), None))
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _on_ipc_ready(self, sock: QLocalSocket) -> None:
        self._ipc_buffers[id(sock)] = self._ipc_buffers.get(id(sock), b"") + bytes(sock.readAll())
        buffer = self._ipc_buffers[id(sock)]
        if b"\n" not in buffer:
            return
        line, rest = buffer.split(b"\n", 1)
        self._ipc_buffers[id(sock)] = rest
        try:
            payload = json.loads(line.decode("utf-8"))
        except Exception:
            return
        if str(payload.get("action") or "") == "reload-scene":
            self._reload_scene_bundle()

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(1000)
        if self._scene_still is not None:
            self._scene_still.close()
        if self._train_images is not None:
            self._train_images.close()
        self._release_cap()
        event.accept()
