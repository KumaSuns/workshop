from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event, Lock

from PySide6.QtGui import QImage

from app.bluestacks import capture_play_frame, swipe_path, tap
from app.intro import _check_stop

_SKILL_SEC = 12.0
_BOMB_MANY = 3
_BOMB_GAP = 1.0
_SHOW_FRAMES = 3


def run_cruella_skill(
    *,
    predict: Callable,
    game: dict[str, int] | None,
    say: Callable[[str], None],
    stop: Event | None,
    watch_hit: Event | None,
    preview: Callable[[QImage], None] | None,
    draw: Callable,
    gpu_lock: Lock,
    find_three: Callable[[list], list],
    skill_lamp: Callable[[bool], None] | None = None,
) -> tuple[int, int]:
    del preview, draw
    deadline = 0.0
    ready = False
    show_frames = 0
    swipes = 0
    taps = 0
    last_bomb = 0.0
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

    try:
        while not ready or time.time() < deadline:
            _check_stop(stop)
            if halted():
                return swipes, taps
            try:
                image = capture_play_frame()
            except Exception:
                time.sleep(0.03)
                continue
            if image is None or image.isNull():
                time.sleep(0.03)
                continue
            from app.play import _qimage_rgb

            rgb = _qimage_rgb(image)
            if rgb is None:
                time.sleep(0.03)
                continue
            with gpu_lock:
                pieces = predict(rgb) or []
            now = time.time()
            chains = find_three(pieces)
            if not ready:
                if not chains:
                    show_frames += 1
                    time.sleep(0.03)
                    continue
                if show_frames < _SHOW_FRAMES:
                    show_frames = 0
                    time.sleep(0.03)
                    continue
                ready = True
                deadline = time.time() + _SKILL_SEC
                say("スキル中")
                set_lamp(True)
            elif time.time() >= deadline:
                break
            for chain in chains:
                _check_stop(stop)
                if halted() or time.time() >= deadline:
                    break
                how = swipe_path(
                    [(int(piece["x"]), int(piece["y"])) for piece in chain],
                    screen_w=image.width(),
                    screen_h=image.height(),
                    stop=stop,
                    abort=watch_hit,
                )
                if how in {"停止", "点が3未満", "なぞり失敗"}:
                    if how == "停止":
                        return swipes, taps
                    continue
                say(how)
                swipes += 1
            if halted() or time.time() >= deadline:
                break
            if chains:
                continue
            bombs = _bombs(pieces, game)
            if len(bombs) >= _BOMB_MANY and now - last_bomb >= _BOMB_GAP:
                bomb = max(bombs, key=lambda piece: int(piece.get("r") or 0))
                say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
                tap(
                    int(bomb["x"]),
                    int(bomb["y"]),
                    hold_ms=40,
                    screen_w=image.width(),
                    screen_h=image.height(),
                )
                taps += 1
                last_bomb = time.time()
        if halted():
            return swipes, taps
        taps += _break_fast_leave_one(predict, game, say, stop, watch_hit, gpu_lock)
        say("スキル中が終わりました")
        return swipes, taps
    finally:
        set_lamp(False)


def _bombs(pieces: list[dict], game: dict[str, int] | None) -> list[dict]:
    found = []
    for piece in pieces:
        if str(piece.get("kind") or "") != "bomb":
            continue
        if not _inside(piece, game):
            continue
        found.append(piece)
    return found


def _inside(piece: dict, game: dict[str, int] | None) -> bool:
    if game is None:
        return True
    x = int(piece["x"])
    y = int(piece["y"])
    left = int(game["x"])
    top = int(game["y"])
    return left <= x < left + int(game["w"]) and top <= y < top + int(game["h"])


def _cell(piece: dict) -> tuple[int, int]:
    return int(piece["x"]) // 24, int(piece["y"]) // 24


def _break_fast_leave_one(
    predict: Callable,
    game: dict[str, int] | None,
    say: Callable[[str], None],
    stop: Event | None,
    watch_hit: Event | None,
    gpu_lock: Lock,
) -> int:
    skip: set[tuple[int, int]] = set()
    taps = 0
    calm = 0
    while calm < 2:
        _check_stop(stop)
        if (stop is not None and stop.is_set()) or (
            watch_hit is not None and watch_hit.is_set()
        ):
            return taps
        try:
            image = capture_play_frame()
        except Exception:
            time.sleep(0.02)
            continue
        if image is None or image.isNull():
            time.sleep(0.02)
            continue
        from app.play import _qimage_rgb

        rgb = _qimage_rgb(image)
        if rgb is None:
            time.sleep(0.02)
            continue
        with gpu_lock:
            pieces = predict(rgb) or []
        bombs = _bombs(pieces, game)
        if len(bombs) <= 1:
            calm += 1
            time.sleep(0.05)
            continue
        calm = 0
        extra = [
            piece
            for piece in sorted(bombs, key=lambda piece: int(piece.get("r") or 0), reverse=True)
            if _cell(piece) not in skip
        ][: len(bombs) - 1]
        if not extra:
            return taps
        say(f"ボム {len(bombs)}")
        for bomb in extra:
            _check_stop(stop)
            if watch_hit is not None and watch_hit.is_set():
                return taps
            say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
            tap(
                int(bomb["x"]),
                int(bomb["y"]),
                hold_ms=40,
                screen_w=image.width(),
                screen_h=image.height(),
            )
            skip.add(_cell(bomb))
            taps += 1
        time.sleep(0.02)
    return taps
