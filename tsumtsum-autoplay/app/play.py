from __future__ import annotations

import colorsys
import json
import math
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock, Thread

from PySide6.QtCore import QPoint, QRect, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen

from app.bluestacks import (
    adb,
    capture_play_frame,
    capture_screen_path,
    capture_window_frame,
    reset_swipe_mouse,
    swipe_path,
    tap,
)
from app.intro import (
    Stopped,
    _check_stop,
    _continue_button,
    _match_start_button,
    _play_button,
    _retry_button,
    _slow_tap,
)
from app.play_style import (
    hud_net,
    hud_situation,
    load_unlike,
    rank,
    record_hud,
    record_pick,
    record_play,
    unlike_hit,
)
from app.trainer_bridge import (
    TRAINER_ROOT,
    load_play_tools,
    save_erase_lesson,
    save_play_board,
)

MIN_CHAIN = 3
BOARD_TSUMS = 8
TIMEUP_SCORE = 0.18
SKILL_GAP = 2.2
SKIP_TTL = 0.6
FAN_GAP = 8.0
_gpu_lock = Lock()

StatusFn = Callable[[str], None]


class PlayWorker(QThread):
    failed = Signal(str)
    stopped = Signal()
    completed = Signal()
    status = Signal(str)
    preview = Signal(QImage)

    def __init__(
        self,
        stop: Event,
        parent=None,
        start_match: bool = False,
        kind_count: int | None = None,
        save_boards: Callable[[], bool] | None = None,
        loop: bool = False,
    ) -> None:
        super().__init__(parent)
        self._stop = stop
        self._start_match = start_match
        self._kind_count = kind_count
        self._save_boards = save_boards
        self._loop = loop

    def run(self) -> None:
        try:
            run_play(
                self.status.emit,
                self._stop,
                start_match=self._start_match,
                preview=self.preview.emit,
                kind_count=self._kind_count,
                save_boards=self._save_boards,
                loop=self._loop,
            )
        except Stopped:
            self.stopped.emit()
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
        else:
            self.completed.emit()


