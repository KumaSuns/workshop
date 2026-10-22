from __future__ import annotations

import time
from collections.abc import Callable
from threading import Event, Lock

from PySide6.QtGui import QImage

from app.bluestacks import capture_play_frame, swipe_path, tap
from app.intro import _check_stop

SayFn = Callable[[str], None]
_CHAINS = 10
_MIN_CHAIN = 8
_SKILL_SEC = 3.8
_POINT_S = 0.002
_CENTER_S = 0.006


def _untraced(pieces: list[dict], done: list[tuple[int, int, int]]) -> list[dict]:
    fresh: list[dict] = []
    for piece in pieces:
        x = int(piece["x"])
        y = int(piece["y"])
        radius = max(8, int(piece.get("r") or 16))
        if any((x - dx) ** 2 + (y - dy) ** 2 <= max(radius, dr) ** 2 for dx, dy, dr in done):
            continue
        fresh.append(piece)
    return fresh


def _bombs(pieces: list[dict]) -> list[dict]:
    return [piece for piece in pieces if str(piece.get("kind") or "") == "bomb"]


def _on_bomb(piece: dict, bombs: list[dict]) -> bool:
    x = int(piece["x"])
    y = int(piece["y"])
    for bomb in bombs:
        reach = max(8, int(bomb.get("r") or 16))
        if (x - int(bomb["x"])) ** 2 + (y - int(bomb["y"])) ** 2 <= reach * reach:
            return True
    return False


