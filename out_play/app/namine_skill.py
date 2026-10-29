from __future__ import annotations

import math
import time
from collections.abc import Callable
from threading import Event, Lock

from PySide6.QtGui import QImage

from app.bluestacks import capture_play_frame, swipe_path, tap
from app.intro import _check_stop

_SKILL_SEC = 6.0
_MAX_CYCLES = 5
_BOARD_BACK = 8
_SORA_GAIN = 4
_CIRCLE_SEC = 0.4
_TURNS = 2
_POINTS_PER_TURN = 16
_RADIUS_FRAC = 0.42
_CORNER_Y = 0.55
_CORNER_X = 0.38


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
    ready = False

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
        while time.time() < deadline and cycles < _MAX_CYCLES:
            _check_stop(stop)
            if halted():
                return cycles
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
                if not ready:
                    ready = True
                    deadline = time.time() + _SKILL_SEC
                    say("スキル中")
                    set_lamp(True)
                saw_face = True
                continue
            if my <= 0 and find_my is not None:
                found = int(find_my(image, pieces) or 0)
                if found > 0:
                    my = found
            counts = _counts(pieces, game)
            grown = _grown(before, counts, my)
            # スキル中はナミネ以外がランダムでソラになるので、毎フレーム見直す
            sora = _sora_group(
                before, counts, my, saw_face or ready or grown >= _SORA_GAIN
            )
            if not ready:
                if grown >= _SORA_GAIN or (saw_face and (my > 0 or sora > 0)):
                    ready = True
                    deadline = time.time() + _SKILL_SEC
                    say("スキル中")
                    set_lamp(True)
                else:
                    continue
            if sora <= 0 and my <= 0:
                continue
            bombs = _bombs(pieces, game)
            if not bombs:
                chain = _three_chain(tsums)
                if chain is None:
                    continue
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
                say("3チェーン")
                if halted():
                    return cycles
                fresh = _fresh_board(predict, game, gpu_lock)
                if fresh is None:
                    continue
                image, pieces, tsums = fresh
                if my <= 0 and find_my is not None:
                    found = int(find_my(image, pieces) or 0)
                    if found > 0:
                        my = found
                counts = _counts(pieces, game)
                grown = _grown(before, counts, my)
                sora = _sora_group(
                    before, counts, my, True
                )
                bombs = _bombs(pieces, game)
            grab = _corner_grab(tsums, my, sora, game)
            if grab is None:
                continue
            path = _circle_path(grab, game, image.width(), image.height())
            if len(path) < 3:
                continue
            wait = _point_s_for(path, _CIRCLE_SEC)
            how = swipe_path(
                path,
                screen_w=image.width(),
                screen_h=image.height(),
                stop=stop,
                abort=watch_hit,
                point_s=wait,
                center_s=wait,
            )
            if how in {"停止", "点が3未満", "なぞり失敗"}:
                if how == "停止":
                    return cycles
                continue
            say("円")
            cycles += 1
            say(f"ナミネ {cycles}回")
            if halted():
                return cycles
            live_bombs = bombs
            if len(live_bombs) <= 1:
                live_bombs = _fresh_bombs(predict, game, gpu_lock)
            if len(live_bombs) > 1:
                bomb = max(live_bombs, key=lambda piece: int(piece.get("r") or 0))
                say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
                tap(
                    int(bomb["x"]),
                    int(bomb["y"]),
                    hold_ms=40,
                    screen_w=image.width(),
                    screen_h=image.height(),
                )
        return cycles
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
    # スキル中はナミネ以外が順にソラへ変わるので、増えた種類をソラとみる
    if best_gain > 0:
        return best
    largest = 0
    size = 0
    for group, count in after.items():
        if group <= 0 or group == my_group:
            continue
        if count > size:
            largest = group
            size = count
    if size >= 1:
        return largest
    return 0