def run_play(
    report: StatusFn | None,
    stop: Event | None,
    start_match: bool = False,
    preview: Callable[[QImage], None] | None = None,
    kind_count: int | None = None,
    save_boards: Callable[[], bool] | None = None,
    loop: bool = False,
) -> None:
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
    if getattr(predictor, "type_model", None) is None:
        raise RuntimeError("ツム種類のモデルがありません。画面認識アプリで学習してください。")
    if getattr(predictor, "scene_model", None) is None:
        raise RuntimeError("TIME UP のモデルがありません。")

    say("プレイを開始します")
    reset_swipe_mouse()
    unlike = load_unlike()
    skip_chains: list[frozenset[tuple[int, int]]] = []
    skip_born: dict[frozenset[tuple[int, int]], float] = {}
    saved_boards: set[tuple[tuple[int, int], ...]] = set()
    game = None
    skill = None
    fever = None
    timer = None
    fan = None
    hud_ready = False
    last_skill_at = 0.0
    last_fan_at = 0.0
    last_bomb_at = 0.0
    skip_bomb_cells: set[tuple[int, int]] = set()
    last_skill_look = 0.0
    last_save_at = 0.0
    ignore_start_until = 0.0
    saw_board = False
    clears = 0
    swipes = 0
    skill_taps = 0
    bomb_taps = 0
    fan_taps = 0
    pending_lesson: tuple[list[int], int] | None = None
    pending_hud: list[tuple[str, str, bool]] = []
    last_boxes: dict[str, dict[str, int]] = {}
    pending_spots: list[tuple[int, int, int, tuple[float, float, float] | None]] | None = None
    pending_key: frozenset[tuple[int, int]] | None = None
    pending_n = 0
    pending_at = 0.0
    pending_burst = 1
    pending_skip: list[frozenset[tuple[int, int]]] = []
    pieces: list[dict[str, int]] = []

    def fresh_match() -> None:
        nonlocal game, skill, fever, timer, fan, hud_ready
        nonlocal last_skill_at, last_fan_at, last_bomb_at, skip_bomb_cells, last_skill_look, last_save_at
        nonlocal ignore_start_until, saw_board
        nonlocal clears, swipes, skill_taps, bomb_taps, fan_taps
        nonlocal pending_lesson, pending_hud, last_boxes, pending_spots, pending_key
        nonlocal pending_n, pending_at, pending_burst, pending_skip, skip_chains, skip_born, saved_boards
        nonlocal my_group
        game = None
        skill = None
        fever = None
        timer = None
        fan = None
        hud_ready = False
        last_skill_at = 0.0
        last_fan_at = 0.0
        last_bomb_at = 0.0
        skip_bomb_cells = set()
        last_skill_look = 0.0
        last_save_at = 0.0
        ignore_start_until = time.time() + 6
        saw_board = False
        clears = 0
        swipes = 0
        skill_taps = 0
        bomb_taps = 0
        fan_taps = 0
        pending_lesson = None
        pending_hud = []
        last_boxes = {}
        pending_spots = None
        pending_key = None
        pending_n = 0
        pending_at = 0.0
        pending_burst = 1
        pending_skip = []
        skip_chains = []
        skip_born = {}
        saved_boards = set()
        my_group = 0

    my_group = 0
    kinds = 5
    kinds_locked = False
    if kind_count is not None and int(kind_count) >= 1:
        kinds = int(kind_count)
        kinds_locked = True
        say(f"種類 {kinds}")
    if start_match:
        seen, locked = _click_start_or_continue(say, stop)
        if not kinds_locked and locked:
            kinds = seen
            kinds_locked = True
            say(f"5＞4 {'使用' if kinds == 4 else '未使用'} / 種類 {kinds}")
    watching = Event()
    watch_hit = Event()
    stop_watch = Event()
    watcher = Thread(
        target=_watch_timeup,
        args=(predictor, stop_watch, watching, watch_hit, stop),
        daemon=True,
    )
    watcher.start()
    while True:
        _check_stop(stop)
        try:
            image = capture_play_frame()
            rgb = _qimage_rgb(image)
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.25, stop)
            continue
        if rgb is None or image.isNull():
            say("画面を待っています")
            _sleep_stop(0.25, stop)
            continue
        if game is None:
            with _gpu_lock:
                boxes = predictor.predict_all(Path("."), rgb=rgb)
            last_boxes = boxes
            game, _, fever, timer, fan = _merge_hud(
                boxes, game, None, fever, timer, fan
            )
        if _end_on_timeup(
            predictor,
            image,
            rgb,
            pending_spots,
            clears,
            swipes,
            pieces if saw_board else None,
            game,
            say,
            stop,
            timer,
            saw_board,
            last_boxes,
        ):
            record_play(clears, swipes, skill_taps, bomb_taps, fan_taps)
            if not loop:
                stop_watch.set()
                watching.clear()
                return
            if not _replay_after_timeup(predictor, say, stop):
                stop_watch.set()
                watching.clear()
                return
            fresh_match()
            say("次のプレイを開始します")
            continue
        _check_stop(stop)
        if not kinds_locked:
            used = _five_to_four_used_pil(rgb)
            if used is not None:
                kinds = 4 if used else 5
                kinds_locked = True
                say(f"5＞4 {'使用' if used else '未使用'} / 種類 {kinds}")
        with _gpu_lock:
            pieces = predictor.predict_pieces(Path("."), game, rgb=rgb, inner=False)
        tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        if len(tsums) < BOARD_TSUMS and not saw_board:
            with _gpu_lock:
                pieces = predictor.predict_pieces(Path("."), None, rgb=rgb, inner=False)
            tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
        _check_stop(stop)
        if len(tsums) >= BOARD_TSUMS:
            saw_board = True
            kinds_locked = True
        if saw_board and not hud_ready:
            with _gpu_lock:
                boxes = predictor.predict_all(Path("."), rgb=rgb)
            last_boxes = boxes
            skill = None
            game, skill, fever, timer, fan = _merge_hud(
                boxes, game, skill, fever, timer, fan, meters=True
            )
            hud_ready = True
            last_skill_at = 0.0
        if not saw_board:
            if len(tsums) < BOARD_TSUMS:
                say(f"ツム {len(tsums)}体（盤面が少ない）")
                if time.time() >= ignore_start_until and _tap_start_or_continue(image, say, stop):
                    continue
                play = None if image.isNull() else _play_button(image)
                if play is not None:
                    say("プレイをクリックします")
                    _slow_tap(play.center().x(), play.center().y())
                    _sleep_stop(2.0, stop)
                    continue
                continue
        erased_now = False
        if pending_spots is not None:
            erased = not _spots_lingered(rgb, pending_spots)
            if pending_n > 0 and len(tsums) <= pending_n - MIN_CHAIN:
                erased = True
            if erased:
                if pending_lesson is not None:
                    record_pick(pending_lesson[0], pending_lesson[1], True)
                    pending_lesson = None
                clears += max(1, pending_burst)
                pending_burst = 1
                pending_spots = None
                pending_key = None
                pending_n = 0
                pending_at = 0.0
                pending_skip = []
                erased_now = True
                with _gpu_lock:
                    coin = _read_coin(predictor, rgb, last_boxes)
                say(_counts_line(clears, swipes, coin))
            else:
                if pending_lesson is not None:
                    record_pick(pending_lesson[0], pending_lesson[1], False)
                    pending_lesson = None
                miss_at = time.time()
                for key in pending_skip:
                    skip_born[key] = miss_at
                pending_spots = None
                pending_key = None
                pending_n = 0
                pending_at = 0.0
                pending_burst = 1
                pending_skip = []
                with _gpu_lock:
                    coin = _read_coin(predictor, rgb, last_boxes)
                say(_counts_line(clears, swipes, coin))
        fever_fill = _fever_fill(rgb, fever)
        fever_on = fever_fill >= 0.25
        say(_group_counts_line(tsums))
        now = time.time()
        skip_chains = [
            key for key in skip_chains if now - skip_born.get(key, 0) < SKIP_TTL
        ]
        skip_chains = _prune_skip(skip_chains, tsums)
        raw = [
            item
            for item in candidates(pieces, max(MIN_CHAIN, len(tsums)))
            if len(item) >= MIN_CHAIN
        ]
        found = [item for item in raw if not _chain_too_similar(item, skip_chains)]
        found.sort(key=len, reverse=True)
        if my_group <= 0 and skill is not None:
            with _gpu_lock:
                my_group = _mytsum_group(predictor, rgb, tsums, skill)
            if my_group <= 0:
                my_group = -1
        if my_group > 0:
            found.sort(
                key=lambda chain: (
                    len(chain) + (1 if int(chain[0].get("group") or 0) == my_group else 0),
                    int(chain[0].get("group") or 0) == my_group,
                ),
                reverse=True,
            )
        if found:
            say("候補 " + " / ".join(str(len(item)) for item in found))
        has_bomb = any(str(piece.get("kind") or "") == "bomb" for piece in pieces)
        sit = hud_situation(
            fever_on,
            fever_fill,
            bool(found),
            has_bomb,
            len(tsums) >= BOARD_TSUMS,
        )
        if pending_hud:
            for old_sit, kind, pressed in pending_hud:
                ok = erased_now or fever_on or (kind == "fan" and bool(found))
                record_hud(old_sit, kind, pressed, ok)
            pending_hud = []
        if _press_skill(skill, image, rgb, say, stop, last_skill_at, pending_hud, sit):
            last_skill_at = time.time()
            skill_taps += 1
        skill_fill = _skill_fill(rgb, skill)
        if found:
            used: set[tuple[int, int]] = set()
            last_chain: list[dict[str, int]] | None = None
            burst = 0
            burst_skip: list[frozenset[tuple[int, int]]] = []
            timeup = False
            watch_hit.clear()
            watching.set()
            try:
                for chain in found:
                    if watch_hit.is_set():
                        timeup = True
                        break
                    spots = {(int(piece["x"]), int(piece["y"])) for piece in chain}
                    if spots & used:
                        continue
                    if not _swipe_chain(
                        chain,
                        pieces,
                        image,
                        game,
                        len(tsums),
                        say,
                        stop,
                        preview,
                        watch_hit,
                        skill_fill,
                    ):
                        continue
                    swipes += 1
                    burst += 1
                    used |= spots
                    last_chain = chain
                    key = _chain_key(chain)
                    skip_chains.append(key)
                    skip_born[key] = time.time()
                    burst_skip.append(key)
                    if watch_hit.is_set():
                        timeup = True
                        break
            finally:
                watching.clear()
            if timeup or watch_hit.is_set():
                timeup = True
                try:
                    check = capture_play_frame()
                    check_rgb = _qimage_rgb(check)
                except Exception:
                    check = image
                    check_rgb = rgb
                if not (
                    check is not None
                    and not check.isNull()
                    and check_rgb is not None
                    and _end_on_timeup(
                        predictor,
                        check,
                        check_rgb,
                        pending_spots,
                        clears,
                        swipes,
                        pieces,
                        game,
                        say,
                        stop,
                        timer,
                        True,
                        last_boxes,
                    )
                ):
                    with _gpu_lock:
                        coin = _read_coin(predictor, check_rgb, last_boxes)
                    say("TIME UP / " + _counts_line(clears, swipes, coin))
            if timeup:
                record_play(clears, swipes, skill_taps, bomb_taps, fan_taps)
                if not loop:
                    stop_watch.set()
                    watching.clear()
                    return
                if not _replay_after_timeup(predictor, say, stop):
                    stop_watch.set()
                    watching.clear()
                    return
                fresh_match()
                say("次のプレイを開始します")
                continue
            if last_chain is not None:
                extra = burst
                if pending_spots is not None:
                    extra = pending_burst + burst
                pending_spots = _chain_spots(rgb, last_chain)
                pending_key = _chain_key(last_chain)
                pending_n = len(tsums)
                pending_burst = extra
                pending_lesson = ([len(item) for item in found], len(last_chain))
                pending_at = time.time()
                pending_skip = pending_skip + burst_skip
            did, cell = _tap_biggest_bomb(
                pieces, image, say, stop, game, skip_bomb_cells
            )
            if did:
                bomb_taps += 1
                last_bomb_at = time.time()
                if cell is not None:
                    skip_bomb_cells.add(cell)
                pending_hud.append((sit, "bomb", True))
            continue
        if preview is not None:
            preview(_draw_plan(image, pieces, [], game, skill_fill))
        if saw_board and (skill is None or fan is None):
            with _gpu_lock:
                boxes = predictor.predict_all(Path("."), rgb=rgb)
            last_boxes = boxes
            game, skill, fever, timer, fan = _merge_hud(
                boxes, game, skill, fever, timer, fan, meters=True
            )
        did, cell = _tap_biggest_bomb(
            pieces, image, say, stop, game, skip_bomb_cells
        )
        if did:
            bomb_taps += 1
            last_bomb_at = time.time()
            if cell is not None:
                skip_bomb_cells.add(cell)
            pending_hud.append((sit, "bomb", True))
            continue
        if _press_fan(fan, image, say, stop, last_fan_at, len(tsums), pending_hud, sit):
            last_fan_at = time.time()
            fan_taps += 1
            skip_chains = []
            continue
        last_save_at = _learn_board(
            predictor,
            image,
            rgb,
            game,
            skill,
            fever,
            timer,
            fan,
            last_boxes,
            pieces,
            tsums,
            saved_boards,
            last_save_at,
            save_boards,
            say,
        )
        say(f"ツム {len(tsums)}体 / なぞれる3体以上なし")
        continue


