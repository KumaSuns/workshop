from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QStandardPaths, Qt, QTimer, QEvent
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.bluestacks import capture_play_frame, halt_input, start_tsum, tsum_is_running
from app.intro import IntroWorker
from app.paths import APP_ROOT
from app.play import (
    PlayWorker,
    read_kind_count,
    register_used_tsum_id,
    save_used_tsum_teach,
    used_tsum_names,
)

APP_NAME = "ツムツム オートプレイ"
_STOP_HOTKEY = 1
_WM_HOTKEY = 0x0312
_VK_Q = 0x51
_MOD_NOREPEAT = 0x4000
_NOT_CHARM_TSUMS = frozenset(
    {
        "ナミネ",
        "namine",
        "ガジェット",
        "gadget",
        "cバズ",
        "c_bazu",
        "キャプテンライトイヤー",
        "戴冠式エルサ",
        "coronation_elsa",
    }
)


def _is_not_charm_tsum(name: str) -> bool:
    raw = " ".join((name or "").split())
    if not raw:
        return False
    return raw in _NOT_CHARM_TSUMS or raw.casefold() in _NOT_CHARM_TSUMS


class DebugWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("デバッグ")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self._gauges = QLabel("スキル  —    フィーバー  —")
        self._gauges.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._fever_mark = QLabel("FEVER")
        self._fever_mark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._set_fever_mark(False)
        row.addWidget(self._gauges, 1)
        row.addWidget(self._fever_mark, 0)
        layout.addLayout(row)
        self._preview = QLabel("なぞる経路")
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(280)
        self._preview.setStyleSheet("background:#111; color:#888;")
        layout.addWidget(self._preview)
        self._used_tsum = QLabel("使用ツム  —")
        self._used_tsum.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._used_tsum)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(400)
        layout.addWidget(self._log)
        self.resize(420, 720)
        self._on_stop = None

    def set_preview(self, image: QImage) -> None:
        if image.isNull():
            return
        width = max(200, self._preview.width())
        pix = QPixmap.fromImage(image)
        self._preview.setPixmap(
            pix.scaled(
                width,
                max(240, self._preview.height()),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def set_gauges(self, skill, fever) -> None:
        skill_s = "—" if skill is None else f"{float(skill):.2f}"
        fever_s = "—" if fever is None else f"{float(fever):.2f}"
        self._gauges.setText(f"スキル  {skill_s}    フィーバー  {fever_s}")
        on = fever is not None and float(fever) >= 0.25
        self._set_fever_mark(on)

    def _set_fever_mark(self, on: bool) -> None:
        if on:
            self._fever_mark.setStyleSheet("color:#FF2A2A; font-weight:700;")
        else:
            self._fever_mark.setStyleSheet("color:#888888; font-weight:400;")

    def set_used_tsum(self, name: str) -> None:
        shown = " ".join((name or "").split()) or "—"
        self._used_tsum.setText(f"使用ツム  {shown}")

    def append(self, text: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._log.appendPlainText(f"{now}  {text}")
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())
        if text.startswith("使用ツム "):
            self.set_used_tsum(text[len("使用ツム ") :])

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Q and not event.isAutoRepeat() and self._on_stop:
            self._on_stop()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        icon = self._ensure_app_icon()
        if icon is not None:
            self.setWindowIcon(QIcon(str(icon)))
        root = QWidget()
        layout = QVBoxLayout(root)
        self.capture_btn = QPushButton("消す前の盤面を取り込む")
        self.capture_btn.setCheckable(True)
        self.capture_btn.toggled.connect(self._on_capture_toggled)
        layout.addWidget(self.capture_btn)
        self.shot_btn = QPushButton("キャプチャー")
        self.shot_btn.clicked.connect(self.on_capture_screen)
        layout.addWidget(self.shot_btn)
        self.play_btn = QPushButton("PLAY")
        self.play_btn.clicked.connect(self.on_play)
        layout.addWidget(self.play_btn)
        self.now_btn = QPushButton("今すぐプレイ")
        self.now_btn.clicked.connect(self.on_play_now)
        layout.addWidget(self.now_btn)
        self.loop_btn = QPushButton("連続プレイ")
        self.loop_btn.clicked.connect(self.on_loop_play)
        layout.addWidget(self.loop_btn)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.on_stop)
        layout.addWidget(self.stop_btn)
        self.shortcut_btn = QPushButton("起動アイコン作成")
        self.shortcut_btn.clicked.connect(self.create_launch_shortcut)
        layout.addWidget(self.shortcut_btn)
        self.remote_btn = QPushButton("新アプリを起動")
        self.remote_btn.clicked.connect(self._start_remote_app)
        layout.addWidget(self.remote_btn)
        self.tsum_btn = QPushButton("ツムツムを起動")
        self.tsum_btn.clicked.connect(self._start_tsum_app)
        layout.addWidget(self.tsum_btn)
        self.shutdown_btn = QPushButton("PCをシャットダウン")
        self.shutdown_btn.clicked.connect(self._confirm_shutdown)
        layout.addWidget(self.shutdown_btn)
        self.reboot_btn = QPushButton("PCを再起動")
        self.reboot_btn.clicked.connect(self._confirm_reboot)
        layout.addWidget(self.reboot_btn)
        self.status_label = QLabel("待機中")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)
        self._stop = threading.Event()
        self._save_boards = threading.Event()
        self._loop_play = False
        self._intro: IntroWorker | None = None
        self._play: PlayWorker | None = None
        self._selected_used_tsum = ""
        self._debug = DebugWindow()
        self._debug._on_stop = self.on_stop
        self._placed = False
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._front_timer = QTimer(self)
        self._front_timer.setInterval(800)
        self._front_timer.timeout.connect(self._keep_front)
        self._front_timer.start()
        self._debug.append("待機中")

    def _on_capture_toggled(self, on: bool) -> None:
        if on:
            self._save_boards.set()
        else:
            self._save_boards.clear()

    def on_capture_screen(self) -> None:
        try:
            image = capture_play_frame()
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "キャプチャー", str(exc))
            return
        if image is None or image.isNull():
            QMessageBox.warning(self, "キャプチャー", "画面を取れませんでした。")
            return
        clip = QApplication.clipboard()
        if clip is None:
            QMessageBox.warning(self, "キャプチャー", "クリップボードにコピーできませんでした。")
            return
        clip.setImage(image)
        self._debug.set_preview(image)
        self._set_status("キャプチャーしました。貼り付けできます")

    def on_play(self) -> None:
        self._begin_play(loop=False)

    def on_loop_play(self) -> None:
        self._begin_play(loop=True)

    def _begin_play(self, *, loop: bool) -> None:
        if self._is_busy():
            return
        self._loop_play = loop
        self._stop.clear()
        self._set_running(True)
        self._set_status("連続プレイ" if loop else "PLAY")
        if not tsum_is_running():
            desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
            try:
                start_tsum(desktop or "")
            except Exception as exc:  # noqa: BLE001
                self._set_running(False)
                QMessageBox.critical(self, "起動できませんでした", str(exc))
                return
            self._set_status("起動しています")
            self._start_intro()
            return
        if loop:
            self._start_play(start_match=True, ask_kinds=True, loop=True)
            return
        self._start_play(loop=False)

    def on_play_now(self) -> None:
        if self._is_busy():
            return
        if not tsum_is_running():
            QMessageBox.information(self, "今すぐプレイ", "ツムツムが起動していません。")
            return
        self._stop.clear()
        self._set_running(True)
        self._set_status("今すぐプレイ")
        self._start_play(start_match=True, ask_kinds=True, loop=False)

    def _ask_kind_count(self) -> int | None:
        guess = read_kind_count()
        if guess in (4, 5):
            return guess
        box = QMessageBox(self)
        box.setWindowTitle("今すぐプレイ")
        box.setText("種類は何種類ですか？")
        four = box.addButton("4種類", QMessageBox.ButtonRole.AcceptRole)
        five = box.addButton("5種類", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(five)
        box.exec()
        clicked = box.clickedButton()
        if clicked is four:
            return 4
        if clicked is five:
            return 5
        return None

    def _ask_charm_tsum(self) -> bool | None:
        box = QMessageBox(self)
        box.setWindowTitle("今すぐプレイ")
        box.setText("チャームツムですか？")
        box.setInformativeText("使うと種類が1つ減ります。")
        yes = box.addButton("はい", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("いいえ", QMessageBox.ButtonRole.NoRole)
        box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        clicked = box.clickedButton()
        if clicked is yes:
            return True
        if clicked is no:
            return False
        return None

    def on_stop(self) -> None:
        if not self._is_busy():
            return
        if self._stop.is_set():
            halt_input()
            return
        self._stop.set()
        if self._intro is not None:
            self._intro.requestInterruption()
        if self._play is not None:
            self._play.requestInterruption()
        halt_input()
        self._set_status("停止しています")

    def _is_busy(self) -> bool:
        intro_on = self._intro is not None and self._intro.isRunning()
        play_on = self._play is not None and self._play.isRunning()
        return intro_on or play_on

    def _set_running(self, running: bool) -> None:
        self.play_btn.setEnabled(not running)
        self.now_btn.setEnabled(not running)
        self.loop_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        if running:
            self._front_timer.stop()
            self._debug.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
            self._debug.show()
            self.show()
            self._register_stop_hotkey()
        else:
            self._unregister_stop_hotkey()
            self._debug.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self._debug.show()
            self.show()
            self._front_timer.start()
            self._keep_front()

    def _start_intro(self) -> None:
        self._intro = IntroWorker(self._stop, self)
        self._intro.status.connect(self._set_status)
        self._intro.succeeded.connect(self._on_intro_ok)
        self._intro.failed.connect(self._on_intro_fail)
        self._intro.stopped.connect(self._on_stopped)
        self._keep_front()
        self._intro.start()

    def _start_play(
        self,
        start_match: bool = False,
        kind_count: int | None = None,
        loop: bool | None = None,
        ask_kinds: bool = False,
    ) -> None:
        if loop is None:
            loop = self._loop_play
        self._selected_used_tsum = ""
        self._play = PlayWorker(
            self._stop,
            self,
            start_match=start_match,
            kind_count=kind_count,
            save_boards=self._save_boards.is_set,
            loop=loop,
            ask_kinds=ask_kinds,
        )
        self._play.status.connect(self._set_status)
        self._play.preview.connect(self._debug.set_preview)
        self._play.gauges.connect(self._debug.set_gauges)
        self._play.failed.connect(self._on_play_fail)
        self._play.stopped.connect(self._on_stopped)
        self._play.completed.connect(self._on_play_done)
        if ask_kinds:
            self._play.need_kinds.connect(self._on_need_kinds)
            self._play.need_used_tsum.connect(self._on_need_used_tsum)
        self._play.start()

    def _on_need_used_tsum(self, guess: str, path: str, pick_only: bool) -> None:
        play = self._play
        if play is None:
            return
        screen = Path(path) if path else None
        name = self._confirm_used_tsum(guess, screen, pick_only)
        if name is None:
            play.provide_used_tsum(None)
            self.on_stop()
            return
        self._selected_used_tsum = name
        play.provide_used_tsum(name)

    def _confirm_used_tsum(
        self, guess: str, path: Path | None, pick_only: bool = False
    ) -> str | None:
        if pick_only:
            return self._choose_used_tsum(path)
        box = QMessageBox(self)
        box.setWindowTitle("今すぐプレイ")
        box.setWindowModality(Qt.WindowModality.ApplicationModal)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        if guess:
            box.setText(f"使用ツムは {guess} ですか？")
            yes = box.addButton("はい", QMessageBox.ButtonRole.AcceptRole)
        else:
            box.setText("使用ツムが分かっていません。")
            yes = None
        no = box.addButton("いいえ", QMessageBox.ButtonRole.NoRole)
        new = box.addButton("新規", QMessageBox.ButtonRole.ActionRole)
        cancel = box.addButton("キャンセル", QMessageBox.ButtonRole.RejectRole)
        no.setAutoDefault(False)
        new.setAutoDefault(False)
        cancel.setAutoDefault(False)
        if yes is not None:
            yes.setAutoDefault(True)
            yes.setDefault(True)
            box.setDefaultButton(yes)

        class _EnterYes(QObject):
            def eventFilter(self, watched, event) -> bool:
                if event.type() != QEvent.Type.KeyPress or event.isAutoRepeat():
                    return False
                if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    return False
                if yes is None:
                    return False
                yes.click()
                return True

        filt = _EnterYes(box)
        app = QApplication.instance()
        box.installEventFilter(filt)
        if app is not None:
            app.installEventFilter(filt)
        box.raise_()
        box.activateWindow()
        if yes is not None:
            yes.setFocus()
        try:
            box.exec()
        finally:
            if app is not None:
                app.removeEventFilter(filt)
        clicked = box.clickedButton()
        if yes is not None and clicked is yes:
            return guess
        if clicked is no:
            return self._pick_used_tsum(guess, path)
        if clicked is new:
            return self._register_used_tsum(path)
        return None

    def _choose_used_tsum(self, path: Path | None) -> str | None:
        names = used_tsum_names()
        if not names:
            return self._register_used_tsum(path)
        dialog = QDialog(self)
        dialog.setWindowTitle("今すぐプレイ")
        dialog.setModal(True)
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("使用ツムはどれですか？"))
        name_list = QListWidget()
        for name in names:
            name_list.addItem(name)
        name_list.setCurrentRow(0)
        layout.addWidget(name_list, 1)
        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("これにします", QDialogButtonBox.ButtonRole.AcceptRole)
        new_btn = buttons.addButton("新規", QDialogButtonBox.ButtonRole.ActionRole)
        cancel_btn = buttons.addButton("やめる", QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)
        name_list.itemDoubleClicked.connect(lambda *_: dialog.accept())
        ok_btn.clicked.connect(dialog.accept)
        cancel_btn.clicked.connect(dialog.reject)
        new_btn.clicked.connect(lambda: dialog.done(2))
        result = dialog.exec()
        if result == 2:
            return self._register_used_tsum(path)
        if result != QDialog.DialogCode.Accepted:
            return None
        row = name_list.currentItem()
        if row is None:
            return None
        if path is not None and path.is_file():
            return self._save_used_tsum_choice(path, row.text(), None)
        return row.text()

    def _pick_used_tsum(self, guess: str, path: Path | None) -> str | None:
        names = [name for name in used_tsum_names() if name != guess]
        if not names:
            QMessageBox.information(
                self,
                "今すぐプレイ",
                "まだ種類がありません。「新規」で名前を付けてください。",
            )
            return self._register_used_tsum(path)
        dialog = QDialog(self)
        dialog.setWindowTitle("今すぐプレイ")
        dialog.setModal(True)
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("どれですか？"))
        name_list = QListWidget()
        for name in names:
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
            return None
        row = name_list.currentItem()
        if row is None:
            return None
        return self._save_used_tsum_choice(path, row.text(), None)

    def _register_used_tsum(self, path: Path | None) -> str | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("今すぐプレイ")
        dialog.setModal(True)
        dialog.setMinimumWidth(320)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("ツム名"))
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("ガジェット")
        layout.addWidget(name_edit)
        layout.addWidget(QLabel("フォルダ名"))
        dir_edit = QLineEdit()
        dir_edit.setPlaceholderText("Gadget")
        layout.addWidget(dir_edit)
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
        name_edit.returnPressed.connect(dialog.accept)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        name = " ".join(name_edit.text().split())
        folder_id = "".join(dir_edit.text().split())
        if not name:
            QMessageBox.information(self, "今すぐプレイ", "ツム名を入力してください。")
            return None
        if not folder_id:
            QMessageBox.information(self, "今すぐプレイ", "フォルダ名を入力してください。")
            return None
        return self._save_used_tsum_choice(path, name, folder_id)

    def _save_used_tsum_choice(
        self, path: Path | None, name: str, folder_id: str | None
    ) -> str | None:
        try:
            if path is not None and path.is_file():
                saved = save_used_tsum_teach(path, name, folder_id)
            elif folder_id:
                saved = register_used_tsum_id(name, folder_id)
            else:
                return name
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "保存できませんでした", str(exc))
            return None
        self._set_status(f"使用ツム {saved}")
        return saved

    def _on_need_kinds(self) -> None:
        play = self._play
        if play is None:
            return
        kinds = self._ask_kind_count()
        if kinds is None:
            play.provide_kinds(None)
            self.on_stop()
            return
        charm = False
        if not _is_not_charm_tsum(self._selected_used_tsum):
            asked = self._ask_charm_tsum()
            if asked is None:
                play.provide_kinds(None)
                self.on_stop()
                return
            charm = asked
        if charm:
            kinds = max(1, kinds - 1)
        play.provide_kinds(kinds)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self._debug.append(text)

    def _keep_front(self) -> None:
        self.raise_()
        if self._debug.isVisible():
            self._debug.raise_()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._debug.show()
        if self._placed:
            return
        self._placed = True
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        dbg = self._debug.frameGeometry()
        self._debug.move(area.right() - dbg.width() + 1, area.top())
        dbg = self._debug.frameGeometry()
        main = self.frameGeometry()
        self.move(max(area.left(), dbg.left() - main.width() - 40), dbg.top())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Q and not event.isAutoRepeat():
            self.on_stop()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Q:
            if not event.isAutoRepeat() and self._is_busy():
                self.on_stop()
                return True
        return super().eventFilter(watched, event)

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32":
            raw = bytes(eventType) if not isinstance(eventType, (bytes, bytearray)) else eventType
            if raw.startswith(b"windows_generic_MSG"):
                import ctypes
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == _WM_HOTKEY and int(msg.wParam) == _STOP_HOTKEY:
                    QTimer.singleShot(0, self.on_stop)
                    return True, 0
        return super().nativeEvent(eventType, message)

    def _register_stop_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        ctypes.windll.user32.RegisterHotKey(
            int(self.winId()), _STOP_HOTKEY, _MOD_NOREPEAT, _VK_Q
        )

    def _unregister_stop_hotkey(self) -> None:
        if sys.platform != "win32":
            return
        import ctypes

        ctypes.windll.user32.UnregisterHotKey(int(self.winId()), _STOP_HOTKEY)

    def closeEvent(self, event) -> None:
        self._unregister_stop_hotkey()
        self._debug.close()
        super().closeEvent(event)

    def _on_intro_ok(self) -> None:
        if self._stop.is_set():
            self._on_stopped()
            return
        if self._loop_play:
            self._start_play(start_match=True, ask_kinds=True, loop=True)
            return
        self._start_play(loop=False)

    def _on_intro_fail(self, message: str) -> None:
        self._set_running(False)
        self._set_status(message)
        QMessageBox.critical(self, "PLAY", message)

    def _on_play_fail(self, message: str) -> None:
        self._set_running(False)
        self._set_status(message)
        QMessageBox.critical(self, "PLAY", message)

    def _on_play_done(self) -> None:
        self._set_running(False)
        text = self.status_label.text()
        if "リトライ" in text:
            return
        if "コイン" not in text and text != "TIME UP":
            self._set_status("TIME UP")

    def _on_stopped(self) -> None:
        self._set_running(False)
        self._set_status("停止しました")

    def _start_remote_app(self) -> None:
        script = APP_ROOT.parent / "pc-web-remote" / "main.py"
        if not script.is_file():
            QMessageBox.critical(self, "新アプリを起動", "新アプリが見つかりませんでした。")
            return
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.Popen(
                [str(target), str(script)],
                cwd=str(script.parent),
                creationflags=flags,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "新アプリを起動", str(exc))
            return
        self._set_status("新アプリを起動しました")

    def _start_tsum_app(self) -> None:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        try:
            start_tsum(desktop or "")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "ツムツムを起動", str(exc))
            return
        self._set_status("ツムツムを起動しました")

    def _confirm_shutdown(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("PCをシャットダウン")
        box.setText("この PC をシャットダウンしますか？")
        yes = box.addButton("はい", QMessageBox.ButtonRole.YesRole)
        box.addButton("いいえ", QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(yes)
        box.exec()
        if box.clickedButton() is not yes:
            return
        self._run_shutdown("/s")

    def _confirm_reboot(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("PCを再起動")
        box.setText("この PC を再起動しますか？")
        yes = box.addButton("はい", QMessageBox.ButtonRole.YesRole)
        box.addButton("いいえ", QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(yes)
        box.exec()
        if box.clickedButton() is not yes:
            return
        self._run_shutdown("/r")

    def _run_shutdown(self, flag: str) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                ["shutdown", flag, "/t", "0"],
                check=False,
                capture_output=True,
                text=True,
                creationflags=flags,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "PC", str(exc))
            return
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "実行できませんでした").strip()
            QMessageBox.critical(self, "PC", err)

    def create_launch_shortcut(self) -> None:
        desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
        if not desktop:
            QMessageBox.warning(self, "デスクトップがありません", "デスクトップの場所が分かりませんでした。")
            return
        if sys.platform == "darwin":
            dest = self._create_macos_launch_shortcut(Path(desktop))
            QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{dest}")
            return
        lnk = Path(desktop) / f"{APP_NAME}.lnk"
        python = Path(sys.executable)
        pythonw = python.with_name("pythonw.exe")
        target = pythonw if pythonw.exists() else python
        script = APP_ROOT / "main.py"
        icon = self._ensure_app_icon()

        def ps_quote(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"

        icon_line = f"$s.IconLocation = {ps_quote(str(icon) + ',0')}" if icon else ""
        command = (
            "$ws = New-Object -ComObject WScript.Shell\n"
            f"$s = $ws.CreateShortcut({ps_quote(str(lnk))})\n"
            f"$s.TargetPath = {ps_quote(str(target))}\n"
            f"$s.Arguments = {ps_quote(chr(34) + str(script) + chr(34))}\n"
            f"$s.WorkingDirectory = {ps_quote(str(APP_ROOT))}\n"
            "$s.WindowStyle = 1\n"
            f"$s.Description = {ps_quote(APP_NAME)}\n"
            f"{icon_line}\n"
            "$s.Save()\n"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-STA", "-Command", command],
                check=False,
                capture_output=True,
                text=True,
                creationflags=flags,
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "アイコンを作れませんでした", str(exc))
            return
        if result.returncode != 0 or not lnk.exists():
            err = (result.stderr or result.stdout or "ショートカットを作れませんでした").strip()
            QMessageBox.critical(self, "アイコンを作れませんでした", err)
            return
        QMessageBox.information(self, "起動アイコン", f"デスクトップに作りました。\n{lnk}")

    def _create_macos_launch_shortcut(self, desktop: Path) -> Path:
        app_path = desktop / f"{APP_NAME}.app"
        contents = app_path / "Contents"
        macos_dir = contents / "MacOS"
        if app_path.exists():
            import shutil

            shutil.rmtree(app_path)
        macos_dir.mkdir(parents=True, exist_ok=True)
        launcher = macos_dir / "launch"
        launcher.write_text(
            "#!/bin/bash\n"
            f'cd "{APP_ROOT}"\n'
            f'exec "{sys.executable}" main.py\n',
            encoding="utf-8",
        )
        launcher.chmod(0o755)
        (contents / "Info.plist").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>CFBundleIdentifier</key><string>workshop.tsumtsum-autoplay</string>
  <key>CFBundleName</key><string>ツムツム オートプレイ</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
</dict>
</plist>
""",
            encoding="utf-8",
        )
        return app_path

    def _ensure_app_icon(self) -> Path | None:
        path = APP_ROOT / "app.ico"
        return path if path.exists() else None
