from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from app.bluestacks import capture_screen_path, swipe_path
from app.intro import Stopped, _check_stop, _play_button, _slow_tap
from app.trainer_bridge import load_play_tools

MIN_CHAIN = 3
SETTLE_WAIT = 1.4
HOME_TSUM_MAX = 6

StatusFn = Callable[[str], None]


class PlayWorker(QThread):
    failed = Signal(str)
    stopped = Signal()
    status = Signal(str)

    def __init__(self, stop: Event, parent=None) -> None:
        super().__init__(parent)
        self._stop = stop

    def run(self) -> None:
        try:
            run_play(self.status.emit, self._stop)
        except Stopped:
            self.stopped.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


def run_play(report: StatusFn | None, stop: Event | None) -> None:
    def say(text: str) -> None:
        if report is not None:
            report(text)

    say("モデルを読み込み中")
    try:
        predictor, longest = load_play_tools()
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "画面認識に必要なライブラリがありません。画面認識アプリと同じ Python で起動してください。"
        ) from exc
    if getattr(predictor, "piece_model", None) is None:
        raise RuntimeError("ツムの〇モデルがありません。画面認識アプリで学習してください。")

    say("プレイを開始します")
    while True:
        _check_stop(stop)
        try:
            path = capture_screen_path()
            image = QImage(str(path))
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.8, stop)
            continue
        boxes = predictor.predict_all(path)
        game = boxes.get("game")
        pieces = predictor.predict_pieces(path, game)
        tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        chain = longest(pieces)
        if len(chain) >= MIN_CHAIN:
            say(f"チェーン {len(chain)}")
            points = [(int(piece["x"]), int(piece["y"])) for piece in chain]
            swipe_path(points)
            _sleep_stop(SETTLE_WAIT, stop)
            continue
        play = None if image.isNull() else _play_button(image)
        if play is not None and len(tsums) < HOME_TSUM_MAX:
            say("プレイをクリックします")
            _slow_tap(play.center().x(), play.center().y())
            _sleep_stop(1.0, stop)
            continue
        say("盤面を待っています")
        _sleep_stop(0.6, stop)


def _sleep_stop(seconds: float, stop: Event | None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        _check_stop(stop)
        time.sleep(min(0.2, max(0.0, end - time.time())))