def _swipe_chain(
    chain: list[dict[str, int]],
    pieces: list[dict[str, int]],
    image: QImage,
    game: dict[str, int] | None,
    tsum_count: int,
    say: StatusFn,
    stop: Event | None,
    preview: Callable[[QImage], None] | None,
    abort: Event | None = None,
    skill_fill: float | None = None,
) -> bool:
    points = [(int(piece["x"]), int(piece["y"])) for piece in chain]
    cells = {(x // 24, y // 24) for x, y in points}
    if len(points) < MIN_CHAIN or len(cells) < MIN_CHAIN:
        say("同じ位置に重なっているので見送り")
        return False
    route = " → ".join(f"{x},{y}" for x, y in points)
    say(f"ツム {tsum_count}体 / チェーン {len(chain)}体")
    say(f"経路 {route}")
    if preview is not None:
        preview(_draw_plan(image, pieces, chain, game, skill_fill))
    say("なぞっています")
    _check_stop(stop)
    how = swipe_path(
        points,
        screen_w=image.width(),
        screen_h=image.height(),
        stop=stop,
        abort=abort,
    )
    say(how)
    return True


def _chain_spots(rgb, chain: list[dict[str, int]]) -> list[tuple[int, int, int, tuple[float, float, float] | None]]:
    spots: list[tuple[int, int, int, tuple[float, float, float] | None]] = []
    for piece in chain:
        x, y = int(piece["x"]), int(piece["y"])
        radius = max(6, int(piece.get("r") or 12))
        spots.append((x, y, radius, _spot_mean(rgb, x, y, radius)))
    return spots


def _spots_lingered(
    after,
    spots: list[tuple[int, int, int, tuple[float, float, float] | None]],
) -> bool:
    hits = 0
    for x, y, radius, old in spots:
        if old is None:
            continue
        new = _spot_mean(after, x, y, radius)
        if new is None:
            continue
        dist = sum((a - b) ** 2 for a, b in zip(old, new)) ** 0.5
        if dist < 36:
            hits += 1
    return hits >= MIN_CHAIN


def _spot_mean(image, x: int, y: int, radius: int) -> tuple[float, float, float] | None:
    span = max(4, radius // 2)
    box = (x - span, y - span, x + span + 1, y + span + 1)
    crop = image.crop(box)
    pixels = list(crop.getdata())
    if not pixels:
        return None
    count = len(pixels)
    return (
        sum(pixel[0] for pixel in pixels) / count,
        sum(pixel[1] for pixel in pixels) / count,
        sum(pixel[2] for pixel in pixels) / count,
    )


def _unlike_from_chain(
    chain: list[dict[str, int]],
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    vecs = [piece.get("_vec") for piece in chain]
    if any(vec is None for vec in vecs) or len(chain) < 2:
        return None
    cut = _weakest_cut(chain)
    left_v, right_v = vecs[cut - 1], vecs[cut]
    if left_v is None or right_v is None:
        return None
    left = [vecs[index] for index in range(cut)]
    right = [vecs[index] for index in range(cut, len(vecs))]
    if not left or not right:
        return None
    return (_mean_vec(left), _mean_vec(right))


def _weakest_cut(chain: list[dict[str, int]]) -> int:
    vecs = [piece.get("_vec") for piece in chain]
    cut = 1
    worst = 2.0
    for index in range(1, len(chain)):
        left, right = vecs[index - 1], vecs[index]
        if left is None or right is None:
            continue
        sim = _cosine(left, right)
        if sim < worst:
            worst = sim
            cut = index
    return cut


def _mean_vec(vecs: list[tuple[float, ...]]) -> tuple[float, ...]:
    dim = len(vecs[0])
    count = len(vecs)
    return tuple(sum(vec[index] for vec in vecs) / count for index in range(dim))


def _remember_mixed(predictor, image: QImage, game, pieces, chain) -> None:
    from tempfile import gettempdir

    path = Path(gettempdir()) / "tsum_autoplay_mixed.png"
    if not image.save(str(path), "PNG"):
        return
    cut = _weakest_cut(chain)
    chain_ids = {id(piece) for piece in chain}
    labeled: list[dict[str, int]] = []
    for piece in pieces:
        item = {
            key: value
            for key, value in piece.items()
            if key in {"x", "y", "r", "kind", "group"}
        }
        if id(piece) in chain_ids:
            index = next(i for i, member in enumerate(chain) if id(member) == id(piece))
            item["group"] = 1 if index < cut else 2
        labeled.append(item)
    try:
        save_erase_lesson(predictor, path, game, labeled)
    except Exception:
        return


def _merge_hud(boxes, game, skill, fever, timer, fan, meters: bool = False):
    if game is None and boxes.get("game"):
        game = boxes["game"]
    if skill is None and boxes.get("skill"):
        skill = boxes["skill"]
    if (fever is None or meters) and boxes.get("fever"):
        fever = boxes["fever"]
    if (timer is None or meters) and boxes.get("timer"):
        timer = boxes["timer"]
    if (fan is None or meters) and boxes.get("fan"):
        fan = boxes["fan"]
    return game, skill, fever, timer, fan


def _hud_boxes(game, skill, fever, timer, fan) -> dict[str, dict[str, int]]:
    boxes: dict[str, dict[str, int]] = {}
    if game is not None:
        boxes["game"] = game
    if skill is not None:
        boxes["skill"] = skill
    if fever is not None:
        boxes["fever"] = fever
    if timer is not None:
        boxes["timer"] = timer
    if fan is not None:
        boxes["fan"] = fan
    return boxes


def _learn_board(
    predictor,
    image: QImage,
    rgb,
    game,
    skill,
    fever,
    timer,
    fan,
    last_boxes: dict[str, dict[str, int]],
    pieces: list[dict[str, int]],
    tsums: list[dict[str, int]],
    saved_boards: set[tuple[tuple[int, int], ...]],
    last_save_at: float,
    save_boards: Callable[[], bool] | None,
    say: StatusFn,
) -> float:
    if save_boards is None or not save_boards():
        return last_save_at
    if not tsums:
        return last_save_at
    board = _board_key(tsums)
    if board in saved_boards or time.time() - last_save_at < 2.5:
        return last_save_at
    saved_boards.add(board)
    boxes = dict(last_boxes)
    boxes.update(_hud_boxes(game, skill, fever, timer, fan))
    try:
        learned = save_play_board(
            predictor, image, game, boxes=boxes, pieces=pieces or [], rgb=rgb
        )
    except Exception:
        learned = False
    if learned and save_boards is not None and save_boards():
        say("消す前の盤面を取り込みました")
    return time.time()


def _press_skill(
    skill: dict[str, int] | None,
    image: QImage,
    rgb,
    say: StatusFn,
    stop: Event | None,
    last_skill_at: float,
    pending_hud: list[tuple[str, str, bool]],
    sit: str,
) -> bool:
    if skill is None:
        say("スキル枠がありません")
        return False
    if time.time() - last_skill_at < SKILL_GAP:
        return False
    if not _skill_ready(rgb, skill):
        return False
    pending_hud.append((sit, "skill", True))
    _tap_skill(skill, image, say, stop)
    return True


def _skill_ready(rgb, skill: dict[str, int]) -> bool:
    if rgb is None:
        return False
    yellow, blue = _skill_ring_yellow_blue(rgb, skill)
    if yellow + blue < SLOT_ON:
        return False
    return yellow > blue


def _skill_ring_yellow_blue(image, box: dict[str, int]) -> tuple[float, float]:
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(image.width, left + max(1, int(box["w"])))
    bottom = min(image.height, top + max(1, int(box["h"])))
    if right - left < 8 or bottom - top < 8:
        return 0.0, 0.0
    crop = image.crop((left, top, right, bottom))
    width, height = crop.size
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    radius = min(width, height) / 2.0
    pixels = crop.load()
    total = 0
    yellow = 0
    blue = 0
    step = max(1, min(width, height) // 24)
    for yy in range(0, height, step):
        for xx in range(0, width, step):
            dx = xx - cx
            dy = yy - cy
            dist = (dx * dx + dy * dy) ** 0.5 / radius
            if dist < 0.50 or dist > 0.92:
                continue
            red, green, blue_v = pixels[xx, yy][:3]
            hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue_v / 255.0)
            total += 1
            if 0.08 <= hue <= 0.18 and sat >= 0.30 and val >= 0.45:
                yellow += 1
            elif 0.42 <= hue <= 0.72 and sat >= 0.22 and val >= 0.25:
                blue += 1
    if total <= 0:
        return 0.0, 0.0
    return yellow / total, blue / total


def _skill_button_square(box: dict[str, int]) -> dict[str, int]:
    x = int(box["x"])
    y = int(box["y"])
    width = max(1, int(box["w"]))
    height = max(1, int(box["h"]))
    if height > width:
        return {"x": x, "y": y, "w": width, "h": width}
    if width > height:
        return {"x": x, "y": y, "w": height, "h": height}
    return {"x": x, "y": y, "w": width, "h": height}


def _skill_fill(rgb, skill: dict[str, int] | None) -> float | None:
    if rgb is None or skill is None:
        return None
    box = _skill_button_square(skill)
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(rgb.width, left + max(1, int(box["w"])))
    bottom = min(rgb.height, top + max(1, int(box["h"])))
    if right - left < 8 or bottom - top < 8:
        return 0.0
    crop = rgb.crop((left, top, right, bottom))
    width, height = crop.size
    pixels = crop.load()
    xs: list[int] = []
    ys: list[int] = []
    for yy in range(height):
        for xx in range(width):
            red, green, blue_v = pixels[xx, yy][:3]
            if max(red, green, blue_v) >= 89:
                xs.append(xx)
                ys.append(yy)
    if not xs:
        return 0.0
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    edges: list[int] = []
    for index in range(72):
        ang = -math.pi / 2.0 + (2.0 * math.pi * index / 72.0)
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        for dist in range(8, max(width, height)):
            xx = int(round(cx + cos_a * dist))
            yy = int(round(cy + sin_a * dist))
            if xx < 0 or yy < 0 or xx >= width or yy >= height:
                break
            red, green, blue_v = pixels[xx, yy][:3]
            if max(red, green, blue_v) < 56:
                edges.append(dist)
                break
    if len(edges) >= 36:
        radius = float(sorted(edges)[len(edges) // 2])
    else:
        radius = min(width, height) / 2.0
    filled = 0
    total = 0
    ring = radius * 0.92
    for index in range(72):
        ang = -math.pi / 2.0 + (2.0 * math.pi * index / 72.0)
        xx = int(round(cx + math.cos(ang) * ring))
        yy = int(round(cy + math.sin(ang) * ring))
        if xx < 0 or yy < 0 or xx >= width or yy >= height:
            continue
        red, green, blue_v = pixels[xx, yy][:3]
        hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue_v / 255.0)
        total += 1
        if 0.05 <= hue <= 0.20 and sat >= 0.20 and val >= 0.45:
            filled += 1
        elif 0.48 <= hue <= 0.58 and sat >= 0.45 and val >= 0.75:
            filled += 1
    if total <= 0:
        return 0.0
    return filled / total


def _press_fan(
    fan: dict[str, int] | None,
    image: QImage,
    say: StatusFn,
    stop: Event | None,
    last_fan_at: float,
    tsum_count: int,
    pending_hud: list[tuple[str, str, bool]],
    sit: str,
) -> bool:
    if fan is None:
        say("扇風機の枠がありません")
        return False
    if tsum_count < BOARD_TSUMS:
        return False
    if time.time() - last_fan_at < FAN_GAP:
        return False
    pending_hud.append((sit, "fan", True))
    _tap_fan(fan, image, say, stop)
    _tap_fan(fan, image, say, stop)
    return True


def _tap_skill(
    skill: dict[str, int],
    image: QImage,
    say: StatusFn,
    stop: Event | None,
) -> None:
    x = int(skill["x"] + max(1, int(skill["w"])) / 2)
    y = int(skill["y"] + max(1, int(skill["h"])) / 2)
    say(f"スキルをタップ {x},{y}")
    tap(x, y, screen_w=image.width(), screen_h=image.height())


def _tap_fan(
    fan: dict[str, int],
    image: QImage,
    say: StatusFn,
    stop: Event | None,
) -> None:
    x = int(fan["x"] + max(1, int(fan["w"])) / 2)
    y = int(fan["y"] + max(1, int(fan["h"])) / 2)
    say(f"扇風機をタップ {x},{y}")
    tap(x, y, screen_w=image.width(), screen_h=image.height())
    _sleep_stop(0.12, stop)


def _fever_fill(image, box: dict[str, int] | None) -> float:
    if box is None:
        return 0.0
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(image.width, left + max(1, int(box["w"])))
    bottom = min(image.height, top + max(1, int(box["h"])))
    if right - left < 2 or bottom - top < 2:
        return 0.0
    crop = image.crop((left, top, right, bottom))
    width, height = crop.size
    step_x = max(1, width // 24)
    step_y = max(1, height // 24)
    pixels = crop.load()
    total = 0
    pink = 0
    for yy in range(0, height, step_y):
        for xx in range(0, width, step_x):
            red, green, blue = pixels[xx, yy][:3]
            hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
            total += 1
            if sat >= 0.35 and val >= 0.45 and (hue >= 0.82 or hue <= 0.08):
                pink += 1
    if total <= 0:
        return 0.0
    return pink / total


def _tap_biggest_bomb(
    pieces: list[dict[str, int]],
    image: QImage,
    say: StatusFn,
    stop: Event | None,
    game: dict[str, int] | None = None,
    skip_cells: set[tuple[int, int]] | None = None,
) -> tuple[bool, tuple[int, int] | None]:
    bombs = _bombs_on_board(pieces, game)
    if skip_cells:
        bombs = [piece for piece in bombs if _piece_cell(piece) not in skip_cells]
    if not bombs:
        return False, None
    bomb = max(bombs, key=lambda piece: int(piece.get("r") or 0))
    say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
    tap(int(bomb["x"]), int(bomb["y"]), screen_w=image.width(), screen_h=image.height())
    return True, _piece_cell(bomb)


def _piece_cell(piece: dict[str, int]) -> tuple[int, int]:
    return (int(piece["x"]) // 16, int(piece["y"]) // 16)


def _bombs_on_board(
    pieces: list[dict[str, int]],
    game: dict[str, int] | None,
) -> list[dict[str, int]]:
    if game is None:
        return []
    left = int(game["x"])
    top = int(game["y"])
    right = left + max(1, int(game["w"]))
    bottom = top + max(1, int(game["h"]))
    found: list[dict[str, int]] = []
    for piece in pieces:
        if str(piece.get("kind") or "") != "bomb":
            continue
        x = int(piece["x"])
        y = int(piece["y"])
        if x < left or y < top or x >= right or y >= bottom:
            continue
        found.append(piece)
    return found


def _remaining_after_erase(
    pieces: list[dict[str, int]],
    chain: list[dict[str, int]],
) -> list[dict[str, int]]:
    gone = {id(piece) for piece in chain}
    leftover = [dict(piece) for piece in pieces if id(piece) not in gone]
    _drop_down(leftover, pieces)
    return leftover


def _drop_down(remaining: list[dict[str, int]], before: list[dict[str, int]]) -> None:
    origins = [
        piece
        for piece in before
        if str(piece.get("kind") or "") in {"tsum", "bomb"}
    ]
    movers = [
        piece
        for piece in remaining
        if str(piece.get("kind") or "") in {"tsum", "bomb"}
    ]
    tsums = [piece for piece in origins if str(piece.get("kind") or "") == "tsum"]
    spacing = _median_spacing(tsums or origins)
    if spacing <= 0 or not movers or not origins:
        return
    col_w = spacing * 0.5
    centers: list[float] = []
    orig_cols: list[list[dict[str, int]]] = []
    for piece in origins:
        x = float(piece["x"])
        best_i = None
        best_d = col_w
        for index, cx in enumerate(centers):
            dist = abs(x - cx)
            if dist < best_d:
                best_d = dist
                best_i = index
        if best_i is None:
            centers.append(x)
            orig_cols.append([piece])
            continue
        orig_cols[best_i].append(piece)
        count = len(orig_cols[best_i])
        centers[best_i] += (x - centers[best_i]) / count
    rest_cols: list[list[dict[str, int]]] = [[] for _ in centers]
    for piece in movers:
        x = float(piece["x"])
        best_i = min(range(len(centers)), key=lambda index: abs(x - centers[index]))
        rest_cols[best_i].append(piece)
    for orig, kept in zip(orig_cols, rest_cols):
        if not kept:
            continue
        ys = sorted(int(piece["y"]) for piece in orig)
        bottom = ys[-1]
        gaps = [ys[index + 1] - ys[index] for index in range(len(ys) - 1) if ys[index + 1] > ys[index]]
        step = gaps[len(gaps) // 2] if gaps else int(round(spacing))
        if step < 1:
            step = max(1, int(round(spacing)))
        kept.sort(key=lambda piece: int(piece["y"]))
        for index, piece in enumerate(reversed(kept)):
            piece["y"] = int(round(bottom - index * step))


def _median_spacing(tsums: list[dict[str, int]]) -> float:
    if len(tsums) < 2:
        return 0.0
    nearest: list[float] = []
    for index, left in enumerate(tsums):
        ax, ay = int(left["x"]), int(left["y"])
        best = 1e18
        for other, right in enumerate(tsums):
            if other == index:
                continue
            dx = ax - int(right["x"])
            dy = ay - int(right["y"])
            dist = dx * dx + dy * dy
            if dist < best:
                best = dist
        if best < 1e18:
            nearest.append(best ** 0.5)
    if not nearest:
        return 0.0
    nearest.sort()
    return nearest[len(nearest) // 2]


def _qimage_rgb(image: QImage):
    from PIL import Image as PILImage

    if image.isNull():
        return None
    converted = image.convertToFormat(QImage.Format.Format_RGB888)
    width = converted.width()
    height = converted.height()
    stride = converted.bytesPerLine()
    ptr = converted.constBits()
    size = converted.sizeInBytes()
    try:
        mv = memoryview(ptr)[:size]
    except TypeError:
        mv = bytes(ptr[:size])
    try:
        import numpy as np

        raw = np.frombuffer(mv, dtype=np.uint8)
        if stride == width * 3:
            arr = raw.reshape((height, width, 3)).copy()
        else:
            arr = raw.reshape((height, stride))[:, : width * 3].copy()
            arr = arr.reshape((height, width, 3))
        return PILImage.fromarray(arr, "RGB")
    except Exception:
        buf = bytes(mv) if not isinstance(mv, (bytes, bytearray)) else mv
        if stride == width * 3:
            return PILImage.frombytes("RGB", (width, height), buf)
        rows = [buf[row * stride : row * stride + width * 3] for row in range(height)]
        return PILImage.frombytes("RGB", (width, height), b"".join(rows))


def _watch_timeup(
    predictor,
    stop_watch: Event,
    watching: Event,
    hit: Event,
    stop: Event | None,
) -> None:
    while not stop_watch.is_set():
        if stop is not None and stop.is_set():
            return
        if not watching.is_set() or hit.is_set():
            time.sleep(0.02)
            continue
        image = capture_window_frame()
        if not watching.is_set() or stop_watch.is_set() or hit.is_set():
            continue
        if image is None or image.isNull():
            time.sleep(0.05)
            continue
        rgb = _qimage_rgb(image)
        if rgb is None:
            time.sleep(0.05)
            continue
        if not watching.is_set() or stop_watch.is_set() or hit.is_set():
            continue
        with _gpu_lock:
            if not watching.is_set() or stop_watch.is_set() or hit.is_set():
                continue
            seen, _score = _timeup_hit(predictor, rgb)
        if seen:
            hit.set()


def _end_on_timeup(
    predictor,
    image: QImage,
    rgb,
    pending_spots,
    clears: int,
    swipes: int,
    pieces: list[dict[str, int]] | None,
    game: dict[str, int] | None,
    say: StatusFn,
    stop: Event | None,
    timer: dict[str, int] | None = None,
    saw_board: bool = False,
    boxes: dict[str, dict[str, int]] | None = None,
) -> bool:
    with _gpu_lock:
        hit, score = _timeup_hit(predictor, rgb)
        timer_zero = saw_board and _timer_is_zero(predictor, rgb, timer)
        coin = _read_coin(predictor, rgb, boxes)
    retry = (
        saw_board
        and image is not None
        and not image.isNull()
        and _retry_button(image) is not None
    )
    if not hit and not timer_zero and not retry:
        return False
    extra = 0
    if pending_spots is not None and not _spots_lingered(rgb, pending_spots):
        extra = 1
    counts = _counts_line(clears + extra, swipes, coin)
    if hit:
        say(f"TIME UP {score:.0%} / {counts}")
    elif timer_zero:
        say(f"TIME UP タイマー0 / {counts}")
    else:
        say(f"TIME UP / {counts}")
    return True


def _counts_line(clears: int, swipes: int, coin: str = "") -> str:
    text = f"消し {clears}回 / なぞり {swipes}回"
    if coin:
        text += f" / コイン {int(coin)}"
    return text


def _read_coin(predictor, rgb, boxes: dict[str, dict[str, int]] | None) -> str:
    if rgb is None or not boxes:
        return ""
    predict = getattr(predictor, "predict_coin_digits", None)
    if predict is None:
        return ""
    width, height = rgb.size
    for key in ("coin", "result_coin"):
        box = boxes.get(key)
        if not box:
            continue
        left = max(0, int(box["x"]))
        top = max(0, int(box["y"]))
        right = min(width, left + max(1, int(box["w"])))
        bottom = min(height, top + max(1, int(box["h"])))
        if right - left < 4 or bottom - top < 4:
            continue
        crop = rgb.crop((left, top, right, bottom))
        try:
            raw = str(predict(crop, key) or "")
        except Exception:
            continue
        digits = "".join(char for char in raw if char.isdigit())
        if digits:
            return digits
    return ""


def _timer_is_zero(predictor, rgb, timer: dict[str, int] | None) -> bool:
    if timer is None or rgb is None:
        return False
    predict = getattr(predictor, "predict_coin_digits", None)
    if predict is None:
        return False
    width, height = rgb.size
    left = max(0, int(timer["x"]))
    top = max(0, int(timer["y"]))
    right = min(width, left + max(1, int(timer["w"])))
    bottom = min(height, top + max(1, int(timer["h"])))
    if right - left < 4 or bottom - top < 4:
        return False
    crop = rgb.crop((left, top, right, bottom))
    try:
        raw = str(predict(crop, "timer") or "")
    except Exception:
        return False
    digits = "".join(char for char in raw if char.isdigit())
    if not digits:
        return False
    return int(digits) == 0


def _replay_after_timeup(predictor, say: StatusFn, stop: Event | None) -> bool:
    if not _wait_and_tap_retry(predictor, say, stop):
        return False
    return _wait_and_tap_start(say, stop)


def _tap_point(image: QImage, x: int, y: int) -> None:
    xi, yi = str(int(x)), str(int(y))
    result = adb(["shell", "input", "tap", xi, yi], timeout=6)
    if result.returncode != 0:
        tap(x, y, screen_w=image.width(), screen_h=image.height())


def _scene_top(predictor, rgb) -> tuple[str, float]:
    model = getattr(predictor, "scene_model", None)
    transform = getattr(predictor, "_scene_transform", None)
    if model is None or transform is None or rgb is None:
        return "other", 0.0
    import torch

    view = _portrait_frame(rgb)
    tensor = transform(view).unsqueeze(0).to(predictor.device)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    classes = getattr(predictor, "scene_classes", None) or ("other", "go", "timeup")
    index = int(probs.argmax().item())
    name = classes[index] if 0 <= index < len(classes) else "other"
    return name, float(probs[index].item())


def _timeup_hit(predictor, rgb) -> tuple[bool, float]:
    score, top = _timeup_read(predictor, rgb)
    return (top or score >= TIMEUP_SCORE), score


def _timeup_read(predictor, rgb) -> tuple[float, bool]:
    model = getattr(predictor, "scene_model", None)
    transform = getattr(predictor, "_scene_transform", None)
    if model is None or transform is None or rgb is None:
        return 0.0, False
    import torch

    view = _portrait_frame(rgb)
    tensor = transform(view).unsqueeze(0).to(predictor.device)
    with torch.no_grad():
        probs = torch.softmax(model(tensor), dim=1)[0]
    classes = getattr(predictor, "scene_classes", None) or ("other", "go", "timeup")
    if "timeup" in classes:
        index = classes.index("timeup")
    elif probs.numel() >= 3:
        index = 2
    else:
        return 0.0, False
    if index < 0 or index >= int(probs.numel()):
        return 0.0, False
    score = float(probs[index].item())
    top = int(probs.argmax().item()) == index
    return score, top


def _timeup_score(predictor, rgb) -> float:
    score, _top = _timeup_read(predictor, rgb)
    return score


def _portrait_frame(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width <= height:
        return image
    sample_w = min(160, width)
    sample_h = max(1, int(round(height * sample_w / width)))
    sample = image.resize((sample_w, sample_h))
    left_s = 0
    while left_s < sample_w - 1 and _column_luma(sample, left_s) < 14:
        left_s += 1
    right_s = sample_w - 1
    while right_s > left_s and _column_luma(sample, right_s) < 14:
        right_s -= 1
    scale = width / sample_w
    left = int(left_s * scale)
    right = min(width, int((right_s + 1) * scale))
    if right - left < height * 0.35:
        strip_w = max(1, int(height * 9 / 16))
        left = max(0, (width - strip_w) // 2)
        right = min(width, left + strip_w)
    return image.crop((left, 0, right, height))


def _column_luma(image: Image.Image, x: int) -> float:
    height = image.size[1]
    total = 0.0
    for y in range(height):
        red, green, blue = image.getpixel((x, y))[:3]
        total += 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return total / max(height, 1)


def _sleep_stop(seconds: float, stop: Event | None) -> None:
    end = time.time() + seconds
    while time.time() < end:
        _check_stop(stop)
        time.sleep(min(0.2, max(0.0, end - time.time())))


def _click_start_or_continue(say: StatusFn, stop: Event | None) -> tuple[int, bool]:
    deadline = time.time() + 12
    kinds = 5
    locked = False
    while time.time() < deadline:
        _check_stop(stop)
        try:
            path = capture_screen_path()
            image = QImage(str(path))
        except Exception:
            say("画面を待っています")
            _sleep_stop(0.8, stop)
            continue
        if image.isNull():
            _sleep_stop(0.4, stop)
            continue
        used = _five_to_four_used_path(path)
        if used is not None:
            kinds = 4 if used else 5
            locked = True
        if _tap_start_or_continue(image, say, stop):
            return kinds, locked
        say("スタートまたは続けるを待っています")
        _sleep_stop(0.35, stop)
    return kinds, locked


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


def _wait_and_tap_retry(predictor, say: StatusFn, stop: Event | None) -> bool:
    say("リトライを待っています")
    deadline = time.time() + 90
    ready_at = time.time() + 4
    hits = 0
    while time.time() < deadline:
        _check_stop(stop)
        try:
            image = capture_play_frame()
            rgb = _qimage_rgb(image)
        except Exception:
            hits = 0
            _sleep_stop(0.4, stop)
            continue
        if image is None or image.isNull() or rgb is None:
            hits = 0
            _sleep_stop(0.4, stop)
            continue
        with _gpu_lock:
            hit, _score = _timeup_hit(predictor, rgb)
        if time.time() < ready_at or hit:
            hits = 0
            _sleep_stop(0.4, stop)
            continue
        retry = _retry_button(image)
        if retry is None:
            hits = 0
            _sleep_stop(0.4, stop)
            continue
        hits += 1
        if hits < 4:
            _sleep_stop(0.4, stop)
            continue
        say("リトライをクリックします")
        _tap_point(image, retry.center().x(), retry.center().y())
        return True
    say("リトライが出ませんでした")
    return False


def _wait_and_tap_start(say: StatusFn, stop: Event | None) -> bool:
    say("スタートを待っています")
    deadline = time.time() + 90
    hits = 0
    while time.time() < deadline:
        _check_stop(stop)
        try:
            image = capture_play_frame()
        except Exception:
            hits = 0
            _sleep_stop(0.4, stop)
            continue
        if image is None or image.isNull():
            hits = 0
            _sleep_stop(0.4, stop)
            continue
        start = _match_start_button(image)
        if start is None:
            hits = 0
            _sleep_stop(0.4, stop)
            continue
        hits += 1
        if hits < 4:
            _sleep_stop(0.4, stop)
            continue
        say("スタートをクリックします")
        _tap_point(image, start.center().x(), start.center().y())
        return True
    say("スタートが出ませんでした")
    return False


_SLOT_5TO4: tuple[dict[str, int], int, int] | None | bool = False
SLOT_ON = 0.28


def _five_to_four_slot() -> tuple[dict[str, int], int, int] | None:
    global _SLOT_5TO4
    if _SLOT_5TO4 is not False:
        return _SLOT_5TO4
    path = TRAINER_ROOT / "data" / "item_slots.json"
    loaded = None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get("5to4") or []:
            box = item.get("box")
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if not box or width <= 0 or height <= 0:
                continue
            loaded = (
                {
                    "x": int(box["x"]),
                    "y": int(box["y"]),
                    "w": max(1, int(box["w"])),
                    "h": max(1, int(box["h"])),
                },
                width,
                height,
            )
            break
    except Exception:
        loaded = None
    _SLOT_5TO4 = loaded
    return loaded


def _five_to_four_used_path(path: Path) -> bool | None:
    from PIL import Image

    with Image.open(path) as board:
        return _five_to_four_used_pil(board.convert("RGB"))


def _five_to_four_used_pil(image) -> bool | None:
    slot = _five_to_four_slot()
    if slot is None:
        return None
    box, src_w, src_h = slot
    view = _portrait_frame(image)
    scaled = _scale_item_box(box, src_w, src_h, view.size[0], view.size[1])
    yellow, blue = _slot_yellow_blue(view, scaled)
    if yellow + blue < SLOT_ON:
        return None
    return yellow > blue


def read_kind_count() -> int | None:
    try:
        path = capture_screen_path()
    except Exception:
        return None
    used = _five_to_four_used_path(path)
    if used is None:
        return None
    return 4 if used else 5


def _scale_item_box(
    box: dict[str, int], src_w: int, src_h: int, dst_w: int, dst_h: int
) -> dict[str, int]:
    sx = dst_w / max(src_w, 1)
    sy = dst_h / max(src_h, 1)
    x = int(round(int(box["x"]) * sx))
    y = int(round(int(box["y"]) * sy))
    w = max(1, int(round(int(box["w"]) * sx)))
    h = max(1, int(round(int(box["h"]) * sy)))
    x = max(0, min(x, max(dst_w - 1, 0)))
    y = max(0, min(y, max(dst_h - 1, 0)))
    w = min(w, max(dst_w - x, 1))
    h = min(h, max(dst_h - y, 1))
    return {"x": x, "y": y, "w": w, "h": h}


def _slot_yellow_blue(image, box: dict[str, int]) -> tuple[float, float]:
    left = max(0, int(box["x"]))
    top = max(0, int(box["y"]))
    right = min(image.width, left + max(1, int(box["w"])))
    bottom = min(image.height, top + max(1, int(box["h"])))
    crop = image.crop((left, top, right, bottom))
    width, height = crop.size
    if width < 2 or height < 2:
        return 0.0, 0.0
    inset_x = max(1, int(width * 0.2))
    inset_y = max(1, int(height * 0.2))
    inner = crop.crop((inset_x, inset_y, width - inset_x, height - inset_y))
    iw, ih = inner.size
    step_x = max(1, iw // 24)
    step_y = max(1, ih // 24)
    pixels = inner.load()
    total = 0
    yellow = 0
    blue = 0
    for yy in range(0, ih, step_y):
        for xx in range(0, iw, step_x):
            red, green, blue_v = pixels[xx, yy][:3]
            hue, sat, val = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue_v / 255.0)
            total += 1
            if 0.10 <= hue <= 0.18 and sat >= 0.30 and val >= 0.35:
                yellow += 1
            elif 0.52 <= hue <= 0.72 and sat >= 0.28 and val >= 0.25:
                blue += 1
    if total <= 0:
        return 0.0, 0.0
    return yellow / total, blue / total


def _group_counts_line(tsums: list[dict[str, int]]) -> str:
    counts: dict[int, int] = {}
    for piece in tsums:
        group = int(piece.get("group") or 0)
        if group <= 0:
            continue
        counts[group] = counts.get(group, 0) + 1
    if not counts:
        return "この盤面の種類は分かっていません"
    sizes = [counts[group] for group in sorted(counts)]
    kinds = len(sizes)
    bodies = "、".join(f"{n}体" for n in sizes)
    return f"この盤面は{kinds}種類に分けた（多い順 {bodies}）"


def _pick_chain(
    predictor,
    rgb,
    pieces: list[dict[str, int]],
    candidates,
    unlike,
    skip_chains: set[tuple[tuple[int, int], ...]],
    say: StatusFn,
) -> tuple[list[dict[str, int]], list[int]]:
    found = [chain for chain in candidates(pieces, 8) if len(chain) >= MIN_CHAIN]
    found = [chain for chain in found if _chain_key(chain) not in skip_chains]
    if not found:
        return [], []
    say("候補 " + " / ".join(str(len(chain)) for chain in found))
    options = [len(item) for item in found]
    return max(found, key=len), options


def _chain_key(chain: list[dict[str, int]]) -> tuple[tuple[int, int], ...]:
    return tuple(sorted((int(piece["x"]) // 8, int(piece["y"]) // 8) for piece in chain))


def _chain_has_unlike(chain: list[dict[str, int]], unlike) -> bool:
    if not unlike:
        return False
    for index in range(1, len(chain)):
        if unlike_hit(chain[index - 1].get("_vec"), chain[index].get("_vec"), unlike):
            return True
    return False


def _leftover_len(
    pieces: list[dict[str, int]],
    chain: list[dict[str, int]],
    candidates,
) -> int:
    leftover = _remaining_after_erase(pieces, chain)
    found = [item for item in candidates(leftover, 1) if len(item) >= MIN_CHAIN]
    return max((len(item) for item in found), default=0)


def _board_key(tsums: list[dict[str, int]]) -> tuple[tuple[int, int], ...]:
    return tuple(
        sorted((int(piece["x"]) // 12, int(piece["y"]) // 12) for piece in tsums)
    )


def _skill_face(skill: dict[str, int]) -> dict[str, int]:
    width = max(1, int(skill["w"]))
    height = max(1, int(skill["h"]))
    return {
        "x": int(skill["x"] + width / 2),
        "y": int(skill["y"] + height / 2),
        "r": max(4, min(width, height) // 2),
        "kind": "tsum",
        "group": 0,
    }


def _mytsum_group(predictor, rgb, tsums: list[dict[str, int]], skill) -> int:
    if skill is None or not tsums:
        return 0
    reps: list[dict[str, int]] = []
    groups: list[int] = []
    seen: set[int] = set()
    for piece in tsums:
        group = int(piece.get("group") or 0)
        if group <= 0 or group in seen:
            continue
        seen.add(group)
        groups.append(group)
        reps.append(piece)
    if not reps:
        return 0
    vecs = _type_vectors(predictor, rgb, reps + [_skill_face(skill)])
    if not vecs or len(vecs) != len(reps) + 1:
        return 0
    skill_vec = vecs[-1]
    best_group = 0
    best_sim: float | None = None
    for group, vec in zip(groups, vecs[:-1]):
        sim = _cosine(skill_vec, vec)
        if best_sim is None or sim > best_sim:
            best_sim = sim
            best_group = group
    return best_group


def _attach_type_vecs(
    predictor,
    rgb,
    pieces: list[dict[str, int]],
) -> None:
    tsums = [piece for piece in pieces if str(piece.get("kind") or "") == "tsum"]
    if not tsums:
        return
    vecs = _type_vectors(predictor, rgb, tsums)
    if vecs is None:
        return
    for piece, vec in zip(tsums, vecs):
        piece["_vec"] = vec


def _type_vectors(predictor, rgb, pieces: list[dict[str, int]]):
    if not pieces or getattr(predictor, "type_model", None) is None:
        return None
    embed = getattr(predictor, "_tsum_embeddings", None)
    if embed is None or rgb is None:
        return None
    return embed(rgb, pieces)


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _draw_plan(
    image: QImage,
    pieces: list[dict[str, int]],
    chain: list[dict[str, int]],
    game: dict[str, int] | None,
    skill_fill: float | None = None,
) -> QImage:
    if image.isNull():
        return image
    left = top = 0
    board = image
    if game is not None:
        left = max(0, int(game["x"]))
        top = max(0, int(game["y"]))
        width = max(1, int(game["w"]))
        height = max(1, int(game["h"]))
        cropped = image.copy(QRect(left, top, min(width, image.width() - left), min(height, image.height() - top)))
        if not cropped.isNull():
            board = cropped
    painted = board.copy()
    painter = QPainter(painted)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    chain_ids = {id(piece) for piece in chain}
    for piece in pieces:
        x = int(piece["x"]) - left
        y = int(piece["y"]) - top
        radius = max(6, int(piece.get("r") or 12))
        if id(piece) in chain_ids:
            continue
        if str(piece.get("kind") or "") == "bomb":
            painter.setPen(QPen(QColor("#FF5C5C"), 2))
        else:
            painter.setPen(QPen(QColor("#FFE066"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(x, y), radius, radius)
    points = [(int(piece["x"]) - left, int(piece["y"]) - top, max(8, int(piece.get("r") or 16))) for piece in chain]
    if len(points) >= 2:
        painter.setPen(QPen(QColor("#7CFF7C"), max(4, points[0][2] // 3)))
        for (x0, y0, _r0), (x1, y1, _r1) in zip(points, points[1:]):
            painter.drawLine(x0, y0, x1, y1)
    font = QFont()
    font.setBold(True)
    painter.setFont(font)
    for index, (x, y, radius) in enumerate(points, start=1):
        painter.setPen(QPen(QColor("#1A1A1A"), 2))
        painter.setBrush(QColor("#7CFF7C"))
        painter.drawEllipse(QPoint(x, y), radius, radius)
        painter.setPen(QColor("#1A1A1A"))
        painter.drawText(QRect(x - radius, y - radius, radius * 2, radius * 2), Qt.AlignmentFlag.AlignCenter, str(index))
    if skill_fill is not None:
        label = f"{skill_fill:.2f}"
        fill_font = QFont()
        fill_font.setBold(True)
        fill_font.setPixelSize(max(64, painted.width() // 6))
        painter.setFont(fill_font)
        box = QRect(8, 8, max(1, painted.width() - 16), fill_font.pixelSize() + 24)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 180))
        painter.drawRect(box)
        painter.setPen(QColor("#FFE066"))
        painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
    painter.end()
    return painted


def _chain_key(chain: list[dict[str, int]]) -> frozenset[tuple[int, int]]:
    return frozenset(_chain_cells(chain))


def _chain_cells(chain: list[dict[str, int]]) -> set[tuple[int, int]]:
    return {(int(piece["x"]) // 16, int(piece["y"]) // 16) for piece in chain}


def _chain_too_similar(
    chain: list[dict[str, int]],
    used_keys: list[frozenset[tuple[int, int]]],
) -> bool:
    key = _chain_key(chain)
    for old in used_keys:
        if key == old or key <= old or old <= key:
            return True
        if len(key & old) >= 2:
            return True
    return False


def _prune_skip(
    skip_chains: list[frozenset[tuple[int, int]]],
    tsums: list[dict[str, int]],
) -> list[frozenset[tuple[int, int]]]:
    occupied = _chain_cells(tsums)
    return [key for key in skip_chains if key & occupied]