def _spacing(pieces: list[dict]) -> float:
    dists: list[float] = []
    for index, piece in enumerate(pieces):
        x = int(piece["x"])
        y = int(piece["y"])
        nearest = None
        for other_index, other in enumerate(pieces):
            if index == other_index:
                continue
            dist = ((x - int(other["x"])) ** 2 + (y - int(other["y"])) ** 2) ** 0.5
            if nearest is None or dist < nearest:
                nearest = dist
        if nearest:
            dists.append(nearest)
    if not dists:
        return 32.0
    dists.sort()
    return dists[len(dists) // 2]


def _bottom_row(pieces: list[dict], done: list[tuple[int, int, int]]) -> list[dict]:
    bombs = _bombs(pieces)
    fresh = [
        piece
        for piece in _untraced(pieces, done)
        if str(piece.get("kind") or "") in {"tsum", "big"} and not _on_bomb(piece, bombs)
    ]
    if len(fresh) < _MIN_CHAIN:
        return []
    spacing = _spacing(fresh)
    columns: dict[int, list[dict]] = {}
    for piece in fresh:
        column = int(int(piece["x"]) / spacing)
        columns.setdefault(column, []).append(piece)
    row: list[dict] = []
    allowance = spacing * 0.5
    for group in columns.values():
        bottom = max(int(piece["y"]) for piece in group)
        for piece in group:
            if bottom - int(piece["y"]) <= allowance:
                row.append(piece)
    if len(row) < _MIN_CHAIN:
        return []
    return row


def _occupied(pieces: list[dict], spot: tuple[int, int, int]) -> bool:
    dx, dy, dr = spot
    for piece in pieces:
        if str(piece.get("kind") or "") not in {"tsum", "big"}:
            continue
        x = int(piece["x"])
        y = int(piece["y"])
        radius = max(8, int(piece.get("r") or 16))
        if (x - dx) ** 2 + (y - dy) ** 2 <= max(radius, dr) ** 2:
            return True
    return False


def _strokes(pieces: list[dict], done: list[tuple[int, int, int]]) -> list[list[dict]]:
    row = _bottom_row(pieces, done)
    if not row:
        return []
    return [row]


def _arc(path: list[dict]) -> list[tuple[int, int]]:
    if len(path) < 2:
        return []
    start = path[0]
    end = path[-1]
    radius = max(max(8, int(piece.get("r") or 16)) for piece in path)
    lift = radius / 2
    x0 = int(start["x"])
    y0 = int(start["y"])
    x1 = int(end["x"])
    y1 = int(end["y"])
    samples = 7
    points: list[tuple[int, int]] = []
    for index in range(samples):
        t = index / (samples - 1)
        bow = 4 * t * (1 - t)
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t + lift * bow
        points.append((int(round(x)), int(round(y))))
    return points


def _break_bombs(
    predict: Callable,
    game: dict[str, int] | None,
    say: SayFn,
    stop: Event | None,
    watch_hit: Event | None,
    gpu_lock: Lock,
) -> int:
    taps = 0
    skip: set[tuple[int, int]] = set()
    while True:
        _check_stop(stop)
        if watch_hit is not None and watch_hit.is_set():
            return taps
        try:
            image = capture_play_frame()
        except Exception:
            time.sleep(0.02)
            continue
        if image.isNull():
            time.sleep(0.02)
            continue
        from app.play import _qimage_rgb

        rgb = _qimage_rgb(image)
        if rgb is None:
            time.sleep(0.02)
            continue
        with gpu_lock:
            pieces = predict(rgb)
        bombs = [piece for piece in pieces if str(piece.get("kind") or "") == "bomb"]
        pending = [
            piece
            for piece in bombs
            if (int(piece["x"]) // 24, int(piece["y"]) // 24) not in skip
        ]
        if not pending:
            return taps
        say(f"ボム {len(bombs)}")
        for bomb in pending:
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
            skip.add((int(bomb["x"]) // 24, int(bomb["y"]) // 24))
            taps += 1


def run_cinderella_skill(
    *,
    predict: Callable,
    game: dict[str, int] | None,
    say: SayFn,
    stop: Event | None,
    watch_hit: Event | None,
    preview: Callable[[QImage], None] | None,
    draw: Callable,
    gpu_lock: Lock,
    skill_lamp: Callable[[bool], None] | None = None,
) -> int:
    del preview, draw, game
    swipes = 0
    direction = 0
    done: list[tuple[int, int, int]] = []
    skill_ends = time.time() + _SKILL_SEC
    if skill_lamp is not None:
        skill_lamp(True)
    say("スキル中")
    try:
        while swipes < _CHAINS and time.time() < skill_ends:
            _check_stop(stop)
            if watch_hit is not None and watch_hit.is_set():
                return swipes
            try:
                image = capture_play_frame()
            except Exception:
                time.sleep(0.02)
                continue
            if image.isNull():
                time.sleep(0.02)
                continue
            from app.play import _qimage_rgb

            rgb = _qimage_rgb(image)
            if rgb is None:
                time.sleep(0.02)
                continue
            with gpu_lock:
                pieces = predict(rgb)
            done = [spot for spot in done if _occupied(pieces, spot)]
            planned: list[list[dict]] = []
            strokes = _strokes(pieces, done)
            if strokes and swipes < _CHAINS:
                stroke = strokes[0]
                stroke.sort(key=lambda piece: int(piece["x"]), reverse=direction % 2 == 1)
                planned.append(stroke)
            if not planned:
                time.sleep(0.02)
                continue
            for path in planned:
                _check_stop(stop)
                if watch_hit is not None and watch_hit.is_set():
                    return swipes
                points = _arc(path)
                say(f"なぞり {len(path)}体 {swipes + 1}/{_CHAINS}")
                swipe_path(
                    points,
                    screen_w=image.width(),
                    screen_h=image.height(),
                    stop=stop,
                    abort=watch_hit,
                    point_s=_POINT_S,
                    center_s=_CENTER_S,
                )
                for piece in path:
                    done.append((int(piece["x"]), int(piece["y"]), max(8, int(piece.get("r") or 16))))
                direction += 1
                swipes += 1
        _break_bombs(predict, None, say, stop, watch_hit, gpu_lock)
        return swipes
    finally:
        if skill_lamp is not None:
            skill_lamp(False)
