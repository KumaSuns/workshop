from __future__ import annotations

import html
import json
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image
import cv2
from PySide6.QtCore import QEvent, QSettings, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPixmap, QShortcut, QKeySequence, QDragEnterEvent, QDropEvent
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
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
    SamplePoint,
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
from app.scene_train import SCENE_EPOCHS, SceneTrainWorker
from app.train_overlay import CPU_RGB, GPU_RGB, GlowBadge, TrainOverlay, apply_device_glow, soft_glow
from app.coin_read import CoinReader, _scale_box, boxes_close
from app.coin_teach import (
    BOX_EPOCHS,
    DIGIT_EPOCHS,
    MIN_DIGIT_SAMPLES,
    DigitTrainWorker,
    digit_teaching_count,
    digit_train_counts,
    save_coin_teaching,
    taught_coin_for_frame,
    taught_coin_for_image,
    taught_keys_for_image,
)
from app.item_slots import (
    ICON_DIM,
    ICON_ON,
    ITEM_ICON_KEYS,
    ITEM_SLOT_KEYS,
    SLOT_LABELS,
    ItemSlotStore,
    box_means_used,
    item_coin_cost,
    sample_color,
)
from app.item_teach import (
    MIN_TSUM_SAMPLES,
    TSUM_EPOCHS,
    TsumReader,
    TsumTrainWorker,
    save_tsum_screen,
    set_tsum_display_name,
    shown_tsum_name,
    tsum_class_names,
    tsum_folder_entries,
    tsum_id_for_name,
    tsum_teaching_count,
)
from app.preview_label import ImagePreview
from app.scene_still_window import SceneStillWindow
from app.scene_train_images_window import SceneTrainImagesWindow
from app.coin_train_images_window import CoinTrainImagesWindow

RECENT_VIDEO_LIMIT = 10
SAVED_COIN_COLOR = "#ff9f43"
RESULT_ICONS = (
    ("score", "Score.png"),
    ("coin", "Coin.png"),
    ("exp", "Exp.png"),
    ("time", "Time.png"),
    ("bomb", "Bomb.png"),
    ("five_to_four", "5over4.png"),
    ("combo", "Combo.png"),
)