def _three_chain(tsums: list[dict]) -> list[dict] | None:
    if len(tsums) < 3:
        return None
    radii = [max(4, int(piece.get("r") or 12)) for piece in tsums]
    typical = sorted(radii)[len(radii) // 2]
    reach = typical * 2.6
    n = len(tsums)
    links: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        gi = int(tsums[i].get("group") or 0)
        if gi <= 0:
            continue
        xi, yi = int(tsums[i]["x"]), int(tsums[i]["y"])
        for j in range(i + 1, n):
            if int(tsums[j].get("group") or 0) != gi:
                continue
            dist = math.hypot(int(tsums[j]["x"]) - xi, int(tsums[j]["y"]) - yi)
            if dist > reach:
                continue
            links[i].append(j)
            links[j].append(i)

    def walk(start: int) -> list[int] | None:
        stack = [(start, [start])]
        while stack:
            node, path = stack.pop()
            if len(path) >= 3:
                return path[:3]
            for nxt in links[node]:
                if nxt in path:
                    continue
                stack.append((nxt, path + [nxt]))
        return None

    best: list[dict] | None = None
    for index in range(n):
        found = walk(index)
        if found is None:
            continue
        chain = [tsums[i] for i in found]
        if best is None or len(chain) > len(best):
            best = chain
            if len(best) >= 3:
                return best
    return best


def _fresh_bombs(predict: Callable, game: dict[str, int] | None, gpu_lock: Lock) -> list[dict]:
    fresh = _fresh_board(predict, game, gpu_lock)
    if fresh is None:
        return []
    _image, pieces, _tsums = fresh
    return _bombs(pieces, game)


def _fresh_board(
    predict: Callable,
    game: dict[str, int] | None,
    gpu_lock: Lock,
) -> tuple[QImage, list[dict], list[dict]] | None:
    try:
        image = capture_play_frame()
    except Exception:
        return None
    if image is None or image.isNull():
        return None
    rgb = _rgb(image)
    if rgb is None:
        return None
    with gpu_lock:
        pieces = predict(rgb) or []
    return image, pieces, _tsums(pieces, game)


def _corner_grab(
    tsums: list[dict],
    my_group: int,
    sora_group: int,
    game: dict[str, int] | None,
) -> dict | None:
    wanted = {g for g in (my_group, sora_group) if g > 0}
    if not wanted:
        return None
    if game is None:
        return None
    left = int(game["x"])
    top = int(game["y"])
    width = max(1, int(game["w"]))
    height = max(1, int(game["h"]))
    best: dict | None = None
    best_score = -1.0
    for piece in tsums:
        if int(piece.get("group") or 0) not in wanted:
            continue
        x = int(piece["x"])
        y = int(piece["y"])
        rx = (x - left) / width
        ry = (y - top) / height
        if ry < _CORNER_Y:
            continue
        if rx > _CORNER_X and rx < 1.0 - _CORNER_X:
            continue
        edge = rx if rx <= 0.5 else 1.0 - rx
        score = ry + (1.0 - edge)
        if score > best_score:
            best = piece
            best_score = score
    return best


def _board_box(
    game: dict[str, int] | None, screen_w: int, screen_h: int
) -> tuple[int, int, int, int]:
    if game is None:
        return 0, 0, max(1, screen_w), max(1, screen_h)
    return (
        int(game["x"]),
        int(game["y"]),
        max(1, int(game["w"])),
        max(1, int(game["h"])),
    )


def _circle_path(
    grab: dict,
    game: dict[str, int] | None,
    screen_w: int,
    screen_h: int,
) -> list[tuple[int, int]]:
    # ツム同士をつなぐ経路ではなく、つかんだ位置から盤面内に円を描く
    left, top, width, height = _board_box(game, screen_w, screen_h)
    pad = max(4, int(min(width, height) * 0.04))
    cx = left + width / 2
    cy = top + height / 2
    radius = min(width, height) * _RADIUS_FRAC
    radius = min(radius, (width / 2) - pad, (height / 2) - pad)
    sx = int(grab["x"])
    sy = int(grab["y"])
    start_ang = math.atan2(sy - cy, sx - cx)
    path: list[tuple[int, int]] = [(sx, sy)]
    total = _TURNS * _POINTS_PER_TURN
    for index in range(0, total + 1):
        ang = start_ang + (math.tau * _TURNS) * (index / total)
        x = int(round(cx + math.cos(ang) * radius))
        y = int(round(cy + math.sin(ang) * radius))
        x = min(max(left + pad, x), left + width - pad - 1)
        y = min(max(top + pad, y), top + height - pad - 1)
        if path and path[-1] == (x, y):
            continue
        path.append((x, y))
    return path


def _point_s_for(points: list[tuple[int, int]], seconds: float) -> float:
    length = 0.0
    for index in range(1, len(points)):
        x0, y0 = points[index - 1]
        x1, y1 = points[index]
        length += math.hypot(x1 - x0, y1 - y0)
    steps = max(1, int(length / 14))
    usable = max(0.05, float(seconds) - 0.06)
    return usable / steps


def _rgb(image: QImage):
    from app.play import _qimage_rgb

    return _qimage_rgb(image)
