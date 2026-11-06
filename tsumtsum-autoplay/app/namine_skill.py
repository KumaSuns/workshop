from __future__ import annotations

import math
from collections.abc import Callable
from threading import Event

from PySide6.QtGui import QImage

from app.bluestacks import swipe_path, tap

_SKILL_SEC = 6.0
_CIRCLE_SEC = 0.4
_TURNS = 2
_POINTS_PER_TURN = 16
_CORNER_Y = 0.55
_CORNER_X = 0.38


def namine_skill_step(
    *,
    image: QImage,
    pieces: list[dict],
    game: dict[str, int] | None,
    my_group: int,
    say: Callable[[str], None],
    stop: Event | None,
    watch_hit: Event | None,
    bombs_ready: list[dict] | None = None,
) -> tuple[bool, bool]:
    if image is None or image.isNull():
        return False, False
    if (stop is not None and stop.is_set()) or (
        watch_hit is not None and watch_hit.is_set()
    ):
        return False, False
    tsums = _tsums(pieces, game)
    grab = _grab_target(tsums, my_group, game, allow_namine=True)
    if grab is None:
        return False, False
    path = _circle_path(grab, game, image.width(), image.height())
    if len(path) < 3:
        return False, False
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
        return False, False
    say("円")
    bombs = _bombs(pieces, game) or list(bombs_ready or [])
    if bombs:
        bomb = max(bombs, key=lambda piece: int(piece.get("r") or 0))
        say(f"ボムをタップ {int(bomb['x'])},{int(bomb['y'])}")
        tap(
            int(bomb["x"]),
            int(bomb["y"]),
            screen_w=image.width(),
            screen_h=image.height(),
        )
        return True, True
    return True, False


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


def _is_sora(piece: dict) -> bool:
    name = str(piece.get("tsum_name") or "").strip()
    folded = name.casefold().replace(" ", "")
    return name == "ソラ" or folded == "sora"


def _is_namine(piece: dict, my_group: int) -> bool:
    if my_group > 0 and int(piece.get("group") or 0) == my_group:
        return True
    name = str(piece.get("tsum_name") or "").strip()
    return name == "ナミネ" or name.casefold() == "namine"


def _namine_face(rgb, game: dict[str, int] | None) -> bool:
    # 盤面の真ん中に出る大きい顔
    if rgb is None:
        return False
    width, height = rgb.size
    if game is None:
        left, top, box_w, box_h = 0, 0, width, height
    else:
        left = int(game["x"])
        top = int(game["y"])
        box_w = max(1, int(game["w"]))
        box_h = max(1, int(game["h"]))
    x0 = max(0, min(width - 1, left + int(box_w * 0.20)))
    x1 = max(x0 + 1, min(width, left + int(box_w * 0.80)))
    y0 = max(0, min(height - 1, top + int(box_h * 0.22)))
    y1 = max(y0 + 1, min(height, top + int(box_h * 0.78)))
    crop_w = x1 - x0
    crop_h = y1 - y0
    if crop_w < 8 or crop_h < 8:
        return False
    pixels = rgb.load()
    step = 2
    cols = (crop_w + step - 1) // step
    rows = (crop_h + step - 1) // step
    skin: set[tuple[int, int]] = set()
    for gy in range(rows):
        py = y0 + gy * step
        if py >= height:
            break
        for gx in range(cols):
            px = x0 + gx * step
            if px >= width:
                break
            red, green, blue = pixels[px, py]
            if (
                red > 220
                and 150 < green < 230
                and 130 < blue < 220
                and (red - green) > 18
                and (red - blue) > 35
                and (green - blue) < 55
            ):
                skin.add((gx, gy))
    if not skin:
        return False
    seen: set[tuple[int, int]] = set()
    best_area = 0
    best_w = 0
    best_h = 0
    for start in skin:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        area = 0
        min_x = max_x = start[0]
        min_y = max_y = start[1]
        while stack:
            cx, cy = stack.pop()
            area += 1
            if cx < min_x:
                min_x = cx
            if cx > max_x:
                max_x = cx
            if cy < min_y:
                min_y = cy
            if cy > max_y:
                max_y = cy
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                point = (nx, ny)
                if point in skin and point not in seen:
                    seen.add(point)
                    stack.append(point)
        if area > best_area:
            best_area = area
            best_w = max_x - min_x + 1
            best_h = max_y - min_y + 1
    return best_w / cols >= 0.40 and best_h / rows >= 0.22


def _others_became_sora(tsums: list[dict], my_group: int) -> bool:
    saw_sora = False
    for piece in tsums:
        if _is_namine(piece, my_group):
            continue
        name = str(piece.get("tsum_name") or "").strip()
        if not name:
            continue
        if _is_sora(piece):
            saw_sora = True
            continue
        return False
    return saw_sora


def _other_kind(tsums: list[dict], my_group: int) -> bool:
    for piece in tsums:
        if _is_namine(piece, my_group) or _is_sora(piece):
            continue
        if str(piece.get("tsum_name") or "").strip():
            return True
    return False


def _grab_target(
    tsums: list[dict],
    my_group: int,
    game: dict[str, int] | None,
    allow_namine: bool,
) -> dict | None:
    soras = [piece for piece in tsums if _is_sora(piece)]
    if soras:
        picked = _best_place(soras, game)
        if picked is not None:
            return picked
    if not allow_namine:
        return None
    namines = [piece for piece in tsums if _is_namine(piece, my_group)]
    if not namines:
        return None
    return _best_place(namines, game)


def _best_place(picked: list[dict], game: dict[str, int] | None) -> dict | None:
    if not picked:
        return None
    if game is None:
        return max(picked, key=lambda piece: int(piece["y"]))
    left = int(game["x"])
    top = int(game["y"])
    width = max(1, int(game["w"]))
    height = max(1, int(game["h"]))

    def place(piece: dict) -> tuple[float, float]:
        rx = (int(piece["x"]) - left) / width
        ry = (int(piece["y"]) - top) / height
        return rx, ry

    def score(piece: dict) -> float:
        rx, ry = place(piece)
        edge = rx if rx <= 0.5 else 1.0 - rx
        return ry + (1.0 - edge)

    corners = []
    for piece in picked:
        rx, ry = place(piece)
        if ry < _CORNER_Y:
            continue
        if rx > _CORNER_X and rx < 1.0 - _CORNER_X:
            continue
        corners.append(piece)
    pool = corners or picked
    best: dict | None = None
    best_score = -1.0
    for piece in pool:
        value = score(piece)
        if value > best_score:
            best = piece
            best_score = value
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
    pad = 1
    cx = left + width / 2
    cy = top + height / 2
    rx = max(1.0, (width / 2) - pad)
    ry = max(1.0, (height / 2) - pad)
    sx = int(grab["x"])
    sy = int(grab["y"])
    start_ang = math.atan2((sy - cy) / ry, (sx - cx) / rx)
    path: list[tuple[int, int]] = [(sx, sy)]
    total = _TURNS * _POINTS_PER_TURN
    for index in range(0, total + 1):
        ang = start_ang + (math.tau * _TURNS) * (index / total)
        x = int(round(cx + math.cos(ang) * rx))
        y = int(round(cy + math.sin(ang) * ry))
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