STYLESHEET = """
QMainWindow, QWidget {
    background: #16181d;
    color: #e8eaed;
    font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
    font-size: 13px;
}
QLabel#title { font-size: 18px; font-weight: 700; }
QLabel#previewTitle {
    color: #c5cbd6;
    background: #2f3642;
    border-radius: 6px;
    padding: 4px 8px;
}
QLabel#hint { color: #9aa3b2; }
QLabel#fileName { color: #7ec8ff; font-size: 15px; font-weight: 700; }
QLabel#saveDone { color: #8ee0a8; font-size: 14px; font-weight: 700; }
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
QLabel#infoCaption { color: #9aa3b2; font-size: 10px; }
QLabel#infoValue { color: #f2f5f8; font-size: 13px; font-weight: 700; }
QLabel#infoCoinValue { font-size: 13px; font-weight: 700; }
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
        self.worker: ExtractWorker | SceneExtractWorker | SceneTrainWorker | DigitTrainWorker | TsumTrainWorker | None = None
        self.scene_labels = SceneLabels()
        self._settings = QSettings("workshop", "VideoFrameExtractor")
        self.output_dir = Path(__file__).resolve().parent.parent / "output"
        self._cap = None
        self._full_pixmap: QPixmap | None = None
        self._saved_by_index: dict[int, Path] = {}
        self._preview_point = None
        self._ipc_buffers: dict[int, bytes] = {}
        self._coin_reader: CoinReader | None = None
        self._item_store = ItemSlotStore()
        self._tsum_reader: TsumReader | None = None
        self._coin_cache: dict[tuple[str, int, str], str] = {}
        self._coin_box_cache: dict[tuple[str, int, str], dict[str, int]] = {}
        self._item_used_cache: dict[tuple[str, int], set[str]] = {}
        self._item_tsum_cache: dict[tuple[str, int], str] = {}
        self._item_box_cache: dict[tuple[str, int, str], dict[str, int]] = {}
        self._last_item_box: dict[str, int] | None = None
        self._rate_unit = "m"
        self._remembered_coin_keys: set[tuple[str, int, str]] = set()
        self._preview_coin_box: dict[str, int] | None = None
        self._session_box_patterns: dict[str, list[tuple[dict[str, int], int, int]]] = {
            "coin": [],
            "result_coin": [],
        }
        self._box_cycle_at: dict[tuple[str, int, str], int] = {}
        self._scene_still: SceneStillWindow | None = None
        self._train_images: SceneTrainImagesWindow | None = None
        self._coin_train_images: CoinTrainImagesWindow | None = None
        self._train_both = False
        self._both_scene_metrics: dict | None = None
        self._scene_train_started_at: float | None = None
        self._digit_train_started_at: float | None = None
        self._cuda_ready: bool | None = None
        self._extract_started_at: float | None = None
        self._video_extract_started_at: float | None = None
        self._extract_progress = (0, 1)
        self._video_queue: list[Path] = []
        self._video_index = 0
        self._video_durations: dict[str, float] = {}
        self._batch_extract = False
        self._batch_results: list[str] = []
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(100)
        self._elapsed_timer.timeout.connect(self._tick_extract_elapsed)

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
        title_box.addWidget(title)
        top_layout.addLayout(title_box, 1)
        self.open_btn = QPushButton("動画を開く")
        device_wrap = QWidget()
        device_wrap.setStyleSheet("background: transparent;")
        device_row = QHBoxLayout(device_wrap)
        device_row.setContentsMargins(8, 4, 4, 4)
        device_row.setSpacing(10)
        self.cpu_badge = GlowBadge("CPU", CPU_RGB, px=16)
        self.gpu_badge = GlowBadge("GPU", GPU_RGB, px=16)
        self.cpu_badge.setToolTip("画像の抜き出しなど、CPUで動いているときに点滅します")
        self.gpu_badge.setToolTip("解析や学習など、GPUで動いているときに点滅します")
        device_row.addWidget(self.cpu_badge)
        device_row.addWidget(self.gpu_badge)
        top_layout.addWidget(self.open_btn, 0, Qt.AlignmentFlag.AlignTop)
        top_layout.addWidget(device_wrap, 0, Qt.AlignmentFlag.AlignTop)
        layout.addWidget(top)

        body = QSplitter(Qt.Orientation.Horizontal)
        left = QFrame()
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(6)
        self.file_name_label = QLabel()
        self.file_name_label.setObjectName("fileName")
        self.file_name_label.setWordWrap(True)
        self.info_label = QLabel("まだ動画がありません")
        self.info_label.setObjectName("hint")
        self.info_label.setWordWrap(True)
        left_layout.addWidget(self.file_name_label)
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
        self.left_coin_train_btn = QPushButton("コイン数字を学習する")
        left_layout.addWidget(self.left_coin_train_btn)
        self.both_train_btn = QPushButton("上の2つを続けて学習する")
        left_layout.addWidget(self.both_train_btn)
        self.browse_train_btn = QPushButton("学習画像を見る")
        left_layout.addWidget(self.browse_train_btn)
        self.browse_coin_train_btn = QPushButton("コイン学習画像を見る")
        left_layout.addWidget(self.browse_coin_train_btn)
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
        self._preview_col = preview_col
        preview_layout = QVBoxLayout(preview_col)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(6)
        self.preview_title = QLabel("プレビュー")
        self.preview_title.setObjectName("previewTitle")
        preview_layout.addWidget(self.preview_title)
        self.preview = ImagePreview("動画を開いて、「指定枚数を出す」を押すと右に出ます")
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        preview_layout.addWidget(self.preview, 1)
        self._coin_fix = QWidget()
        coin_layout = QVBoxLayout(self._coin_fix)
        coin_layout.setContentsMargins(0, 0, 0, 0)
        coin_layout.setSpacing(6)
        coin_box_row = QHBoxLayout()
        coin_box_row.setSpacing(6)
        self.coin_reuse_btn = QPushButton("既存の枠を使う")
        self.coin_apply_btn = QPushButton("同じ種類にこの枠を使う")
        coin_box_row.addWidget(self.coin_reuse_btn, 1)
        coin_box_row.addWidget(self.coin_apply_btn, 1)
        coin_layout.addLayout(coin_box_row)
        self.coin_edit = QLineEdit()
        self.coin_edit.setPlaceholderText("この枠の数字")
        coin_layout.addWidget(self.coin_edit)
        coin_save_row = QHBoxLayout()
        coin_save_row.setSpacing(6)
        self.coin_box_save_btn = QPushButton("枠を保存")
        self.coin_number_save_btn = QPushButton("数字を保存")
        self.coin_save_btn = QPushButton("枠と数字を保存")
        coin_save_row.addWidget(self.coin_box_save_btn, 1)
        coin_save_row.addWidget(self.coin_number_save_btn, 1)
        coin_save_row.addWidget(self.coin_save_btn, 1)
        coin_layout.addLayout(coin_save_row)
        self.coin_train_btn = QPushButton("コイン数字を学習する")
        coin_layout.addWidget(self.coin_train_btn)
        preview_layout.addWidget(self._coin_fix)
        self._item_fix = QWidget()
        item_layout = QVBoxLayout(self._item_fix)
        item_layout.setContentsMargins(0, 0, 0, 0)
        item_layout.setSpacing(6)
        self.item_slot_combo = QComboBox()
        for key in ITEM_SLOT_KEYS:
            self.item_slot_combo.addItem(SLOT_LABELS[key], key)
        item_layout.addWidget(self.item_slot_combo)
        item_box_row = QHBoxLayout()
        item_box_row.setSpacing(6)
        self.item_reuse_btn = QPushButton("既存の枠を使う")
        self.item_apply_btn = QPushButton("同じ種類にこの枠を使う")
        item_box_row.addWidget(self.item_reuse_btn, 1)
        item_box_row.addWidget(self.item_apply_btn, 1)
        item_layout.addLayout(item_box_row)
        self.tsum_edit = QLineEdit()
        self.tsum_edit.setPlaceholderText("この枠のツム")
        item_layout.addWidget(self.tsum_edit)
        item_save_row = QHBoxLayout()
        item_save_row.setSpacing(6)
        self.item_box_save_btn = QPushButton("枠を保存")
        self.tsum_name_save_btn = QPushButton("名前を保存")
        self.tsum_save_btn = QPushButton("枠と名前を保存")
        item_save_row.addWidget(self.item_box_save_btn, 1)
        item_save_row.addWidget(self.tsum_name_save_btn, 1)
        item_save_row.addWidget(self.tsum_save_btn, 1)
        item_layout.addLayout(item_save_row)
        self.tsum_train_btn = QPushButton("使用ツムを学習する")
        item_layout.addWidget(self.tsum_train_btn)
        preview_layout.addWidget(self._item_fix)
        self._set_coin_fix_visible(False)
        self._set_item_fix_visible(False)

        info_col = QFrame()
        info_col.setObjectName("panel")
        info_layout = QVBoxLayout(info_col)
        info_layout.setContentsMargins(6, 6, 6, 6)
        info_layout.setSpacing(3)
        info_layout.addWidget(QLabel("動画の情報"))
        self.result_btn = QPushButton("resultを抜き出す")
        self.scene_btn = QPushButton("解析")
        self.scene_btn.setObjectName("primary")
        scene_row = QHBoxLayout()
        scene_row.setSpacing(6)
        scene_row.addWidget(self.result_btn, 1)
        scene_row.addWidget(self.scene_btn, 1)
        info_layout.addLayout(scene_row)

        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(4)
        icons_dir = Path(__file__).resolve().parent / "assets" / "icons"
        self._info_icons: dict[str, QLabel] = {}
        self._info_icon_fades: dict[str, QGraphicsOpacityEffect] = {}
        for key, filename in RESULT_ICONS:
            icon = QLabel()
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap(str(icons_dir / filename))
            if not pixmap.isNull():
                icon.setPixmap(
                    pixmap.scaled(
                        28,
                        28,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            fade = QGraphicsOpacityEffect(icon)
            fade.setOpacity(ICON_DIM)
            icon.setGraphicsEffect(fade)
            icon_row.addWidget(icon, 1)
            self._info_icons[key] = icon
            self._info_icon_fades[key] = fade
        info_layout.addLayout(icon_row)
        self.item_cost_value = self._add_info_block(info_layout, "アイテム消費")
        tsum_info = QFrame()
        tsum_info.setObjectName("infoPane")
        tsum_info.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        tsum_info_layout = QVBoxLayout(tsum_info)
        tsum_info_layout.setContentsMargins(6, 2, 6, 2)
        tsum_info_layout.setSpacing(2)
        tsum_cap = QLabel("使用ツム")
        tsum_cap.setObjectName("infoCaption")
        self.used_tsum_value = QLabel("—")
        self.used_tsum_value.setObjectName("infoValue")
        self.used_tsum_value.setWordWrap(True)
        self.used_tsum_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        tsum_head = QHBoxLayout()
        tsum_head.setContentsMargins(0, 0, 0, 0)
        tsum_head.setSpacing(6)
        tsum_head.addWidget(tsum_cap)
        tsum_head.addWidget(self.used_tsum_value, 1)
        tsum_btn_row = QHBoxLayout()
        tsum_btn_row.setSpacing(4)
        self.tsum_fix_btn = QPushButton("修正")
        self.tsum_register_btn = QPushButton("新規登録")
        self.tsum_label_btn = QPushButton("表示名")
        for btn in (self.tsum_fix_btn, self.tsum_register_btn, self.tsum_label_btn):
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(20)
        tsum_btn_row.addWidget(self.tsum_fix_btn, 1)
        tsum_btn_row.addWidget(self.tsum_register_btn, 1)
        tsum_btn_row.addWidget(self.tsum_label_btn, 1)
        tsum_info_layout.addLayout(tsum_head)
        tsum_info_layout.addLayout(tsum_btn_row)
        info_layout.addWidget(tsum_info, 0)

        self.video_time_value = self._add_info_block(info_layout, "動画の時間")
        self.go_timeup_value = self._add_info_block(info_layout, "GO → TIME UP")
        self.play_coin_value = self._add_info_block(info_layout, "coin のコイン")
        self.result_coin_value = self._add_info_block(info_layout, "result のコイン")
        self.play_coin_value.setObjectName("infoCoinValue")
        self.result_coin_value.setObjectName("infoCoinValue")
        self.play_net_value = self._add_info_block(info_layout, "coin から引いた")
        self.result_net_value = self._add_info_block(info_layout, "result から引いた")
        self.coin_ratio_value = self._add_info_block(info_layout, "コイン倍率")
        self.play_per_min_value = self._add_info_block(info_layout, "coin の1分あたり")
        self.result_per_min_value = self._add_info_block(info_layout, "result の1分あたり")
        for label in (self.play_per_min_value, self.result_per_min_value):
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.installEventFilter(self)
        self.wrong_btn = QPushButton("これは違う")
        self.send_one_btn = QPushButton("指定した枚数をツムツムに渡す")
        self.send_all_btn = QPushButton("一覧をすべて渡す")
        for btn in (self.wrong_btn, self.send_one_btn, self.send_all_btn):
            btn.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            btn.setMinimumHeight(22)
        info_layout.addWidget(self.wrong_btn)
        info_layout.addWidget(self.send_one_btn)
        info_layout.addWidget(self.send_all_btn)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        info_layout.addWidget(self.progress)
        self.elapsed_value = self._add_info_block(info_layout, "経過時間", stretch=0)
        self.estimate_value = self._add_info_block(info_layout, "予想時間", stretch=0)
        info_layout.addStretch(1)
        info_col.setMinimumWidth(160)

        extra_col = QFrame()
        extra_col.setObjectName("panel")
        extra_layout = QVBoxLayout(extra_col)
        extra_layout.setContentsMargins(12, 12, 12, 12)
        extra_layout.addStretch(1)
        extra_col.setMinimumWidth(160)
        self._extra_col = extra_col

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
        points_col.setMaximumWidth(360)

        body.addWidget(left)
        body.addWidget(preview_col)
        body.addWidget(points_col)
        body.addWidget(info_col)
        body.addWidget(extra_col)
        self._body_split = body
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 0)
        body.setStretchFactor(2, 1)
        body.setStretchFactor(3, 2)
        body.setStretchFactor(4, 2)
        body.setSizes([320, 400, 260, 180, 180])
        body.splitterMoved.connect(lambda *_: self._fit_preview())
        layout.addWidget(body, 1)
        self.setCentralWidget(root)
        QTimer.singleShot(0, self._fit_preview)
        self._train_fx = TrainOverlay(self)
        self._train_fx.cancelRequested.connect(self.cancel_scene_train)
        self.statusBar().showMessage("準備完了")

        self._device_glow_timer = QTimer(self)
        self._device_glow_timer.setInterval(50)
        self._device_glow_timer.timeout.connect(self._tick_device_glow)
        self.open_btn.clicked.connect(self.open_video)
        self.sample_btn.clicked.connect(self.refresh_points)
        self.extract_btn.clicked.connect(self.start_extract)
        self.scene_btn.clicked.connect(self.start_scene_extract)
        self.result_btn.clicked.connect(self.start_result_extract)
        self.scene_still_btn.clicked.connect(self.open_scene_still)
        self.wrong_btn.clicked.connect(self.reject_current_scene)
        self.teach_btn.clicked.connect(self.teach_current_kind)
        self.import_btn.clicked.connect(self.import_prepared_images)
        self.other_btn.clicked.connect(lambda: self.teach_current(OTHER_KEY))
        self.scene_train_btn.clicked.connect(self.start_scene_train)
        self.left_coin_train_btn.clicked.connect(self.start_digit_train)
        self.both_train_btn.clicked.connect(self.start_both_train)
        self.browse_train_btn.clicked.connect(self.open_train_images)
        self.browse_coin_train_btn.clicked.connect(self.open_coin_train_images)
        self.preview.box_changed.connect(self.on_preview_box_changed)
        self.coin_reuse_btn.clicked.connect(self.use_existing_coin_box)
        self.coin_apply_btn.clicked.connect(self.apply_coin_box_to_same_kind)
        self.coin_box_save_btn.clicked.connect(self.save_current_coin_box)
        self.coin_number_save_btn.clicked.connect(self.save_current_coin_number)
        self.coin_save_btn.clicked.connect(self.save_current_coin)
        self.coin_train_btn.clicked.connect(self.start_digit_train)
        self.coin_edit.returnPressed.connect(self.save_current_coin_number)
        self.item_slot_combo.currentIndexChanged.connect(self.on_item_slot_changed)
        self.item_reuse_btn.clicked.connect(self.use_existing_item_box)
        self.item_apply_btn.clicked.connect(self.apply_item_box_to_same_kind)
        self.item_box_save_btn.clicked.connect(self.save_current_item_box)
        self.tsum_name_save_btn.clicked.connect(self.save_current_tsum_name)
        self.tsum_save_btn.clicked.connect(self.save_current_tsum)
        self.tsum_train_btn.clicked.connect(self.start_tsum_train)
        self.tsum_edit.returnPressed.connect(self.save_current_tsum_name)
        self.tsum_fix_btn.clicked.connect(self.fix_used_tsum)
        self.tsum_register_btn.clicked.connect(self.register_used_tsum)
        self.tsum_label_btn.clicked.connect(self.edit_tsum_display_names)
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

    def _add_info_block(self, layout: QVBoxLayout, caption: str, stretch: int = 0) -> QLabel:
        box = QFrame()
        box.setObjectName("infoPane")
        box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(6, 2, 6, 2)
        box_layout.setSpacing(6)
        cap = QLabel(caption)
        cap.setObjectName("infoCaption")
        value = QLabel("—")
        value.setObjectName("infoValue")
        value.setWordWrap(True)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        box_layout.addWidget(cap)
        box_layout.addWidget(value, 1)
        layout.addWidget(box, stretch)
        return value

    def _update_buttons(self) -> None:
        busy = self.worker is not None
        ready = self.info is not None and not busy
        extracting = isinstance(self.worker, SceneExtractWorker)
        self.extract_btn.setEnabled(ready)
        self.sample_btn.setEnabled(ready)
        self.scene_btn.setEnabled(not busy or extracting)
        self.scene_btn.setText("中止" if extracting else "解析")
        self.result_btn.setEnabled(ready and bool(self.scene_labels.keys_named("result")))
        self.scene_still_btn.setEnabled(self.info is not None)
        self.open_btn.setEnabled(not busy)
        self.count_spin.setEnabled(not busy)
        has_point = ready and self.point_list.currentItem() is not None
        reviewing = has_point and self._current_is_found_scene()
        self.wrong_btn.setEnabled(reviewing)
        self.send_one_btn.setEnabled(ready)
        self.send_all_btn.setEnabled(ready and self.point_list.count() > 0)
        has_kind = self._selected_kind() is not None
        self.teach_btn.setEnabled(has_point and has_kind)
        self.import_btn.setEnabled(not busy and has_kind)
        self.other_btn.setEnabled(has_point)
        self.kind_combo.setEnabled(not busy)
        self.copy_data_btn.setEnabled(not busy)
        self.import_data_btn.setEnabled(not busy)
        self.server_save_btn.setEnabled(not busy)
        self.server_load_btn.setEnabled(not busy)
        self.server_settings_btn.setEnabled(not busy)
        training = isinstance(self.worker, SceneTrainWorker)
        digit_training = isinstance(self.worker, DigitTrainWorker)
        tsum_training = isinstance(self.worker, TsumTrainWorker)
        self.scene_train_btn.setEnabled(not busy or training)
        self.scene_train_btn.setText("中止" if training else "学習する")
        coin_ready = has_point and self._coin_box_key_for_point(self._current_point()) is not None
        item_ready = has_point and self._is_item_point(self._current_point())
        self.coin_box_save_btn.setEnabled(coin_ready and not busy)
        self.coin_number_save_btn.setEnabled(coin_ready and not busy)
        self.coin_save_btn.setEnabled(coin_ready and not busy)
        self.coin_reuse_btn.setEnabled(coin_ready and not busy)
        self.coin_apply_btn.setEnabled(coin_ready and not busy)
        self._set_coin_train_buttons(not busy or digit_training, digit_training)
        self.item_slot_combo.setEnabled(item_ready and not busy)
        self.item_reuse_btn.setEnabled(item_ready and not busy)
        self.item_apply_btn.setEnabled(item_ready and not busy)
        self.item_box_save_btn.setEnabled(item_ready and not busy)
        self.tsum_train_btn.setEnabled((not busy or tsum_training) and (item_ready or tsum_training))
        self.tsum_train_btn.setText("中止" if tsum_training else "使用ツムを学習する")
        if hasattr(self, "tsum_fix_btn"):
            tsum_fix_ready = ready and any(self._is_item_point(point) for point in self._list_points())
            self.tsum_fix_btn.setEnabled(tsum_fix_ready)
            self.tsum_register_btn.setEnabled(tsum_fix_ready)
            self.tsum_label_btn.setEnabled(not busy)
        self.both_train_btn.setEnabled(not busy or self._train_both)
        self.both_train_btn.setText("中止" if self._train_both and busy else "上の2つを続けて学習する")
        self.coin_edit.setEnabled(coin_ready and not busy)
        self._refresh_teach_label()
        self._sync_device_badges()

    def _set_coin_train_buttons(self, enabled: bool, training: bool) -> None:
        text = "中止" if training else "コイン数字を学習する"
        self.coin_train_btn.setEnabled(enabled)
        self.coin_train_btn.setText(text)
        self.left_coin_train_btn.setEnabled(enabled)
        self.left_coin_train_btn.setText(text)

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
        if self._train_images is not None and not getattr(self, "_skip_train_images_reload", False):
            self._train_images.reload()
        if self._coin_train_images is not None and not getattr(self, "_skip_coin_train_images_reload", False):
            self._coin_train_images.reload()

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

    def _recent_video_paths(self) -> list[str]:
        raw = self._settings.value("recent_video_paths", "")
        paths: list[str] = []
        if isinstance(raw, str) and raw.strip():
            try:
                loaded = json.loads(raw)
                if isinstance(loaded, list):
                    paths = [str(item) for item in loaded if item]
            except json.JSONDecodeError:
                paths = []
        elif isinstance(raw, list):
            paths = [str(item) for item in raw if item]
        last = str(self._settings.value("last_video_path", "") or "")
        if last and last not in paths:
            paths.append(last)
        return paths[:RECENT_VIDEO_LIMIT]

    def _remember_opened_video(self, path: Path) -> None:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        recent = [item for item in self._recent_video_paths() if item != key]
        recent.insert(0, key)
        self._settings.setValue(
            "recent_video_paths",
            json.dumps(recent[:RECENT_VIDEO_LIMIT], ensure_ascii=False),
        )

    def _clear_recent_videos(self) -> None:
        self._settings.setValue("recent_video_paths", json.dumps([], ensure_ascii=False))
        self._settings.remove("last_video_path")

    def _confirm_recent_video(self, path: Path) -> bool:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        current = None
        if self.info is not None:
            try:
                current = str(self.info.path.resolve())
            except OSError:
                current = str(self.info.path)
        recent = self._recent_video_paths()
        if current != key and key not in recent:
            return True
        if current == key:
            title = "同じ動画です"
            text = f"今開いている動画と同じです。\n{path.name}\n\nこのまま開き直しますか？"
        else:
            index = recent.index(key) + 1
            title = "以前開いた動画です"
            text = (
                f"この動画は、最近開いた {min(len(recent), RECENT_VIDEO_LIMIT)} 本のなかにあります。"
                f"（{index} 本前）\n{path.name}\n\nこのまま開きますか？"
            )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        open_btn = box.addButton("開く", QMessageBox.ButtonRole.AcceptRole)
        reset_btn = box.addButton("最近開いた10本をリセット", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton("やめる", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reset_btn:
            self._clear_recent_videos()
            return True
        return clicked is open_btn

    def open_video(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "動画を開く（複数可）",
            self._dialog_dir("video"),
            "Video (*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv)",
        )
        if paths:
            self._remember_dialog_dir("video", paths[0])
            self._open_videos([Path(path) for path in paths])

    def _active_compute_device(self) -> str | None:
        if self.worker is None:
            return None
        uses_torch = isinstance(
            self.worker, (SceneExtractWorker, SceneTrainWorker, DigitTrainWorker, TsumTrainWorker)
        )
        if uses_torch and self._cuda_available():
            return "gpu"
        return "cpu"

    def _sync_device_badges(self) -> None:
        active = self._active_compute_device()
        if active is None:
            self._device_glow_timer.stop()
            apply_device_glow(self.cpu_badge, self.gpu_badge, None, 0.0)
            self._train_fx.set_device_glow(None, 0.0)
            return
        if not self._device_glow_timer.isActive():
            self._device_glow_timer.start()
        self._tick_device_glow()

    def _tick_device_glow(self) -> None:
        active = self._active_compute_device()
        if active is None:
            self._device_glow_timer.stop()
            apply_device_glow(self.cpu_badge, self.gpu_badge, None, 0.0)
            self._train_fx.set_device_glow(None, 0.0)
            return
        intensity = soft_glow(time.perf_counter())
        apply_device_glow(self.cpu_badge, self.gpu_badge, active, intensity)
        self._train_fx.set_device_glow(active, intensity)

    def _path_key(self, path: Path) -> str:
        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _unique_video_paths(self, paths: list[Path]) -> list[Path]:
        seen: set[str] = set()
        unique: list[Path] = []
        for path in paths:
            if path.suffix.lower() not in VIDEO_EXTENSIONS or not path.is_file():
                continue
            key = self._path_key(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def _cache_video_duration(self, path: Path) -> float:
        key = self._path_key(path)
        cached = self._video_durations.get(key)
        if cached is not None:
            return cached
        try:
            duration = read_video_info(path).duration
        except Exception:
            duration = 0.0
        self._video_durations[key] = duration
        return duration

    def _refresh_file_name_label(self) -> None:
        if self.info is None:
            self.file_name_label.setText("")
            return
        name = self.info.path.name
        total = len(self._video_queue)
        if total > 1:
            self.file_name_label.setText(f"{name}\n{self._video_index + 1} / {total} 本")
        else:
            self.file_name_label.setText(name)

    def _confirm_recent_videos(self, paths: list[Path]) -> bool:
        if len(paths) == 1:
            return self._confirm_recent_video(paths[0])
        recent = set(self._recent_video_paths())
        hits = [path for path in paths if self._path_key(path) in recent]
        if not hits:
            return True
        names = "\n".join(path.name for path in hits[:12])
        extra = "" if len(hits) <= 12 else f"\n…ほか {len(hits) - 12} 本"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("以前開いた動画があります")
        box.setText(
            f"選んだ {len(paths)} 本のうち {len(hits)} 本は、最近開いた動画です。\n\n"
            f"{names}{extra}\n\nこのまま開きますか？"
        )
        open_btn = box.addButton("開く", QMessageBox.ButtonRole.AcceptRole)
        reset_btn = box.addButton("最近開いた10本をリセット", QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton("やめる", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is reset_btn:
            self._clear_recent_videos()
            return True
        return clicked is open_btn

    def _open_videos(self, paths: list[Path]) -> None:
        videos = self._unique_video_paths(paths)
        if not videos:
            return
        if not self._confirm_recent_videos(videos):
            return
        for path in videos:
            self._cache_video_duration(path)
        self._video_queue = videos
        self._video_index = 0
        self._batch_extract = False
        self._batch_results = []
        if not self.load_video(videos[0], confirm_recent=False, keep_queue=True):
            return
        if len(videos) > 1:
            self.statusBar().showMessage(
                f"{len(videos)} 本を開きました。「解析」で続けて調べます。",
                6000,
            )

    def load_video(self, path: Path, *, confirm_recent: bool = True, keep_queue: bool = False) -> bool:
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            QMessageBox.warning(self, "未対応の形式", f"{path.suffix} には対応していません。")
            return False
        if confirm_recent and not self._confirm_recent_video(path):
            return False
        try:
            self.info = read_video_info(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "読み込みに失敗", str(exc))
            return False
        if not keep_queue:
            self._video_queue = [path]
            self._video_index = 0
            self._batch_extract = False
            self._batch_results = []
        self._video_durations[self._path_key(path)] = self.info.duration
        self._release_cap()
        self._saved_by_index = {}
        self._coin_cache = {}
        self._coin_box_cache = {}
        self._item_used_cache = {}
        self._item_tsum_cache = {}
        self._item_box_cache = {}
        self._preview_coin_box = None
        extra = ""
        if len(self._video_queue) > 1:
            extra = f"\nまとめて {len(self._video_queue)} 本（いま {self._video_index + 1} 本目）"
        self._refresh_file_name_label()
        self.info_label.setText(
            f"{self.info.width} × {self.info.height}  /  {self.info.fps:.2f} fps\n"
            f"再生時間 {self.info.format_duration()}  /  {self.info.frame_count} フレーム\n"
            f"抜き出し範囲 {int(RANGE_START*100)}%〜{int(RANGE_END*100)}%{extra}"
        )
        self._clear_points()
        self._preview_opened_video()
        self._update_buttons()
        self._remember_dialog_dir("video", path)
        self._settings.setValue("last_video_dir", str(path.parent.resolve()))
        self._settings.setValue("last_video_path", str(path.resolve()))
        self._remember_opened_video(path)
        self._refresh_analysis_estimate()
        self.statusBar().showMessage(
            f"{path.name} を読み込みました。枚数を指定して「指定枚数を出す」を押してください。",
            5000,
        )
        if self._scene_still is not None:
            self._scene_still.set_video(self.info, self.output_dir)
        return True

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
            self._set_item_fix_visible(False)
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
        self._set_item_fix_visible(False)
        self.preview_title.setText("プレビュー")
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
        self._mark_incomplete_items()
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

    def _kind_keys(self, *names: str) -> set[str]:
        return set(self.scene_labels.keys_named(*names))

    def _unplayed_item_ids(self, points: list) -> set[int]:
        item_keys = self._kind_keys("item")
        sequence = [
            self._kind_keys("go"),
            self._kind_keys("timeup", "time up", "time_up"),
            self._kind_keys("coin", "コイン"),
            self._kind_keys("result"),
        ]
        if not item_keys or any(not keys for keys in sequence):
            return set()
        ordered = sorted(points, key=lambda point: point.seconds)
        items = [point for point in ordered if getattr(point, "kind", "") in item_keys]
        bad: set[int] = set()
        for index, item in enumerate(items):
            limit = items[index + 1].seconds if index + 1 < len(items) else float("inf")
            window = [
                point
                for point in ordered
                if item.seconds < point.seconds < limit
            ]
            if not self._has_kind_sequence(window, sequence):
                bad.add(id(item))
        return bad

    def _has_kind_sequence(self, points: list, key_sets: list[set[str]]) -> bool:
        step = 0
        for point in points:
            if getattr(point, "kind", "") in key_sets[step]:
                step += 1
                if step >= len(key_sets):
                    return True
        return False

    def _mark_incomplete_items(self) -> None:
        bad = self._unplayed_item_ids(self._list_points())
        warn = QColor("#ff5c5c")
        normal = QColor("#e8eaed")
        for row in range(self.point_list.count()):
            item = self.point_list.item(row)
            if item is None:
                continue
            point = item.data(Qt.ItemDataRole.UserRole)
            item.setForeground(warn if point is not None and id(point) in bad else normal)

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
        if saved is not None and saved.exists():
            pixmap = QPixmap(str(saved))
        if pixmap is None or pixmap.isNull():
            frame = self._read_frame(point.frame)
            if frame is None:
                self.preview.setText("この位置の画像を取得できませんでした")
                self.preview_title.setText("プレビュー")
                self._preview_coin_box = None
                self.preview.editable = False
                self._set_coin_fix_visible(False)
                self._set_item_fix_visible(False)
                return
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channels = rgb.shape
            image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(image)
        self._full_pixmap = pixmap
        self._preview_point = point
        self.preview_title.setText("プレビュー")
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

    def _image_size_for_point(self, point) -> tuple[int, int]:
        if self._preview_point is point and self._full_pixmap is not None and not self._full_pixmap.isNull():
            return self._full_pixmap.width(), self._full_pixmap.height()
        path = self._point_image_path(point)
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            return (0, 0)
        return pixmap.width(), pixmap.height()

    def _session_box_extras(self, key: str) -> list[tuple[dict[str, int], int, int]]:
        return list(self._session_box_patterns.get(key) or [])

    def _remember_session_box(
        self, key: str, box: dict[str, int], width: int, height: int, persist: bool = False
    ) -> dict[str, int]:
        if width <= 0 or height <= 0:
            return {
                "x": int(box["x"]),
                "y": int(box["y"]),
                "w": max(1, int(box["w"])),
                "h": max(1, int(box["h"])),
            }
        cleaned = {
            "x": int(box["x"]),
            "y": int(box["y"]),
            "w": max(1, int(box["w"])),
            "h": max(1, int(box["h"])),
        }
        rows = self._session_box_patterns.setdefault(key, [])
        for existing, src_w, src_h in rows:
            scaled = _scale_box(existing, src_w, src_h, width, height)
            if boxes_close(scaled, cleaned, width, height):
                break
        else:
            rows.insert(0, (cleaned, width, height))
        try:
            self._coin_reader_instance().add_session_pattern(key, cleaned, width, height, persist=persist)
        except Exception:
            pass
        return cleaned

    def _apply_box_to_point(self, point, key: str, box: dict[str, int]) -> None:
        cache_key = self._coin_cache_key(point, key)
        self._coin_box_cache[cache_key] = dict(box)
        try:
            path = self._point_image_path(point)
            number = self._coin_reader_instance().read_box(path, box, key)
        except Exception:
            number = ""
        self._coin_cache[cache_key] = number

    def _coin_cache_key(self, point, box_key: str) -> tuple[str, int, str]:
        return (str(self.info.path) if self.info else "", int(point.frame), box_key)

    def _read_point_coin(self, point, box_key: str) -> str:
        cache_key = self._coin_cache_key(point, box_key)
        if cache_key in self._coin_cache:
            return self._coin_cache[cache_key]
        number = ""
        try:
            path = self._point_image_path(point)
            fps = self.info.fps if self.info is not None else 30.0
            slack = max(8, int(round(fps * 0.2)))
            taught_box, taught_digits = taught_coin_for_image(path, box_key)
            if not taught_digits and self.info is not None:
                taught_box, taught_digits = taught_coin_for_frame(
                    self.info.path, int(point.frame), box_key, frame_slack=slack
                )
            if taught_digits:
                self._remembered_coin_keys.add(cache_key)
            if taught_box is not None:
                self._coin_box_cache[cache_key] = dict(taught_box)
                number = self._coin_reader_instance().read_box(path, taught_box, box_key)
            else:
                box = self._coin_box_cache.get(cache_key)
                if box is not None:
                    number = self._coin_reader_instance().read_box(path, box, box_key)
                else:
                    box, number = self._coin_reader_instance().inspect_path(
                        path, box_key, extra=self._session_box_extras(box_key)
                    )
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
        self.coin_reuse_btn.setVisible(visible)
        self.coin_apply_btn.setVisible(visible)
        self.coin_edit.setVisible(visible)
        self.coin_box_save_btn.setVisible(visible)
        self.coin_number_save_btn.setVisible(visible)
        self.coin_save_btn.setVisible(visible)
        self.coin_train_btn.setVisible(visible)
        if hasattr(self, "_coin_fix"):
            self._coin_fix.setVisible(visible)
        QTimer.singleShot(0, self._fit_preview)

    def _set_item_fix_visible(self, visible: bool) -> None:
        if hasattr(self, "_item_fix"):
            self._item_fix.setVisible(visible)
        if visible:
            self._refresh_item_fix_mode()
        QTimer.singleShot(0, self._fit_preview)

    def _is_item_point(self, point) -> bool:
        if point is None:
            return False
        kind = str(getattr(point, "kind", "") or "")
        if not kind or kind in {"sample", OTHER_KEY}:
            return False
        name = self.scene_labels.name_of(kind).lower()
        return kind in self.scene_labels.keys_named("item") or name == "item"

    def _current_item_slot(self) -> str:
        if not hasattr(self, "item_slot_combo"):
            return ITEM_SLOT_KEYS[0]
        key = self.item_slot_combo.currentData()
        return str(key or ITEM_SLOT_KEYS[0])

    def _item_cache_key(self, point) -> tuple[str, int]:
        return (str(self.info.path) if self.info else "", int(point.frame))

    def _item_box_cache_key(self, point, slot: str) -> tuple[str, int, str]:
        return (str(self.info.path) if self.info else "", int(point.frame), slot)

    def _session_item_extras(self, slot: str) -> list[tuple[dict[str, int], int, int]]:
        return list(self._session_box_patterns.get(slot) or [])

    def _tsum_reader_instance(self) -> TsumReader:
        if self._tsum_reader is None:
            self._tsum_reader = TsumReader()
        return self._tsum_reader

    def _refresh_item_fix_mode(self) -> None:
        self.tsum_edit.setVisible(False)
        self.tsum_name_save_btn.setVisible(False)
        self.tsum_save_btn.setVisible(False)
        self.tsum_train_btn.setVisible(True)

    def _sync_coin_preview(self, point) -> None:
        key = self._coin_box_key_for_point(point)
        if key is not None:
            self._set_item_fix_visible(False)
            cache_key = self._coin_cache_key(point, key)
            number = self._read_point_coin(point, key)
            box = self._coin_box_cache.get(cache_key)
            if box is None:
                try:
                    path = self._point_image_path(point)
                    box, number = self._coin_reader_instance().inspect_path(
                        path, key, extra=self._session_box_extras(key)
                    )
                    if box is not None:
                        self._coin_box_cache[cache_key] = box
                    self._coin_cache[cache_key] = number
                except Exception:
                    box = None
            self._preview_coin_box = box
            self.preview.editable = True
            self._set_coin_fix_visible(True)
            self.coin_edit.setText(self._format_coin_edit(number))
            self._refresh_coin_saved_color(self._coin_is_taught(point, key))
            self._refresh_info_pane()
            return
        if self._is_item_point(point):
            self._set_coin_fix_visible(False)
            self._sync_item_preview(point)
            return
        self._preview_coin_box = None
        self.preview.editable = False
        self._set_coin_fix_visible(False)
        self._set_item_fix_visible(False)

    def _copy_item_box_size(self, source: dict[str, int], point) -> dict[str, int] | None:
        width, height = self._image_size_for_point(point)
        src_w = int(source.get("w") or 0)
        src_h = int(source.get("h") or 0)
        if width <= 0 or height <= 0 or src_w <= 0 or src_h <= 0:
            return None
        w = max(1, min(src_w, width))
        h = max(1, min(src_h, height))
        x = min(max(0, int(source.get("x") or 0)), width - w)
        y = min(max(0, int(source.get("y") or 0)), height - h)
        return {"x": x, "y": y, "w": w, "h": h}

    def _remember_last_item_box(self, box: dict[str, int] | None) -> None:
        if box:
            self._last_item_box = dict(box)

    def _item_boxes_from_other_slots(self, point, slot: str) -> list[dict[str, int]]:
        width, height = self._image_size_for_point(point)
        if width <= 0 or height <= 0:
            return []
        seen: list[dict[str, int]] = []
        for other in ITEM_SLOT_KEYS:
            if other == slot:
                continue
            for box in self._item_store.boxes_for(other, width, height, extra=self._session_item_extras(other)):
                if any(boxes_close(box, existing, width, height) for existing in seen):
                    continue
                seen.append(dict(box))
        return seen

    def _sync_item_preview(self, point) -> None:
        slot = self._current_item_slot()
        box_key = self._item_box_cache_key(point, slot)
        box = self._item_box_cache.get(box_key)
        if box is None:
            width, height = self._image_size_for_point(point)
            box = self._item_store.box_for(slot, width, height, extra=self._session_item_extras(slot))
            if box is not None:
                self._item_box_cache[box_key] = dict(box)
        if box is None:
            shared = self._item_boxes_from_other_slots(point, slot)
            if shared:
                box = shared[0]
                self._item_box_cache[box_key] = dict(box)
        if box is None and self._last_item_box is not None:
            box = self._copy_item_box_size(self._last_item_box, point)
            if box is not None:
                self._item_box_cache[box_key] = dict(box)
        self._preview_coin_box = dict(box) if box else None
        if box is not None:
            self._remember_last_item_box(box)
        self.preview.editable = True
        self._set_item_fix_visible(True)
        self._read_point_items(point)
        self._refresh_info_pane()

    def on_item_slot_changed(self) -> None:
        point = self._current_point()
        if point is None or not self._is_item_point(point):
            return
        self._remember_last_item_box(self.preview.box() or self._preview_coin_box)
        self._sync_item_preview(point)
        self._fit_preview()
        self._update_buttons()

    def on_preview_box_changed(self, box: dict) -> None:
        point = self._current_point()
        if point is not None and self._is_item_point(point):
            self.on_item_box_changed(box)
            return
        self.on_coin_box_changed(box)

    def on_item_box_changed(self, box: dict) -> None:
        point = self._current_point()
        if point is None or not self._is_item_point(point):
            return
        slot = self._current_item_slot()
        self._preview_coin_box = dict(box)
        self._item_box_cache[self._item_box_cache_key(point, slot)] = dict(box)
        self._remember_last_item_box(box)
        width, height = self._image_size_for_point(point)
        self._session_box_patterns.setdefault(slot, [])
        self._remember_session_box(slot, box, width, height)
        self._read_point_items(point, force=True)
        self._refresh_info_pane()

    def _current_item_target(self):
        point = self._current_point()
        if point is None or not self._is_item_point(point):
            return None, None, None
        slot = self._current_item_slot()
        box = self.preview.box() or self._preview_coin_box
        return point, slot, box

    def save_current_item_box(self) -> None:
        point, slot, box = self._current_item_target()
        if point is None or slot is None:
            return
        if box is None:
            QMessageBox.information(self, "枠がありません", "プレビューをドラッグして、場所を囲んでください。")
            return
        width, height = self._image_size_for_point(point)
        color = None
        if slot in ITEM_SLOT_KEYS:
            try:
                with Image.open(self._point_image_path(point)) as image:
                    color = sample_color(image.convert("RGB"), box)
            except Exception:
                color = None
        self._item_store.add(slot, box, width, height, color=color, persist=True)
        self._remember_session_box(slot, box, width, height, persist=False)
        self._item_box_cache[self._item_box_cache_key(point, slot)] = dict(box)
        self._preview_coin_box = dict(box)
        self._read_point_items(point, force=True)
        self._fit_preview()
        self._refresh_info_pane()
        self.statusBar().showMessage("枠の位置を保存しました。次の解析から使います。", 5000)

    def save_current_tsum_name(self) -> None:
        self._save_tsum_parts(persist_box=False)

    def save_current_tsum(self) -> None:
        self._save_tsum_parts(persist_box=True)

    def _save_tsum_parts(self, persist_box: bool) -> None:
        point = self._current_point()
        if point is None or not self._is_item_point(point):
            return
        try:
            path = self._point_image_path(point)
            count, name = save_tsum_screen(
                path,
                self.tsum_edit.text(),
                source_video=self.info.path if self.info is not None else None,
                source_frame=int(point.frame),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存できませんでした", str(exc))
            return
        self._item_tsum_cache[self._item_cache_key(point)] = name
        self.tsum_edit.setText(name)
        self._reload_tsum_reader()
        self._refresh_info_pane()
        extra = (
            "「使用ツムを学習する」が使えます。"
            if count >= MIN_TSUM_SAMPLES
            else f"学習にはあと {MIN_TSUM_SAMPLES - count} 枚です。"
        )
        self.statusBar().showMessage(f"使用ツム {name} を保存しました。いま {count} 枚。{extra}", 6000)

    def _reload_tsum_reader(self) -> None:
        try:
            if self._tsum_reader is None:
                self._tsum_reader = TsumReader()
            else:
                self._tsum_reader.reload()
        except Exception:
            self._tsum_reader = None

    def _used_tsum_target(self, title: str):
        point = self._current_point()
        if point is None or not self._is_item_point(point):
            items = [item for item in self._list_points() if self._is_item_point(item)]
            if len(items) == 1:
                point = items[0]
            elif not items:
                QMessageBox.information(self, title, "item の画面を解析してから使ってください。")
                return None
            else:
                QMessageBox.information(self, title, "直す item の画面を、右の一覧から選んでください。")
                return None
        return point

    def _apply_used_tsum_name(self, name: str, title: str, folder_id: str | None = None) -> None:
        point = self._used_tsum_target(title)
        if point is None:
            return
        try:
            path = self._point_image_path(point)
            count, saved_name = save_tsum_screen(
                path,
                name,
                source_video=self.info.path if self.info is not None else None,
                source_frame=int(point.frame),
                folder_id=folder_id,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存できませんでした", str(exc))
            return
        self._item_tsum_cache[self._item_cache_key(point)] = saved_name
        self._reload_tsum_reader()
        self._refresh_info_pane()
        self.statusBar().showMessage(f"使用ツムを {saved_name} にしました。いま {count} 枚。", 6000)

    def fix_used_tsum(self) -> None:
        names = tsum_class_names()
        if not names:
            QMessageBox.information(
                self,
                "修正",
                "まだ種類がありません。「新規登録」で名前を付けてください。",
            )
            return
        point = self._used_tsum_target("修正")
        if point is None:
            return
        current = self._item_tsum_cache.get(self._item_cache_key(point), "")
        choices = [name for name in names if name != current] or names
        dialog = QDialog(self)
        dialog.setWindowTitle("修正")
        dialog.setModal(True)
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("どれですか？"))
        name_list = QListWidget()
        for name in choices:
            name_list.addItem(name)
        name_list.setCurrentRow(0)
        layout.addWidget(name_list, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_btn.setText("これに直す")
        cancel_btn.setText("やめる")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        name_list.itemDoubleClicked.connect(lambda *_: dialog.accept())
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        row = name_list.currentItem()
        if row is None:
            return
        self._apply_used_tsum_name(row.text(), "修正")

    def register_used_tsum(self) -> None:
        point = self._used_tsum_target("新規登録")
        if point is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("新規登録")
        dialog.setModal(True)
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("表示名"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("キャプテンライトイヤー")
        layout.addWidget(name_edit)
        layout.addWidget(QLabel("フォルダ名"))
        dir_edit = QLineEdit()
        dir_edit.setPlaceholderText("c_bazu")
        layout.addWidget(dir_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_btn.setText("登録する")
        cancel_btn.setText("やめる")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        name_edit.returnPressed.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = " ".join(name_edit.text().split())
        folder_id = "".join(dir_edit.text().split())
        if not name:
            QMessageBox.information(self, "新規登録", "表示名を入力してください。")
            return
        if tsum_id_for_name(name) is not None:
            QMessageBox.information(
                self,
                "新規登録",
                "同じ表示名があります。「修正」で選んでください。",
            )
            return
        self._apply_used_tsum_name(name, "新規登録", folder_id=folder_id or None)

    def edit_tsum_display_names(self) -> None:
        entries = tsum_folder_entries()
        if not entries:
            QMessageBox.information(self, "表示名", "まだ種類がありません。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("表示名")
        dialog.setModal(True)
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("フォルダ"))
        name_list = QListWidget()
        for folder, display in entries:
            row = QListWidgetItem(f"{display}  （{folder}）")
            row.setData(Qt.ItemDataRole.UserRole, folder)
            name_list.addItem(row)
        name_list.setCurrentRow(0)
        layout.addWidget(name_list, 1)
        layout.addWidget(QLabel("表示名"))
        display_edit = QLineEdit()
        layout.addWidget(display_edit)

        def fill_display() -> None:
            row = name_list.currentItem()
            if row is None:
                display_edit.setText("")
                return
            folder = str(row.data(Qt.ItemDataRole.UserRole) or "")
            display_edit.setText(shown_tsum_name(folder))

        name_list.currentItemChanged.connect(lambda *_: fill_display())
        fill_display()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_btn.setText("保存する")
        cancel_btn.setText("やめる")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        row = name_list.currentItem()
        if row is None:
            return
        folder = str(row.data(Qt.ItemDataRole.UserRole) or "")
        display = " ".join(display_edit.text().split())
        try:
            saved = set_tsum_display_name(folder, display)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存できませんでした", str(exc))
            return
        self._reload_tsum_reader()
        for key, name in list(self._item_tsum_cache.items()):
            if tsum_id_for_name(name) == folder or name == folder:
                self._item_tsum_cache[key] = saved
        self._refresh_info_pane()
        self.statusBar().showMessage(f"{folder} の表示名を {saved} にしました。", 5000)

    def use_existing_item_box(self) -> None:
        point, slot, current = self._current_item_target()
        if point is None or slot is None:
            return
        width, height = self._image_size_for_point(point)
        boxes = self._item_store.boxes_for(slot, width, height, extra=self._session_item_extras(slot))
        from_own = bool(boxes)
        if not boxes:
            boxes = self._item_boxes_from_other_slots(point, slot)
        if not boxes and self._last_item_box is not None:
            copied = self._copy_item_box_size(self._last_item_box, point)
            if copied is not None:
                boxes = [copied]
        if not boxes:
            QMessageBox.information(
                self,
                "枠がありません",
                "覚えている枠がまだありません。先に正しい枠で「枠を保存」をしてください。",
            )
            return
        cache_key = self._item_box_cache_key(point, slot)
        start = self._box_cycle_at.get(cache_key, 0)
        chosen = boxes[0]
        index = 0
        if current is not None and width > 0 and height > 0:
            for offset in range(1, len(boxes) + 1):
                index = (start + offset) % len(boxes)
                candidate = boxes[index]
                if not boxes_close(candidate, current, width, height):
                    chosen = candidate
                    break
            else:
                QMessageBox.information(
                    self,
                    "既存の枠",
                    f"この種類の枠は {len(boxes)} パターンあります。いまの枠と同じです。",
                )
                return
        else:
            index = start % len(boxes)
            chosen = boxes[index]
        self._box_cycle_at[cache_key] = index
        self._item_box_cache[cache_key] = dict(chosen)
        self._preview_coin_box = dict(chosen)
        self._remember_last_item_box(chosen)
        if from_own:
            self._remember_session_box(slot, chosen, width, height)
        self.preview.set_image(self._full_pixmap, chosen)
        self._read_point_items(point, force=True)
        self._refresh_info_pane()
        self.statusBar().showMessage(
            f"既存の枠 {index + 1}/{len(boxes)} を使いました。この位置は次の解析からも使います。",
            5000,
        )

    def apply_item_box_to_same_kind(self) -> None:
        point, slot, box = self._current_item_target()
        if point is None or slot is None:
            return
        if box is None:
            QMessageBox.information(self, "枠がありません", "先に枠を直してください。")
            return
        width, height = self._image_size_for_point(point)
        self._remember_session_box(slot, box, width, height)
        self._item_store.add(slot, box, width, height, persist=False)
        updated = 0
        for other in self._list_points():
            if not self._is_item_point(other):
                continue
            other_w, other_h = self._image_size_for_point(other)
            scaled = _scale_box(box, width, height, other_w, other_h) if other_w and other_h else dict(box)
            self._item_box_cache[self._item_box_cache_key(other, slot)] = dict(scaled)
            updated += 1
        self._preview_coin_box = dict(box)
        self._read_point_items(point, force=True)
        self._refresh_info_pane()
        self.statusBar().showMessage(
            f"item {updated} 枚にこの枠を使いました。この位置は次の解析からも使います。",
            5000,
        )

    def _read_point_items(self, point, force: bool = False) -> None:
        cache_key = self._item_cache_key(point)
        have_used = cache_key in self._item_used_cache
        have_tsum = cache_key in self._item_tsum_cache
        if not force and have_used and have_tsum:
            return
        used: set[str] = set(self._item_used_cache.get(cache_key) or [])
        tsum_name = self._item_tsum_cache.get(cache_key, "")
        try:
            path = self._point_image_path(point)
            with Image.open(path) as opened:
                rgb = opened.convert("RGB")
            width, height = rgb.size
            if force or not have_used:
                used = set()
                for slot in ITEM_SLOT_KEYS:
                    box = self._item_box_cache.get(self._item_box_cache_key(point, slot))
                    if box is None:
                        box = self._item_store.box_for(slot, width, height, extra=self._session_item_extras(slot))
                        if box is not None:
                            self._item_box_cache[self._item_box_cache_key(point, slot)] = dict(box)
                    if box is None:
                        continue
                    if box_means_used(rgb, box):
                        used.add(slot)
            if force or not have_tsum:
                tsum_name = self._tsum_reader_instance().read_screen(rgb)
        except Exception:
            pass
        if force or not have_used:
            self._item_used_cache[cache_key] = used
        if force or not have_tsum:
            self._item_tsum_cache[cache_key] = tsum_name

    def start_tsum_train(self) -> None:
        if isinstance(self.worker, TsumTrainWorker):
            self.worker.requestInterruption()
            self.tsum_train_btn.setEnabled(False)
            self.tsum_train_btn.setText("中止しています…")
            self.statusBar().showMessage("使用ツムの学習を中止しています")
            return
        if self.worker is not None:
            return
        count = tsum_teaching_count()
        names = tsum_class_names()
        if count < MIN_TSUM_SAMPLES:
            QMessageBox.information(
                self,
                "まだ足りません",
                f"使用ツムの学習には {MIN_TSUM_SAMPLES} 枚以上必要です。いま {count} 枚です。",
            )
            return
        if not self._confirm_train(
            "使用ツムを学習します",
            "item 画面の使用ツムを見分けます。切り抜きは app/assets/images/use_tsums に種類ごとのフォルダで溜めます。\n"
            f"いま {count} 枚、{len(names)} 種類です。\n始めますか？",
        ):
            return
        self.progress.setVisible(True)
        self.progress.setRange(0, TSUM_EPOCHS)
        self.progress.setValue(0)
        self.worker = TsumTrainWorker()
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_tsum_trained)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()
        self.statusBar().showMessage("使用ツムを学習しています")

    def on_tsum_trained(self, metrics: dict) -> None:
        self.progress.setVisible(False)
        self._clear_worker()
        self._reload_tsum_reader()
        self._item_tsum_cache = {}
        self._update_buttons()
        acc = float(metrics.get("acc") or 0)
        samples = int(metrics.get("samples") or 0)
        kinds = len(metrics.get("classes") or [])
        QMessageBox.information(
            self,
            "学習完了",
            f"使用ツムを {samples} 枚、{kinds} 種類で学習しました。\n"
            "次の解析から使います。",
        )
        self.statusBar().showMessage(f"使用ツムを学習しました  精度 {acc:.0%}", 5000)
        point = self._current_point()
        if point is not None and self._is_item_point(point):
            self._read_point_items(point, force=True)
            self._sync_item_preview(point)
            self._fit_preview()

    def _format_coin_edit(self, number: str) -> str:
        digits = "".join(char for char in (number or "") if char.isdigit())
        if not digits:
            return ""
        return f"{int(digits):,}"

    def _refresh_coin_saved_color(self, saved: bool) -> None:
        self.coin_edit.setStyleSheet(f"color: {SAVED_COIN_COLOR};" if saved else "")

    def on_coin_box_changed(self, box: dict) -> None:
        point = self._current_point()
        key = self._coin_box_key_for_point(point) if point is not None else None
        if point is None or key is None:
            return
        cache_key = self._coin_cache_key(point, key)
        self._preview_coin_box = dict(box)
        self._coin_box_cache[cache_key] = dict(box)
        width, height = self._image_size_for_point(point)
        self._remember_session_box(key, box, width, height)
        try:
            path = self._point_image_path(point)
            number = self._coin_reader_instance().read_box(path, box, key)
        except Exception:
            number = ""
        self._coin_cache[cache_key] = number
        self.coin_edit.setText(self._format_coin_edit(number))
        self._refresh_info_pane()

    def _current_coin_target(self):
        point = self._current_point()
        key = self._coin_box_key_for_point(point) if point is not None else None
        if point is None or key is None:
            return None, None, None
        box = self.preview.box() or self._preview_coin_box
        return point, key, box

    def save_current_coin_box(self) -> None:
        point, key, box = self._current_coin_target()
        if point is None or key is None:
            return
        if box is None:
            QMessageBox.information(self, "枠がありません", "プレビューをドラッグして、コインの数字を囲んでください。")
            return
        width, height = self._image_size_for_point(point)
        self._remember_session_box(key, box, width, height, persist=True)
        self._preview_coin_box = dict(box)
        self._coin_box_cache[self._coin_cache_key(point, key)] = dict(box)
        self._fit_preview()
        self.statusBar().showMessage("枠の位置を保存しました。次の解析から使います。", 5000)

    def save_current_coin_number(self) -> None:
        self._save_coin_parts(persist_box=False)

    def save_current_coin(self) -> None:
        self._save_coin_parts(persist_box=True)

    def _save_coin_parts(self, persist_box: bool) -> None:
        point, key, box = self._current_coin_target()
        if point is None or key is None:
            return
        if box is None:
            QMessageBox.information(self, "枠がありません", "プレビューをドラッグして、コインの数字を囲んでください。")
            return
        try:
            path = self._point_image_path(point)
            count = save_coin_teaching(
                path,
                box,
                key,
                self.coin_edit.text(),
                source_video=self.info.path if self.info is not None else None,
                source_frame=int(point.frame),
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存できませんでした", str(exc))
            return
        digits = "".join(char for char in self.coin_edit.text() if char.isdigit())
        cache_key = self._coin_cache_key(point, key)
        self._coin_cache[cache_key] = digits
        self._coin_box_cache[cache_key] = dict(box)
        self._remembered_coin_keys.add(cache_key)
        self._preview_coin_box = dict(box)
        width, height = self._image_size_for_point(point)
        self._remember_session_box(key, box, width, height, persist=persist_box)
        self.coin_edit.setText(self._format_coin_edit(digits))
        self._refresh_coin_saved_color(True)
        self._refresh_info_pane()
        self._refresh_teach_label()
        self._update_buttons()
        extra = "「コイン数字を学習する」が使えます。" if count >= MIN_DIGIT_SAMPLES else f"学習にはあと {MIN_DIGIT_SAMPLES - count} 枚です。"
        if persist_box:
            message = f"枠と数字 {self._format_coin_edit(digits)} を保存しました。いま {count} 枚。{extra}"
        else:
            message = f"数字 {self._format_coin_edit(digits)} を保存しました。いま {count} 枚。{extra}"
        self.statusBar().showMessage(message, 6000)

    def use_existing_coin_box(self) -> None:
        point = self._current_point()
        key = self._coin_box_key_for_point(point) if point is not None else None
        if point is None or key is None:
            return
        try:
            path = self._point_image_path(point)
            boxes = self._coin_reader_instance().candidate_boxes_for_path(
                path, key, extra=self._session_box_extras(key)
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "枠を使えませんでした", str(exc))
            return
        if not boxes:
            QMessageBox.information(
                self,
                "枠がありません",
                "覚えている枠がまだありません。先に正しい枠で「枠を保存」をしてください。",
            )
            return
        width, height = self._image_size_for_point(point)
        current = self.preview.box() or self._preview_coin_box
        cache_key = self._coin_cache_key(point, key)
        start = self._box_cycle_at.get(cache_key, 0)
        chosen = boxes[0]
        index = 0
        if current is not None and width > 0 and height > 0:
            for offset in range(1, len(boxes) + 1):
                index = (start + offset) % len(boxes)
                candidate = boxes[index]
                if not boxes_close(candidate, current, width, height):
                    chosen = candidate
                    break
            else:
                QMessageBox.information(
                    self,
                    "既存の枠",
                    f"この種類の枠は {len(boxes)} パターンあります。いまの枠と同じです。",
                )
                return
        else:
            index = start % len(boxes)
            chosen = boxes[index]
        self._box_cycle_at[cache_key] = index
        self._apply_box_to_point(point, key, chosen)
        self._preview_coin_box = dict(chosen)
        self._remember_session_box(key, chosen, width, height)
        self.preview.set_image(self._full_pixmap, chosen)
        number = self._coin_cache.get(cache_key, "")
        self.coin_edit.setText(self._format_coin_edit(number))
        self._refresh_info_pane()
        self.statusBar().showMessage(
            f"既存の枠 {index + 1}/{len(boxes)} を使いました。この位置は次の解析からも使います。",
            5000,
        )

    def apply_coin_box_to_same_kind(self) -> None:
        point = self._current_point()
        key = self._coin_box_key_for_point(point) if point is not None else None
        if point is None or key is None:
            return
        box = self.preview.box() or self._preview_coin_box
        if box is None:
            QMessageBox.information(self, "枠がありません", "先に枠を直してください。")
            return
        width, height = self._image_size_for_point(point)
        self._remember_session_box(key, box, width, height)
        updated = 0
        for other in self._list_points():
            if self._coin_box_key_for_point(other) != key:
                continue
            other_w, other_h = self._image_size_for_point(other)
            if other_w <= 0 or other_h <= 0:
                continue
            scaled = _scale_box(box, width, height, other_w, other_h) if (other_w, other_h) != (width, height) else dict(box)
            self._apply_box_to_point(other, key, scaled)
            updated += 1
        self._preview_coin_box = dict(box)
        self.preview.set_image(self._full_pixmap, box)
        cache_key = self._coin_cache_key(point, key)
        self.coin_edit.setText(self._format_coin_edit(self._coin_cache.get(cache_key, "")))
        self._refresh_info_pane()
        label = "coin" if key == "coin" else "result"
        self.statusBar().showMessage(
            f"{label} {updated} 枚にこの枠を使いました。この位置は次の解析からも使います。",
            5000,
        )

    def _confirm_train(self, title: str, message: str, seconds: float | None = None) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        if seconds is not None:
            message = self._append_train_eta(message, seconds)
        box.setText(message)
        start_btn = box.addButton("学習を始める", QMessageBox.ButtonRole.YesRole)
        box.addButton("やめる", QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(start_btn)
        box.exec()
        return box.clickedButton() is start_btn

    def _append_train_eta(self, message: str, seconds: float) -> str:
        eta = self._train_eta_line(seconds)
        if "始めますか？" in message:
            return message.replace("始めますか？", f"{eta}\n\n始めますか？", 1)
        return message.rstrip() + "\n\n" + eta

    def _train_eta_line(self, seconds: float) -> str:
        seconds = max(1.0, seconds)
        clock = (datetime.now() + timedelta(seconds=seconds)).strftime("%H:%M")
        return f"予想完了時間  {clock}頃（約{self._format_extract_elapsed(seconds)}）"

    def _clear_worker(self) -> None:
        worker = self.worker
        if worker is not None and worker.isRunning():
            worker.wait(30000)
        self.worker = None

    def start_digit_train(self) -> None:
        if isinstance(self.worker, DigitTrainWorker):
            self._interrupt_digit_train()
            return
        if self.worker is not None:
            return
        counts = digit_train_counts()
        coin_n = counts["coin"]
        result_n = counts["result_coin"]
        if coin_n < MIN_DIGIT_SAMPLES and result_n < MIN_DIGIT_SAMPLES:
            QMessageBox.information(
                self,
                "まだ足りません",
                f"コイン数字の学習には {MIN_DIGIT_SAMPLES} 枚以上必要です。"
                f"いま coin {coin_n} 枚、result {result_n} 枚です。",
            )
            return
        if not self._confirm_train(
            "コインの数字を学習します",
            "コインの枠の位置と、枠の中の数字を学習します。\n"
            "画面の種類（GO や result など）の学習ではありません。\n"
            "coin と result は別々に学習します。\n\n"
            f"coin {coin_n} 枚、result {result_n} 枚です。\n始めますか？",
            seconds=self._estimate_digit_train_seconds(coin_n + result_n),
        ):
            return
        self._begin_digit_train()

    def _interrupt_digit_train(self) -> None:
        if not isinstance(self.worker, DigitTrainWorker):
            return
        self.worker.requestInterruption()
        self._set_coin_train_buttons(False, True)
        self.coin_train_btn.setText("中止しています…")
        self.left_coin_train_btn.setText("中止しています…")
        if self._train_both:
            self.both_train_btn.setEnabled(False)
            self.both_train_btn.setText("中止しています…")
        self.statusBar().showMessage("コイン数字の学習を中止しています")

    def _begin_digit_train(self) -> None:
        self.progress.setVisible(True)
        self.progress.setRange(0, DIGIT_EPOCHS)
        self.progress.setValue(0)
        self._digit_train_started_at = time.perf_counter()
        self.worker = DigitTrainWorker()
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_digits_trained)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()
        self._update_buttons()
        self.statusBar().showMessage("コインの枠と数字を学習しています")

    def on_digits_trained(self, metrics: dict) -> None:
        self.progress.setVisible(False)
        self._clear_worker()
        try:
            if self._coin_reader is not None:
                self._coin_reader.reload()
        except Exception:
            self._coin_reader = None
        self._coin_cache = {}
        self._coin_box_cache = {}
        both = self._train_both
        scene_metrics = self._both_scene_metrics
        self._train_both = False
        self._both_scene_metrics = None
        self._update_buttons()
        acc = float(metrics.get("acc") or 0)
        samples = int(metrics.get("samples") or 0)
        digit_lines = self._digit_train_summary(metrics)
        self._remember_train_duration("digit", samples, DIGIT_EPOCHS + BOX_EPOCHS, 4, self._digit_train_started_at)
        self._digit_train_started_at = None
        if both and scene_metrics is not None:
            scene_acc = float(scene_metrics.get("acc") or 0)
            scene_samples = int(scene_metrics.get("samples") or 0)
            QMessageBox.information(
                self,
                "学習完了",
                f"画面の種類を {scene_samples} 枚で学習しました。精度 {scene_acc:.0%}\n"
                f"{digit_lines}\n"
                "次の解析から使います。",
            )
            self.statusBar().showMessage("画面の種類とコインを学習しました", 5000)
        else:
            QMessageBox.information(
                self,
                "学習完了",
                f"{digit_lines}\n次の解析から使います。",
            )
            self.statusBar().showMessage(f"コイン数字を学習しました  精度 {acc:.0%}", 5000)
        point = self._current_point()
        if point is not None:
            self._sync_coin_preview(point)
            self._fit_preview()

    def _digit_train_summary(self, metrics: dict) -> str:
        by_key = metrics.get("by_key") or {}
        names = {"coin": "coin", "result_coin": "result"}
        lines = []
        for key in ("coin", "result_coin"):
            item = by_key.get(key)
            if not item:
                continue
            name = names[key]
            samples = int(item.get("samples") or 0)
            iou = float(item.get("iou") or 0)
            acc = float(item.get("acc") or 0)
            box_extra = "。前回より下がったので前のままです" if item.get("box_kept") else ""
            digit_extra = "。前回より下がったので前のままです" if item.get("kept") else ""
            lines.append(f"{name} の枠を {samples} 枚で学習しました。重なり {iou:.0%}{box_extra}")
            lines.append(f"{name} の数字を {samples} 枚で学習しました。数字の一致 {acc:.0%}{digit_extra}")
        if lines:
            return "\n".join(lines)
        acc = float(metrics.get("acc") or 0)
        samples = int(metrics.get("samples") or 0)
        return f"コインを {samples} 枚で学習しました。数字の一致 {acc:.0%}"

    def _go_timeup_pairs(self, points: list) -> list[tuple[float, float]]:
        go_keys = set(self.scene_labels.keys_named("go"))
        timeup_keys = set(self.scene_labels.keys_named("timeup", "time up", "time_up"))
        goes = sorted((p for p in points if getattr(p, "kind", "") in go_keys), key=lambda p: p.seconds)
        timeups = sorted((p for p in points if getattr(p, "kind", "") in timeup_keys), key=lambda p: p.seconds)
        used: set[int] = set()
        pairs: list[tuple[float, float]] = []
        for go in goes:
            nxt = next((item for item in timeups if item.seconds > go.seconds and id(item) not in used), None)
            if nxt is None:
                continue
            used.add(id(nxt))
            pairs.append((go.seconds, nxt.seconds))
        return pairs

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
            if hasattr(self, "play_net_value"):
                self.play_net_value.setText("—")
            if hasattr(self, "result_net_value"):
                self.result_net_value.setText("—")
            self.coin_ratio_value.setText("—")
            self.play_per_min_value.setText("—")
            self.result_per_min_value.setText("—")
            self.elapsed_value.setText("—")
            self.estimate_value.setText("—")
            if hasattr(self, "used_tsum_value"):
                self.used_tsum_value.setText("—")
            if hasattr(self, "item_cost_value"):
                self.item_cost_value.setText("—")
            self._set_item_icons(set())
            return
        self.video_time_value.setText(self.info.format_duration())
        points = self._list_points()
        pairs = self._go_timeup_pairs(points)
        if pairs:
            if len(pairs) == 1:
                start, end = pairs[0]
                self.go_timeup_value.setText(format_timecode(end - start))
            else:
                self.go_timeup_value.setText(
                    "\n".join(
                        f"{index}回目  {format_timecode(end - start)}"
                        for index, (start, end) in enumerate(pairs, start=1)
                    )
                )
        else:
            self.go_timeup_value.setText("—")

        coin_points = [point for point in points if self._coin_box_key_for_point(point) == "coin"]
        result_points = [point for point in points if self._coin_box_key_for_point(point) == "result_coin"]
        if read_coins and (coin_points or result_points):
            pending = coin_points + result_points
            self.play_coin_value.setText("読み取り中…")
            self.result_coin_value.setText("読み取り中…")
            if hasattr(self, "play_net_value"):
                self.play_net_value.setText("—")
            if hasattr(self, "result_net_value"):
                self.result_net_value.setText("—")
            QApplication.processEvents()
            self.coin_ratio_value.setText("—")
            self.play_per_min_value.setText("—")
            self.result_per_min_value.setText("—")
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

        self._set_coin_value_text(self.play_coin_value, coin_points, "coin")
        self._set_coin_value_text(self.result_coin_value, result_points, "result_coin")
        self.coin_ratio_value.setText(self._ratio_text(coin_points, result_points))
        item_points = [point for point in points if self._is_item_point(point)]
        if read_coins and item_points:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                for index, point in enumerate(item_points, start=1):
                    self._read_point_items(point, force=True)
                    self.statusBar().showMessage(f"アイテムを読んでいます {index}/{len(item_points)}")
                    QApplication.processEvents()
            except Exception:
                pass
            finally:
                QApplication.restoreOverrideCursor()
        used: set[str] = set()
        tsum_names: list[str] = []
        cost_parts: list[str] = []
        for point in item_points:
            cache_key = self._item_cache_key(point)
            point_used = set(self._item_used_cache.get(cache_key) or [])
            used |= point_used
            name = shown_tsum_name(self._item_tsum_cache.get(cache_key, ""))
            if name:
                tsum_names.append(html.escape(name))
            if point_used or cache_key in self._item_used_cache:
                cost_parts.append(f"{item_coin_cost(point_used):,}")
        self._set_item_icons(used)
        if hasattr(self, "item_cost_value"):
            if cost_parts:
                self.item_cost_value.setText("\n".join(cost_parts))
            else:
                self.item_cost_value.setText("—")
        if hasattr(self, "used_tsum_value"):
            if tsum_names:
                self.used_tsum_value.setTextFormat(Qt.TextFormat.RichText)
                self.used_tsum_value.setText("<br>".join(tsum_names))
            else:
                self.used_tsum_value.setTextFormat(Qt.TextFormat.PlainText)
                self.used_tsum_value.setText("—")
        play_net, result_net = self._net_coin_texts(coin_points, result_points)
        if hasattr(self, "play_net_value"):
            self.play_net_value.setText(play_net)
        if hasattr(self, "result_net_value"):
            self.result_net_value.setText(result_net)
        play_rate, result_rate = self._per_minute_texts(coin_points, result_points)
        self.play_per_min_value.setText(play_rate)
        self.result_per_min_value.setText(result_rate)
        if read_coins:
            self._relabel_item_points()

    def _item_point_extra(self, point) -> str:
        extra = f"{self.scene_labels.name_of(point.kind)} {point.score:.0%}"
        tsum = shown_tsum_name(self._item_tsum_cache.get(self._item_cache_key(point), ""))
        if tsum:
            extra = f"{extra}  {tsum}"
        return extra

    def _relabel_item_points(self) -> None:
        if not hasattr(self, "point_list"):
            return
        for row in range(self.point_list.count()):
            item = self.point_list.item(row)
            if item is None:
                continue
            point = item.data(Qt.ItemDataRole.UserRole)
            if point is None or not self._is_item_point(point):
                continue
            label = f"  {self._item_point_extra(point)}"
            item.setText(
                f"{point.index}    {format_timecode(point.seconds)}    {point.percent * 100:.1f}%{label}"
            )

    def _set_item_icons(self, used: set[str]) -> None:
        fades = getattr(self, "_info_icon_fades", None)
        if not fades:
            return
        for slot, icon_key in ITEM_ICON_KEYS.items():
            fade = fades.get(icon_key)
            if fade is not None:
                fade.setOpacity(ICON_ON if slot in used else ICON_DIM)

    def _set_coin_value_text(self, label: QLabel, points: list, box_key: str) -> None:
        parts: list[str] = []
        for point in points:
            cache_key = self._coin_cache_key(point, box_key)
            text = self._coin_cache.get(cache_key, "")
            if not text:
                continue
            shown = html.escape(text)
            if self._coin_is_taught(point, box_key):
                parts.append(f'<span style="color:{SAVED_COIN_COLOR}">{shown}</span>')
            else:
                parts.append(f'<span style="color:#f2f5f8">{shown}</span>')
        if not parts:
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText("—")
            return
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setText("<br>".join(parts))

    def _coin_is_taught(self, point, box_key: str) -> bool:
        cache_key = self._coin_cache_key(point, box_key)
        if cache_key in self._remembered_coin_keys:
            return True
        saved = self._saved_by_index.get(point.index)
        if saved is not None and saved.exists() and box_key in taught_keys_for_image(saved):
            self._remembered_coin_keys.add(cache_key)
            return True
        if self.info is not None:
            fps = self.info.fps if self.info.fps else 30.0
            _box, digits = taught_coin_for_frame(
                self.info.path, int(point.frame), box_key, frame_slack=max(8, int(round(fps * 0.2)))
            )
            if digits:
                self._remembered_coin_keys.add(cache_key)
                return True
        return False

    def _coin_numbers(self, points: list, box_key: str) -> list[tuple[float, int]]:
        numbers: list[tuple[float, int]] = []
        for point in sorted(points, key=lambda item: item.seconds):
            number = self._coin_int(self._coin_cache.get(self._coin_cache_key(point, box_key), ""))
            if number is not None:
                numbers.append((point.seconds, number))
        return numbers

    def _pick_number_in_window(
        self,
        numbers: list[tuple[float, int]],
        start: float,
        end: float,
        after: float,
    ) -> int | None:
        in_window = [item for item in numbers if start < item[0] < end]
        later = [item for item in in_window if item[0] >= after]
        if later:
            return later[0][1]
        if in_window:
            return in_window[0][1]
        return None

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and watched in {getattr(self, "play_per_min_value", None), getattr(self, "result_per_min_value", None)}
        ):
            self._cycle_rate_unit()
            return True
        return super().eventFilter(watched, event)

    def _cycle_rate_unit(self) -> None:
        self._rate_unit = "h" if self._rate_unit == "m" else "m"
        self._refresh_info_pane()

    def _format_per_minute(self, amount: int | None, duration_sec: float) -> str:
        if amount is None or duration_sec <= 0:
            return "—"
        per_sec = amount / duration_sec
        if self._rate_unit == "h":
            value = per_sec * 3600.0
        else:
            value = per_sec * 60.0
        return f"{value:.2f} /{self._rate_unit}"

    def _rate_lines(self, values: list[str]) -> str:
        if not values:
            return "—"
        if len(values) == 1:
            return values[0]
        return "\n".join(
            f"{index}回目  {text}" for index, text in enumerate(values, start=1)
        )

    def _format_net_amount(self, amount: int | None) -> str:
        if amount is None:
            return "—"
        return f"{amount:,}"

    def _item_cost_before_go(self, points: list, prev_end: float, go: float) -> int:
        items = [
            point
            for point in points
            if self._is_item_point(point) and prev_end < point.seconds <= go
        ]
        if not items:
            return 0
        used = set(self._item_used_cache.get(self._item_cache_key(items[-1])) or [])
        return item_coin_cost(used)

    def _game_net_amounts(
        self, coin_points: list, result_points: list
    ) -> list[tuple[float, int | None, int | None]]:
        points = self._list_points()
        pairs = self._go_timeup_pairs(points)
        coins = self._coin_numbers(coin_points, "coin")
        results = self._coin_numbers(result_points, "result_coin")
        games: list[tuple[float, int | None, int | None]] = []
        prev_end = 0.0
        for index, (go, timeup) in enumerate(pairs):
            next_go = pairs[index + 1][0] if index + 1 < len(pairs) else float("inf")
            cost = self._item_cost_before_go(points, prev_end, go)
            play = self._pick_number_in_window(coins, go, next_go, timeup)
            result = self._pick_number_in_window(results, go, next_go, timeup)
            net_play = None if play is None else play - cost
            net_result = None if result is None else result - cost
            games.append((timeup - go, net_play, net_result))
            prev_end = timeup
        return games

    def _net_coin_texts(self, coin_points: list, result_points: list) -> tuple[str, str]:
        games = self._game_net_amounts(coin_points, result_points)
        if not games:
            return "—", "—"
        play_lines = [self._format_net_amount(play) for _duration, play, _result in games]
        result_lines = [self._format_net_amount(result) for _duration, _play, result in games]
        return self._rate_lines(play_lines), self._rate_lines(result_lines)

    def _per_minute_texts(self, coin_points: list, result_points: list) -> tuple[str, str]:
        games = self._game_net_amounts(coin_points, result_points)
        if not games:
            return "—", "—"
        play_lines = [
            self._format_per_minute(play, duration) for duration, play, _result in games
        ]
        result_lines = [
            self._format_per_minute(result, duration) for duration, _play, result in games
        ]
        return self._rate_lines(play_lines), self._rate_lines(result_lines)

    def _ratio_text(self, coin_points: list, result_points: list) -> str:
        coins = self._coin_numbers(coin_points, "coin")
        results = self._coin_numbers(result_points, "result_coin")
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
        self._sync_preview_3_2()
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return
        self.preview.set_image(self._full_pixmap, self._preview_coin_box)

    def _sync_preview_3_2(self) -> None:
        if getattr(self, "_syncing_preview", False):
            return
        col = getattr(self, "_preview_col", None)
        split = getattr(self, "_body_split", None)
        if col is None or split is None or not hasattr(self, "preview"):
            return
        margins = col.contentsMargins()
        spacing = col.layout().spacing() if col.layout() is not None else 0
        title_h = self.preview_title.sizeHint().height() if hasattr(self, "preview_title") else 0
        height = col.height() - margins.top() - margins.bottom() - title_h - spacing
        if height < 80:
            return
        width = (height * 2) // 3
        col_w = width + margins.left() + margins.right()
        if self.preview.width() == width and col.minimumWidth() == col_w and col.maximumWidth() == col_w:
            return
        self._syncing_preview = True
        self.preview.setFixedWidth(width)
        col.setMinimumWidth(col_w)
        col.setMaximumWidth(col_w)
        sizes = split.sizes()
        if len(sizes) >= 5 and sizes[1] != col_w:
            leftover = sizes[1] - col_w
            sizes[1] = col_w
            if leftover != 0:
                sizes[3] = max(160, sizes[3] + leftover // 2)
                sizes[4] = max(160, sizes[4] + leftover - leftover // 2)
            split.setSizes(sizes)
        self._syncing_preview = False

    def _release_cap(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "preview"):
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

    def add_captured_scene(self, kind: str, frame: int, path: Path) -> bool:
        if self.info is None or kind == OTHER_KEY:
            return False
        if kind not in set(self.scene_labels.extract_keys()):
            return False
        fps = max(self.info.fps, 1e-6)
        duration = max(self.info.duration, 1e-6)
        seconds = frame / fps
        captured = SamplePoint(
            index=0,
            percent=min(max(seconds / duration, 0.0), 1.0),
            seconds=seconds,
            frame=int(frame),
            kind=kind,
            score=1.0,
        )
        points = self._list_points()
        old = self._same_kind_in_game(points, captured)
        path_by_id: dict[int, Path] = {}
        for point in points:
            saved = self._saved_by_index.get(point.index)
            if saved is not None:
                path_by_id[id(point)] = saved
        if old is not None:
            points = [point for point in points if point is not old]
            path_by_id.pop(id(old), None)
        points.append(captured)
        path_by_id[id(captured)] = path
        points.sort(key=lambda point: (point.seconds, point.index))
        for index, point in enumerate(points, start=1):
            point.index = index
        self._saved_by_index = {
            point.index: path_by_id[id(point)]
            for point in points
            if id(point) in path_by_id
        }
        self._fill_scene_points(points, select=captured)
        self._update_buttons()
        self._refresh_info_pane(read_coins=True)
        return True

    def _same_kind_in_game(self, points: list, captured) -> object | None:
        item_keys = self._kind_keys("item")
        ordered = sorted(points, key=lambda point: point.seconds)
        items = [point for point in ordered if getattr(point, "kind", "") in item_keys]
        start = 0.0
        end = float("inf")
        for index, item in enumerate(items):
            if item.seconds <= captured.seconds:
                start = item.seconds
                end = items[index + 1].seconds if index + 1 < len(items) else float("inf")
        for point in points:
            if getattr(point, "kind", "") == captured.kind and start <= point.seconds < end:
                return point
        return None

    def _fill_scene_points(self, points: list, select=None) -> None:
        self.point_list.blockSignals(True)
        self.point_list.clear()
        select_row = 0
        for row, point in enumerate(points):
            extra = ""
            kind = getattr(point, "kind", "sample")
            if kind and kind not in {"sample", OTHER_KEY}:
                extra = f"{self.scene_labels.name_of(kind)} {point.score:.0%}"
            self.point_list.addItem(self._point_item(point, extra))
            if select is not None and point is select:
                select_row = row
        self.point_list.blockSignals(False)
        if self.point_list.count():
            self.point_list.setCurrentRow(select_row)
        self._mark_incomplete_items()
        self._fit_point_list()
        QTimer.singleShot(0, self._fit_point_list)

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
        if isinstance(self.worker, SceneExtractWorker):
            self._cancel_scene_extract()
            return
        if self.info is not None and self._video_queue:
            current = self._path_key(self.info.path)
            for index, path in enumerate(self._video_queue):
                if self._path_key(path) == current:
                    self._video_index = index
                    break
        remaining = len(self._video_queue) - self._video_index
        self._batch_extract = remaining > 1
        self._batch_results = []
        keys = set(self.scene_labels.extract_keys()) | set(self.scene_labels.hidden_keys())
        self._start_kind_extract(keys or None, self.scene_labels.extract_names())

    def _cancel_scene_extract(self) -> None:
        if not isinstance(self.worker, SceneExtractWorker) or not self.worker.isRunning():
            return
        self._batch_extract = False
        self.worker.requestInterruption()
        self.scene_btn.setEnabled(False)
        self.scene_btn.setText("中止しています…")
        self.statusBar().showMessage("解析を中止しています")

    def start_result_extract(self) -> None:
        keys = self.scene_labels.keys_named("result")
        if not keys:
            QMessageBox.information(
                self,
                "resultがありません",
                "種類に result がありません。",
            )
            return
        self._batch_extract = False
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

    def open_coin_train_images(self) -> None:
        if self._coin_train_images is None:
            window = CoinTrainImagesWindow(self)
            window.setStyleSheet(self.styleSheet())
            window.destroyed.connect(self._clear_coin_train_images)
            self._coin_train_images = window
        self._coin_train_images.reload()
        self._coin_train_images.show()
        self._coin_train_images.raise_()
        self._coin_train_images.activateWindow()

    def _clear_coin_train_images(self, *_args) -> None:
        self._coin_train_images = None

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
        self._extract_progress = (0, max(self.info.frame_count, 1))
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
        if self._extract_started_at is None:
            self._extract_started_at = time.perf_counter()
            self._elapsed_timer.start()
        self._video_extract_started_at = time.perf_counter()
        self._tick_extract_elapsed()
        self._refresh_analysis_estimate()
        self._update_buttons()
        prefix = ""
        total = len(self._video_queue)
        if self._batch_extract and total > 1:
            prefix = f"{self._video_index + 1}/{total}  "
        self.statusBar().showMessage(f"{prefix}{names}を探しています…")

    def teach_current_kind(self) -> None:
        kind = self._selected_kind()
        if kind:
            self.teach_current(kind)

    def import_prepared_images(self) -> None:
        kind = self._selected_kind()
        if kind is None:
            QMessageBox.information(self, "種類がありません", "取り込む種類を選んでください。")
            return
        name = self.scene_labels.name_of(kind)
        folder = QFileDialog.getExistingDirectory(
            self,
            f"「{name}」の画像フォルダ",
            self._dialog_dir(f"import_{kind}", Path(self._dialog_dir("import"))),
        )
        if not folder:
            return
        root = Path(folder)
        self._remember_dialog_dir(f"import_{kind}", root)
        self._remember_dialog_dir("import", root)
        self._apply_imported_images(self._import_from_folder(root, kind))

    def _image_files_in(self, folder: Path) -> list[Path]:
        return sorted(
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )

    def _kind_key_for_folder(self, name: str) -> str | None:
        text = name.strip()
        if not text:
            return None
        if text.lower() in {OTHER_KEY, "どちらでもない"}:
            return OTHER_KEY
        keys = self.scene_labels.keys_named(text)
        return keys[0] if keys else None

    def _import_from_folder(self, root: Path, fallback_kind: str) -> dict[str, int]:
        added: dict[str, int] = {}
        kind_folders = []
        if root.is_dir():
            for child in sorted(root.iterdir()):
                if not child.is_dir():
                    continue
                matched = self._kind_key_for_folder(child.name)
                if matched:
                    kind_folders.append((matched, child))
        targets: list[tuple[str, Path]] = kind_folders or [
            (self._kind_key_for_folder(root.name) or fallback_kind, root)
        ]
        if kind_folders:
            direct = [
                path
                for path in root.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            ]
            if direct:
                targets.append((fallback_kind, root))
        for kind, folder in targets:
            paths = (
                [
                    path
                    for path in folder.iterdir()
                    if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
                ]
                if folder == root and kind_folders
                else self._image_files_in(folder)
            )
            count = self.scene_labels.add_many(paths, kind)
            if count:
                added[kind] = added.get(kind, 0) + count
        return added

    def _apply_imported_images(self, added: dict[str, int]) -> None:
        self._update_buttons()
        if not added:
            QMessageBox.information(
                self,
                "画像がありません",
                "このフォルダに画像がありません。png や jpg の入ったフォルダを選んでください。",
            )
            return
        counts = self.scene_labels.counts()
        lines = [
            f"「{self.scene_labels.name_of(kind)}」に {count} 枚"
            for kind, count in added.items()
        ]
        now = "  /  ".join(
            f"{self.scene_labels.name_of(kind)} {counts.get(kind, 0)}" for kind in added
        )
        QMessageBox.information(self, "取り込みました", "\n".join(lines) + f"\nいま {now}")
        self.statusBar().showMessage(now, 5000)

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
            QMessageBox.information(self, "これは違う", "直す画像を、右の一覧から選んでください。")
            return
        if not self._current_is_found_scene():
            QMessageBox.information(
                self,
                "これは違う",
                "解析で見つかった画面のときだけ使えます。先に「解析」してください。",
            )
            return
        point = item.data(Qt.ItemDataRole.UserRole)
        if point is None:
            return
        detected = str(getattr(point, "kind", "") or "")
        kind = self._ask_correct_kind(detected, point)
        if not kind:
            return
        name = self.scene_labels.name_of(kind)
        self._remove_current_point()
        left = self.point_list.count()
        QMessageBox.information(
            self,
            "直しました",
            f"「{name}」として覚えました。\n残り {left} 枚です。",
        )
        self.statusBar().showMessage(f"「{name}」に直しました。残り {left} 枚", 5000)

    def _ask_correct_kind(self, detected: str, point) -> str | None:
        options: list[tuple[str, str]] = [(OTHER_KEY, self.scene_labels.name_of(OTHER_KEY))]
        for key in self.scene_labels.correct_keys():
            if key == detected:
                continue
            options.append((key, self.scene_labels.name_of(key)))
        dialog = QDialog(self)
        dialog.setWindowTitle("これは違う")
        dialog.setModal(True)
        dialog.setMinimumWidth(380)
        dialog.setMinimumHeight(320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("では、どれですか？"))
        kind_list = QListWidget()
        for key, name in options:
            row = QListWidgetItem(name)
            row.setData(Qt.ItemDataRole.UserRole, key)
            kind_list.addItem(row)
        kind_list.setCurrentRow(0)
        layout.addWidget(kind_list, 1)
        status = QLabel("保存しています…")
        status.setObjectName("hint")
        status.setVisible(False)
        layout.addWidget(status)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setVisible(False)
        layout.addWidget(progress)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        ok_btn.setText("これに直す")
        cancel_btn.setText("やめる")
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        chosen: list[str] = []
        saving = {"on": False}

        def restore() -> None:
            saving["on"] = False
            ok_btn.setEnabled(True)
            ok_btn.setText("これに直す")
            cancel_btn.setEnabled(True)
            kind_list.setEnabled(True)
            status.setVisible(False)
            progress.setVisible(False)
            QApplication.restoreOverrideCursor()

        def do_save(key: str) -> None:
            ok = self.teach_current(key)
            if ok:
                chosen.append(key)
                QApplication.restoreOverrideCursor()
                dialog.accept()
                return
            restore()

        def start_save() -> None:
            if saving["on"]:
                return
            current = kind_list.currentItem()
            if current is None:
                return
            key = str(current.data(Qt.ItemDataRole.UserRole) or "")
            if not key:
                return
            saving["on"] = True
            ok_btn.setEnabled(False)
            ok_btn.setText("保存しています…")
            cancel_btn.setEnabled(False)
            kind_list.setEnabled(False)
            status.setVisible(True)
            progress.setVisible(True)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            ok_btn.repaint()
            progress.repaint()
            status.repaint()
            QTimer.singleShot(0, lambda: do_save(key))

        ok_btn.clicked.connect(start_save)
        kind_list.itemDoubleClicked.connect(lambda *_: start_save())
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return chosen[0] if chosen else None

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
        self._mark_incomplete_items()
        self._update_buttons()
        self._refresh_info_pane()
        return removed

    def _remove_current_point(self) -> None:
        row = self.point_list.currentRow()
        item = self.point_list.takeItem(row)
        del item
        if self.point_list.count():
            self.point_list.setCurrentRow(min(row, self.point_list.count() - 1))
        self._mark_incomplete_items()
        self._update_buttons()
        self._refresh_info_pane()

    def start_scene_train(self) -> None:
        if isinstance(self.worker, SceneTrainWorker):
            self.cancel_scene_train()
            return
        if self.worker is not None:
            return
        if self.scene_labels.missing_for_train():
            self._show_scene_train_missing()
            return
        if not self._confirm_train(
            "画面の種類を学習します",
            "解析で使う画面の種類を学習します。\n"
            "コインの数字の学習ではありません。\n\n"
            + self._scene_train_summary()
            + "\n\n始めますか？",
            seconds=self._estimate_scene_train_seconds(),
        ):
            return
        self._begin_scene_train()

    def start_both_train(self) -> None:
        if self._train_both and isinstance(self.worker, SceneTrainWorker):
            self.cancel_scene_train()
            return
        if self._train_both and isinstance(self.worker, DigitTrainWorker):
            self._interrupt_digit_train()
            return
        if self.worker is not None:
            return
        missing = self.scene_labels.missing_for_train()
        counts = digit_train_counts()
        digit_count = counts["coin"] + counts["result_coin"]
        digit_short = counts["coin"] < MIN_DIGIT_SAMPLES and counts["result_coin"] < MIN_DIGIT_SAMPLES
        if missing or digit_short:
            parts = []
            if missing:
                parts.append(f"画面の種類はそれぞれ {MIN_SCENE_SAMPLES} 枚以上必要です。\n" + "\n".join(missing))
            if digit_short:
                parts.append(
                    f"コイン数字の学習には {MIN_DIGIT_SAMPLES} 枚以上必要です。"
                    f"いま coin {counts['coin']} 枚、result {counts['result_coin']} 枚です。"
                )
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Information)
            box.setWindowTitle("まだ足りません")
            box.setText("\n\n".join(parts))
            import_btn = None
            other_count = self.scene_labels.counts().get(OTHER_KEY, 0)
            if missing and other_count < MIN_SCENE_SAMPLES:
                import_btn = box.addButton("どちらでもない画像を取り込む", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("OK", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if import_btn is not None and box.clickedButton() is import_btn:
                index = self.kind_combo.findData(OTHER_KEY)
                if index >= 0:
                    self.kind_combo.setCurrentIndex(index)
                self.import_prepared_images()
            return
        scene_seconds = self._estimate_scene_train_seconds()
        digit_seconds = self._estimate_digit_train_seconds(digit_count)
        if not self._confirm_train(
            "上の2つを続けて学習します",
            "上の「学習する」と「コイン数字を学習する」を、続けて実行します。新しい学習ではありません。\n\n"
            "「学習する」は画面の種類です。GO、result、item、timeup など、今どの画面かを見分けます。\n"
            "「コイン数字を学習する」は、コインの緑枠の位置と、その中の数字です。\n\n"
            "ここの画面は、緑のコイン枠ではありません。解析で使う画面の種類のことです。\n"
            "緑の枠だけなら「コイン数字を学習する」と同じです。種類の学習も一緒にやりたいときの一括です。\n\n"
            "【画面の種類】\n"
            + self._scene_train_summary()
            + f"\n\n【コインの枠と数字】\ncoin {counts['coin']} 枚、result {counts['result_coin']} 枚\n\n始めますか？",
            seconds=scene_seconds + digit_seconds,
        ):
            return
        self._train_both = True
        self._both_scene_metrics = None
        self._begin_scene_train()

    def _scene_train_summary(self) -> str:
        counts = self.scene_labels.counts()
        lines = [
            f"{self.scene_labels.name_of(key)}  {counts.get(key, 0)} 枚"
            for key in self.scene_labels.train_classes()
        ]
        skip = self.scene_labels.idle_keys()
        extra = ""
        if skip:
            extra = (
                "\n\nいまは使いません: "
                + "、".join(self.scene_labels.name_of(key) for key in skip)
            )
        hidden_trained = [
            self.scene_labels.name_of(key)
            for key in self.scene_labels.train_classes()
            if key in set(self.scene_labels.hidden_keys())
        ]
        if hidden_trained:
            extra += (
                "\n学習しますが、解析結果には出しません: "
                + "、".join(hidden_trained)
            )
        return "\n".join(lines) + extra

    def _show_scene_train_missing(self) -> None:
        missing = self.scene_labels.missing_for_train()
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

    def _begin_scene_train(self) -> None:
        self.progress.setVisible(True)
        self.progress.setRange(0, SCENE_EPOCHS)
        self.progress.setValue(0)
        self._scene_train_started_at = time.perf_counter()
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
        if self._train_both:
            self.both_train_btn.setEnabled(False)
            self.both_train_btn.setText("中止しています…")
        self.statusBar().showMessage("学習を中止しています")

    def on_scene_trained(self, metrics: dict) -> None:
        self.progress.setVisible(False)
        self._train_fx.stop()
        self._fit_preview()
        self._clear_worker()
        acc = float(metrics.get("acc") or 0)
        samples = int(metrics.get("samples") or 0)
        self._remember_train_duration("scene", samples, SCENE_EPOCHS, 8, self._scene_train_started_at)
        self._scene_train_started_at = None
        if self._train_both:
            self._both_scene_metrics = metrics
            counts = digit_train_counts()
            if counts["coin"] < MIN_DIGIT_SAMPLES and counts["result_coin"] < MIN_DIGIT_SAMPLES:
                self._train_both = False
                self._both_scene_metrics = None
                self._update_buttons()
                QMessageBox.information(
                    self,
                    "学習完了",
                    f"画面の種類を {samples} 枚で学習しました。精度 {acc:.0%}\n"
                    f"コイン数字は {MIN_DIGIT_SAMPLES} 枚以上必要です。"
                    f"いま coin {counts['coin']} 枚、result {counts['result_coin']} 枚です。",
                )
                self.statusBar().showMessage(f"画面を学習しました  精度 {acc:.0%}", 5000)
                return
            self._update_buttons()
            self.statusBar().showMessage("画面を学習しました。続けてコイン数字を学習します")
            self._begin_digit_train()
            return
        self._update_buttons()
        QMessageBox.information(
            self,
            "学習完了",
            f"{samples} 枚で学習しました。精度 {acc:.0%}\n「解析」が使えます。探す種類は上の枠に出ています。",
        )
        self.statusBar().showMessage(f"学習しました  精度 {acc:.0%}", 5000)

    def on_scene_finished(self, paths: list[str]) -> None:
        points = getattr(self.worker, "found_points", []) if self.worker is not None else []
        names = getattr(self.worker, "search_names", "") if self.worker is not None else ""
        self.progress.setVisible(False)
        self._clear_worker()
        batch = self._batch_extract
        if batch:
            self._remember_current_video_rate()
        else:
            self._finish_extract_elapsed(remember=True)
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
            self._mark_incomplete_items()
            self._fit_point_list()
            QTimer.singleShot(0, self._fit_point_list)
        else:
            self.point_list.blockSignals(True)
            self.point_list.clear()
            self.point_list.blockSignals(False)
            self._preview_opened_video()
        self._update_buttons()
        self._refresh_info_pane(read_coins=bool(points))
        if batch:
            self._batch_results.append(self._batch_result_line(len(points), hidden_hits))
            if self._video_index + 1 < len(self._video_queue):
                QTimer.singleShot(0, self._continue_batch_extract)
                return
            self._finish_batch_extract()
            return
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
            "間違っていたら「これは違う」で正しい種類を選んでください。\n"
            "直したあと「学習する」と、次から精度が上がります。",
        )
        self.statusBar().showMessage(f"{len(points)} 枚見つかりました。間違いは「これは違う」", 6000)

    def _plain_coin_join(self, box_key: str) -> str:
        points = [
            point
            for point in self._list_points()
            if self._coin_box_key_for_point(point) == box_key
        ]
        numbers = self._coin_numbers(points, box_key)
        if not numbers:
            return "—"
        return "、".join(str(number) for _seconds, number in numbers)

    def _batch_result_line(self, found: int, hidden_hits: list) -> str:
        name = self.info.path.name if self.info is not None else "動画"
        if found <= 0:
            extra = ""
            if hidden_hits:
                extra = "（結果に出さない種類のみ）"
            return f"{name}  見つかりません{extra}"
        return (
            f"{name}  {found}枚\n"
            f"  GO→TIME UP  {self.go_timeup_value.text()}\n"
            f"  使用ツム  {self._plain_tsum_join()}\n"
            f"  アイテム消費  {self._plain_item_cost_join()}\n"
            f"  coin  {self._plain_coin_join('coin')}\n"
            f"  coin から引いた  {self.play_net_value.text()}（1分あたり {self.play_per_min_value.text()}）\n"
            f"  result  {self._plain_coin_join('result_coin')}\n"
            f"  result から引いた  {self.result_net_value.text()}（1分あたり {self.result_per_min_value.text()}）"
        )

    def _plain_item_cost_join(self) -> str:
        parts: list[str] = []
        for point in self._list_points():
            if not self._is_item_point(point):
                continue
            cache_key = self._item_cache_key(point)
            if cache_key not in self._item_used_cache:
                continue
            used = set(self._item_used_cache.get(cache_key) or [])
            parts.append(f"{item_coin_cost(used):,}")
        if not parts:
            return "—"
        return "、".join(parts)

    def _plain_tsum_join(self) -> str:
        names: list[str] = []
        for point in self._list_points():
            if not self._is_item_point(point):
                continue
            name = shown_tsum_name(self._item_tsum_cache.get(self._item_cache_key(point), ""))
            if name:
                names.append(name)
        if not names:
            return "—"
        return "、".join(names)

    def _continue_batch_extract(self) -> None:
        if not self._batch_extract:
            self._finish_extract_elapsed()
            return
        self._video_index += 1
        if self._video_index >= len(self._video_queue):
            self._finish_batch_extract()
            return
        path = self._video_queue[self._video_index]
        if not self.load_video(path, confirm_recent=False, keep_queue=True):
            self._batch_results.append(f"{path.name}  開けませんでした")
            QTimer.singleShot(0, self._continue_batch_extract)
            return
        keys = set(self.scene_labels.extract_keys()) | set(self.scene_labels.hidden_keys())
        self._start_kind_extract(keys or None, self.scene_labels.extract_names())

    def _finish_batch_extract(self) -> None:
        self._batch_extract = False
        self._finish_extract_elapsed()
        self._update_buttons()
        body = "\n\n".join(self._batch_results) or "結果がありません。"
        QMessageBox.information(
            self,
            "まとめて解析しました",
            f"{len(self._batch_results)} 本を解析しました。最後の動画の結果を表示しています。\n\n{body}",
        )
        self.statusBar().showMessage(
            f"{len(self._batch_results)} 本を解析しました。最後の動画を表示しています。",
            8000,
        )

    def on_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(current)
        if isinstance(self.worker, SceneExtractWorker):
            self._extract_progress = (current, max(total, 1))
            self._refresh_analysis_estimate()
        if isinstance(self.worker, SceneTrainWorker):
            self._train_fx.set_progress(current, total, name)
        prefix = ""
        queue_total = len(self._video_queue)
        if self._batch_extract and queue_total > 1:
            prefix = f"{self._video_index + 1}/{queue_total}  "
        self.statusBar().showMessage(prefix + name)
        QApplication.processEvents()

    def on_finished(self, paths: list[str]) -> None:
        self._clear_worker()
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

    def _format_extract_elapsed(self, seconds: float) -> str:
        elapsed = max(0, int(seconds))
        hours, rest = divmod(elapsed, 3600)
        minutes, secs = divmod(rest, 60)
        if hours:
            return f"{hours}時間{minutes:02d}分{secs:02d}秒"
        return f"{minutes:02d}分{secs:02d}秒"

    def _cuda_available(self) -> bool:
        if self._cuda_ready is None:
            try:
                import torch

                self._cuda_ready = bool(torch.cuda.is_available())
            except Exception:
                self._cuda_ready = False
        return self._cuda_ready

    def _train_batch_count(self, samples: int, batch_size: int) -> int:
        count = max(int(samples), 1)
        size = max(int(batch_size), 1)
        return max(1, math.ceil(count / min(size, count)))

    def _train_batch_rate(self, key: str, default: float) -> float:
        try:
            rate = float(self._settings.value(f"train_sec_per_batch/{key}", default) or default)
        except (TypeError, ValueError):
            rate = default
        return min(max(rate, 0.05), 20.0)

    def _estimate_train_seconds(
        self, key: str, samples: int, epochs: int, batch_size: int, overhead: float, default_rate: float
    ) -> float:
        batches = self._train_batch_count(samples, batch_size)
        return max(overhead + epochs * batches * self._train_batch_rate(key, default_rate), 5.0)

    def _scene_train_sample_count(self) -> int:
        allowed = set(self.scene_labels.train_classes())
        return sum(1 for item in self.scene_labels.items() if item["kind"] in allowed)

    def _estimate_scene_train_seconds(self) -> float:
        cuda = self._cuda_available()
        return self._estimate_train_seconds(
            "scene",
            self._scene_train_sample_count(),
            SCENE_EPOCHS,
            8,
            18.0 if cuda else 8.0,
            0.28 if cuda else 2.0,
        )

    def _estimate_digit_train_seconds(self, count: int | None = None) -> float:
        cuda = self._cuda_available()
        return self._estimate_train_seconds(
            "digit",
            count if count is not None else digit_teaching_count(),
            DIGIT_EPOCHS + BOX_EPOCHS,
            4,
            8.0 if cuda else 4.0,
            0.22 if cuda else 1.5,
        )

    def _remember_train_duration(
        self,
        key: str,
        samples: int,
        epochs: int,
        batch_size: int,
        started_at: float | None,
    ) -> None:
        if started_at is None:
            return
        elapsed = time.perf_counter() - started_at
        if elapsed < 3:
            return
        batches = self._train_batch_count(samples, batch_size)
        work = max(epochs * batches, 1)
        overhead = 12.0 if key == "scene" else 5.0
        observed = (elapsed - overhead) / work
        if not 0.05 <= observed <= 20.0:
            return
        default = 0.28 if key == "scene" else 0.22
        rate = 0.55 * self._train_batch_rate(key, default) + 0.45 * observed
        self._settings.setValue(f"train_sec_per_batch/{key}", rate)

    def _analysis_rate(self) -> float:
        try:
            rate = float(self._settings.value("analysis_sec_per_video_sec", 0.6) or 0.6)
        except (TypeError, ValueError):
            rate = 0.6
        return min(max(rate, 0.15), 4.0)

    def _remember_analysis_rate(self, elapsed: float) -> None:
        if self.info is None or self.info.duration < 3:
            return
        observed = elapsed / self.info.duration
        if not 0.1 <= observed <= 5.0:
            return
        rate = 0.55 * self._analysis_rate() + 0.45 * observed
        self._settings.setValue("analysis_sec_per_video_sec", rate)

    def _predicted_analysis_seconds(self) -> float | None:
        duration = self._remaining_queue_duration(include_current=True)
        if duration is None:
            return None
        return max(duration * self._analysis_rate(), 3.0)

    def _remaining_queue_duration(self, include_current: bool) -> float | None:
        if self.info is None and not self._video_queue:
            return None
        total = 0.0
        current_key = self._path_key(self.info.path) if self.info is not None else ""
        seen_current = self.info is None
        if include_current and self.info is not None:
            total += self.info.duration
        for path in self._video_queue:
            key = self._path_key(path)
            if not seen_current:
                if key == current_key:
                    seen_current = True
                continue
            total += self._cache_video_duration(path)
        if total <= 0 and self.info is None:
            return None
        return total

    def _refresh_analysis_estimate(self) -> None:
        started = self._extract_started_at
        if started is None:
            predicted = self._predicted_analysis_seconds()
            if predicted is None:
                self.estimate_value.setText("—")
                return
            self.estimate_value.setText(f"約{self._format_extract_elapsed(predicted)}")
            return
        elapsed = max(0.0, time.perf_counter() - started)
        current, total = self._extract_progress
        video_started = self._video_extract_started_at or started
        video_elapsed = max(0.0, time.perf_counter() - video_started)
        current_remaining = 0.0
        if self.info is not None:
            current_remaining = max(0.0, self.info.duration * self._analysis_rate() - video_elapsed)
            if current >= 8 and total > 0:
                current_remaining = max(0.0, video_elapsed * total / current - video_elapsed)
        others = self._remaining_queue_duration(include_current=False) or 0.0
        remaining = current_remaining + others * self._analysis_rate()
        predicted = elapsed + remaining
        self.estimate_value.setText(
            f"約{self._format_extract_elapsed(predicted)}\n残り {self._format_extract_elapsed(remaining)}"
        )

    def _tick_extract_elapsed(self) -> None:
        started = self._extract_started_at
        if started is None:
            return
        self.elapsed_value.setText(self._format_extract_elapsed(time.perf_counter() - started))
        self._refresh_analysis_estimate()

    def _remember_current_video_rate(self) -> None:
        started = self._video_extract_started_at
        self._video_extract_started_at = None
        if started is None:
            return
        self._remember_analysis_rate(time.perf_counter() - started)

    def _finish_extract_elapsed(self, remember: bool = False) -> None:
        self._elapsed_timer.stop()
        started = self._extract_started_at
        self._extract_started_at = None
        if remember:
            self._remember_current_video_rate()
        else:
            self._video_extract_started_at = None
        if started is None:
            self._refresh_analysis_estimate()
            return
        elapsed = max(0.0, time.perf_counter() - started)
        self.elapsed_value.setText(self._format_extract_elapsed(elapsed))
        self._refresh_analysis_estimate()

    def on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self._finish_extract_elapsed()
        self._train_fx.stop()
        self._fit_preview()
        self._clear_worker()
        self._train_both = False
        self._both_scene_metrics = None
        self._scene_train_started_at = None
        self._digit_train_started_at = None
        self._batch_extract = False
        self._update_buttons()
        if "中止" in message:
            title = "解析を中止" if "解析" in message else "学習を中止"
            QMessageBox.information(self, title, "中止しました。")
            self.statusBar().showMessage("中止しました", 4000)
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
            self._open_videos(videos)
            event.acceptProposedAction()
            return
        kind = self._selected_kind()
        folders = [path for path in paths if path.is_dir()]
        images = [path for path in paths if path.suffix.lower() in IMAGE_EXTENSIONS]
        if folders:
            if kind is None:
                QMessageBox.information(self, "種類がありません", "取り込む種類を選んでください。")
                event.ignore()
                return
            added: dict[str, int] = {}
            for folder in folders:
                for key, count in self._import_from_folder(folder, kind).items():
                    added[key] = added.get(key, 0) + count
            self._apply_imported_images(added)
            event.acceptProposedAction()
            return
        if images and kind:
            added = self.scene_labels.add_many(images, kind)
            self._apply_imported_images({kind: added} if added else {})
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
