from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Event, Lock

from PySide6.QtGui import QImage

from app.bluestacks import capture_play_frame, swipe_path, tap
from app.intro import _check_stop

_SKILL_SEC = 6.0
_MAX_CYCLES = 7
_BOARD_BACK = 8
_SORA_GAIN = 4
_LOOP_POINTS = 8


def run_namine_skill(
    *,
    predict: Callable,
    game: dict[str, int] | None,
    my_group: int,
    before_pieces: list[dict],
    say: Callable[[str], None],
    stop: Event | None,
    watch_hit: Event | None,
    preview: Callable[[QImage], None] | None,
    draw: Callable,
    gpu_lock: Lock,
    skill_lamp: Callable[[bool], None] | None = None,
    find_my: Callable[[QImage, list], int] | None = None,
) -> int | None:
    deadline = time.time() + _SKILL_SEC
    before = _counts(before_pieces, game)
    saw_face = False
    cycles = 0
    my = int(my_group or 0)
    sora = 0
    lit = False

    def set_lamp(on: bool) -> None:
        nonlocal lit
        if skill_lamp is None or on == lit:
            return
        lit = on
        skill_lamp(on)

    def halted() -> bool:
        return (stop is not None and stop.is_set()) or (
            watch_hit is not None and watch_hit.is_set()
        )

    full_boards = 0
    started = False
    try:
        while time.time() < deadline and cycles < _MAX_CYCLES:
            _check_stop(stop)
            if halted():
                return None if not started else cycles
            try:
                image = capture_play_frame()
            except Exception:
                continue
            if image is None or image.isNull():
                continue
            rgb = _rgb(image)
            if rgb is None:
                continue
            with gpu_lock:
                pieces = predict(rgb) or []
            tsums = _tsums(pieces, game)
            if len(tsums) < _BOARD_BACK:
                if not started:
                    started = True
                    deadline = time.time() + _SKILL_SEC
                    say("スキル中")
                    set_lamp(True)
                saw_face = True
                continue
            if not started:
                full_boards += 1
                if full_boards >= 2:
                    return None
                continue
            if my <= 0 and find_my is not None:
                found = int(find_my(image, pieces) or 0)
                if found > 0:
                    my = found
            counts = _counts(pieces, game)
            grown = _grown(before, counts, my)
            if not saw_face and grown < _SORA_GAIN:
                continue
            if sora <= 0:
                sora = _sora_group(before, counts, my, saw_face or grown >= _SORA_GAIN)
            if sora <= 0 or my <= 0:
                continue
            chain = _loose_chain(tsums, my, sora)
            if len(chain) < 3:
                continue
            bombs = _bombs(pieces, game)
            if preview is not None:
                preview(draw(image, pieces, chain, game))
            how = swipe_path(
                [(int(piece["x"]), int(piece["y"])) for piece in chain],
                screen_w=image.width(),
                screen_h=image.height(),
                stop=stop,
                abort=watch_hit,
            )
            if how in {"停止", "点が3未満", "なぞり失敗"}:
                if how == "停止":
                    return cycles
                continue
            say(how)
            cycles += 1
            say(f"ナミネ {cycles}回")
            if bombs and not halted():
                bomb = max(bombs, key=lambda piece: int(piece.get("r") or 0))
                say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
                tap(
                    int(bomb["x"]),
                    int(bomb["y"]),
                    hold_ms=40,
                    screen_w=image.width(),
                    screen_h=image.height(),
                )
        return None if not started else cycles
    finally:
        set_lamp(False)


def _tsums(pieces: list[dict], game: dict[str, int] | None) -> list[dict]:
    return [
        piece
        for piece in pieces
        if str(piece.get("kind") or "") in {"tsum", "big"} and _inside(piece, game)
    ]


def _bombs(pieces: list[dict], game: dict[str, int] | None) -> list[dict]:
    return [
        piece
        for piece in pieces
        if str(piece.get("kind") or "") == "bomb" and _inside(piece, game)
    ]


def _inside(piece: dict, game: dict[str, int] | None) -> bool:
    if game is None:
        return True
    x = int(piece["x"])
    y = int(piece["y"])
    left = int(game["x"])
    top = int(game["y"])
    return left <= x < left + int(game["w"]) and top <= y < top + int(game["h"])


def _counts(pieces: list[dict], game: dict[str, int] | None) -> dict[int, int]:
    counts: dict[int, int] = {}
    for piece in _tsums(pieces, game):
        group = int(piece.get("group") or 0)
        if group <= 0:
            continue
        counts[group] = counts.get(group, 0) + 1
    return counts


def _grown(before: dict[int, int], after: dict[int, int], my_group: int) -> int:
    best = 0
    for group, count in after.items():
        if group <= 0 or group == my_group:
            continue
        gain = count - before.get(group, 0)
        if gain > best:
            best = gain
    return best


def _sora_group(
    before: dict[int, int],
    after: dict[int, int],
    my_group: int,
    after_face: bool,
) -> int:
    best = 0
    best_gain = 0
    for group, count in after.items():
        if group <= 0 or group == my_group:
            continue
        gain = count - before.get(group, 0)
        if gain > best_gain:
            best = group
            best_gain = gain
    if best_gain >= _SORA_GAIN:
        return best
    if not after_face:
        return 0
    largest = 0
    size = 0
    for group, count in after.items():
        if group <= 0 or group == my_group:
            continue
        if count > size:
            largest = group
            size = count
    if size >= 3:
        return largest
    return 0


def _loose_chain(tsums: list[dict], my_group: int, sora_group: int) -> list[dict]:
    nodes = [
        piece
        for piece in tsums
        if int(piece.get("group") or 0) in {my_group, sora_group}
    ]
    if len(nodes) < 3:
        return []
    cx = sum(int(piece["x"]) for piece in nodes) / len(nodes)
    cy = sum(int(piece["y"]) for piece in nodes) / len(nodes)
    nodes.sort(key=lambda piece: math.atan2(int(piece["y"]) - cy, int(piece["x"]) - cx))
    if len(nodes) <= _LOOP_POINTS:
        return nodes
    step = len(nodes) / _LOOP_POINTS
    return [nodes[int(index * step)] for index in range(_LOOP_POINTS)]


def _rgb(image: QImage):
    from app.play import _qimage_rgb

    return _qimage_rgb(image)
