from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from tempfile import gettempdir
from threading import Event

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from app.bluestacks import capture_screen, capture_screen_path, swipe_path
from app.intro import (
    Stopped,
    _check_stop,
    _continue_button,
    _match_start_button,
    _play_button,
    _slow_tap,
)
from app.trainer_bridge import load_play_tools, save_erase_lesson

MIN_CHAIN = 3
SETTLE_WAIT = 0.12
BOARD_TSUMS = 8

StatusFn = Callable[[str], None]


class PlayWorker(QThread):
    failed = Signal(str)
    stopped = Signal()
    completed = Signal()
    status = Signal(str)

    def __init__(self, stop: Event, parent=None, start_match: bool = False) -> None:
        super().__init__(parent)
        self._stop = stop
        self._start_match = start_match

    def run(self) -> None:
        try:
            run_play(self.status.emit, self._stop, start_match=self._start_match)
        except Stopped:
            self.stopped.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit()


def run_play(report: StatusFn | None, stop: Event | None, start_match: bool = False) -> None:
    def say(text: str) -> None:
        if report is not None:
            report(text)

    say("モデルを読み込み中")
    try:
        predictor, candidates = load_play_tools()
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "画面認識に必要なライブラリがありません。画面認識アプリと同じ Python で起動してください。"
        ) from exc
    if getattr(predictor, "piece_model", None) is None:
        raise RuntimeError("ツムの〇モデルがありません。画面認識アプリで学習してください。")

    say("プレイを開始します")
    if start_match:
        _click_start_or_continue(say, stop)
    used_keys: list[frozenset[tuple[int, int]]] = []
    last_count = 0
    game = None
    timeup_hits = 0
    while True:
        _check_stop(stop)
        try:
            path = capture_screen_path()
            image = QImage(str(path))
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.4, stop)
            continue
        if _is_timeup(predictor, path):
            timeup_hits += 1
            if timeup_hits >= 2:
                say("TIME UP")
                return
        else:
            timeup_hits = 0
        if game is None:
            boxes = predictor.predict_all(path)
            game = boxes.get("game")
        _check_stop(stop)
        pieces = predictor.predict_pieces(path, game)
        tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        if len(tsums) < BOARD_TSUMS:
            boxes = predictor.predict_all(path)
            game = boxes.get("game")
            pieces = predictor.predict_pieces(path, None)
            tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        _check_stop(stop)
        if len(tsums) < BOARD_TSUMS:
            say(f"ツム {len(tsums)}体（盤面が少ない）")
            if _tap_start_or_continue(image, say, stop):
                continue
            play = None if image.isNull() else _play_button(image)
            if play is not None:
                say("プレイをクリックします")
                _slow_tap(play.center().x(), play.center().y())
                _sleep_stop(2.0, stop)
                continue
        if last_count > 0 and (
            len(tsums) <= last_count - MIN_CHAIN or len(tsums) >= last_count + 5
        ):
            used_keys.clear()
        last_count = len(tsums)
        chain = _pick_chain(pieces, candidates, used_keys, say)
        if chain:
            used_keys.append(_chain_key(chain))
            points = [(int(piece["x"]), int(piece["y"])) for piece in chain]
            cells = {(x // 24, y // 24) for x, y in points}
            route = " → ".join(f"{x},{y}" for x, y in points)
            say(f"ツム {len(tsums)}体 / チェーン {len(chain)}体")
            say(f"経路 {route}")
            if len(points) < MIN_CHAIN or len(cells) < MIN_CHAIN:
                say("同じ位置に重なっているので見送り")
                _sleep_stop(0.08, stop)
                continue
            say("なぞっています")
            _check_stop(stop)
            before_copy = Path(gettempdir()) / "tsum_autoplay_before.png"
            before_copy.write_bytes(Path(path).read_bytes())
            how = swipe_path(points, screen_w=image.width(), screen_h=image.height(), stop=stop)
            say(how)
            _check_stop(stop)
            if how not in {"なぞり失敗", "停止", "点が3未満", "ツムが近すぎる"}:
                try:
                    after = QImage(str(capture_screen_path()))
                except Exception:
                    after = QImage()
                if _save_play_lesson(
                    predictor, before_copy, image, after, game, pieces, chain
                ):
                    say("消えたツムを学習用に保存")
            _sleep_stop(SETTLE_WAIT, stop)
            continue
        say(f"ツム {len(tsums)}体 / なぞれる3体以上なし")
        _sleep_stop(0.08, stop)


def _is_timeup(predictor, path: Path) -> bool:
    predict = getattr(predictor, "predict_scene", None)
    if predict is None:
        return False
    try:
        name, score = predict(path)
    except Exception:
        return False
    return name == "timeup" and float(score) >= 0.55


def _sleep_stop(seconds: float, stop: Event | None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        _check_stop(stop)
        time.sleep(min(0.2, max(0.0, end - time.time())))


def _click_start_or_continue(say: StatusFn, stop: Event | None) -> None:
    deadline = time.time() + 12
    while time.time() < deadline:
        _check_stop(stop)
        try:
            image = capture_screen()
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.8, stop)
            continue
        if image.isNull():
            _sleep_stop(0.4, stop)
            continue
        if _tap_start_or_continue(image, say, stop):
            return
        say("スタートまたは続けるを待っています")
        _sleep_stop(0.35, stop)


def _tap_start_or_continue(image: QImage, say: StatusFn, stop: Event | None) -> bool:
    if image.isNull():
        return False
    start = _match_start_button(image)
    resume = _continue_button(image)
    if start is not None:
        say("スタートをクリックします")
        _slow_tap(start.center().x(), start.center().y())
        _sleep_stop(1.2, stop)
        return True
    if resume is not None:
        say("続けるをクリックします")
        _slow_tap(resume.center().x(), resume.center().y())
        _sleep_stop(1.2, stop)
        return True
    return False


def _pick_chain(
    pieces: list[dict[str, int]],
    candidates,
    used_keys: list[frozenset[tuple[int, int]]],
    say: StatusFn,
) -> list[dict[str, int]]:
    found = [chain for chain in candidates(pieces, 8) if len(chain) >= MIN_CHAIN]
    if found:
        say("候補 " + " / ".join(str(len(chain)) for chain in found))
    for chain in found:
        if _chain_too_similar(chain, used_keys):
            continue
        return chain
    if found:
        used_keys.clear()
        return found[0]
    return []


def _chain_key(chain: list[dict[str, int]]) -> frozenset[tuple[int, int]]:
    return frozenset(_chain_cells(chain))


def _chain_cells(chain: list[dict[str, int]]) -> set[tuple[int, int]]:
    return {(int(piece["x"]) // 24, int(piece["y"]) // 24) for piece in chain}


def _chain_too_similar(
    chain: list[dict[str, int]],
    used_keys: list[frozenset[tuple[int, int]]],
) -> bool:
    key = _chain_key(chain)
    for old in used_keys:
        overlap = len(key & old)
        if overlap >= max(1, min(len(key), len(old)) * 0.5):
            return True
        if key <= old or old <= key:
            return True
    return False


def _save_play_lesson(
    predictor,
    image_path: Path,
    before: QImage,
    after: QImage,
    game: dict[str, int] | None,
    pieces: list[dict[str, int]],
    chain: list[dict[str, int]],
) -> bool:
    if after.isNull() or before.isNull():
        return False
    popped = [piece for piece in chain if _looks_popped(before, after, piece)]
    if len(popped) < MIN_CHAIN:
        return False
    popped_ids = {id(piece) for piece in popped}
    labeled: list[dict[str, int]] = []
    rest: list[dict[str, int]] = []
    for piece in pieces:
        item = {
            "x": int(piece["x"]),
            "y": int(piece["y"]),
            "r": int(piece["r"]),
            "kind": str(piece.get("kind") or "tsum"),
            "group": int(piece.get("group") or 1),
        }
        if item["kind"] != "tsum":
            item["group"] = 0
            labeled.append(item)
            continue
        if id(piece) in popped_ids:
            item["group"] = 1
            labeled.append(item)
        else:
            rest.append(item)
    if rest:
        from PIL import Image

        with Image.open(image_path) as board:
            predictor._assign_groups(board.convert("RGB"), rest, kinds=min(3, len(rest)))
        for item in rest:
            item["group"] = int(item.get("group") or 1) + 1
            labeled.append(item)
    groups = {int(piece["group"]) for piece in labeled if piece["kind"] == "tsum"}
    if len(groups) < 2:
        return False
    return save_erase_lesson(predictor, image_path, game, labeled)


def _looks_popped(before: QImage, after: QImage, piece: dict[str, int]) -> bool:
    x, y, r = int(piece["x"]), int(piece["y"]), max(8, int(piece["r"]))
    return abs(_patch_luma(before, x, y, r) - _patch_luma(after, x, y, r)) >= 24


def _patch_luma(image: QImage, x: int, y: int, r: int) -> float:
    total = 0.0
    count = 0
    span = max(4, r // 2)
    width = max(1, image.width())
    height = max(1, image.height())
    for dy in (-span, 0, span):
        for dx in (-span, 0, span):
            px = min(max(x + dx, 0), width - 1)
            py = min(max(y + dy, 0), height - 1)
            color = image.pixelColor(px, py)
            total += 0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()
            count += 1
    return total / max(count, 1)

