from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from app.bluestacks import capture_play_frame, swipe_path, tap
from app.intro import _check_stop
from app.paths import APP_ROOT

_DURING_DIR = (
    APP_ROOT.parent
    / "video-frame-extractor"
    / "app"
    / "assets"
    / "images"
    / "skills"
    / "Coronation_Elsa"
)
_WORK_W = 66
_WORK_H = 143
_SKILL_SEC = 10.0
_STABLE_VAR = 150.0

_style_ready = False
_style_idx: list[int] = []
_style_mean: bytearray = bytearray()
_style_limit = 0.0


def run_elsa_skill(
    *,
    predict: Callable,
    game: dict[str, int] | None,
    say: Callable[[str], None],
    stop: Event | None,
    watch_hit: Event | None,
    preview: Callable[[QImage], None] | None,
    draw: Callable,
    gpu_lock: Lock,
) -> int:
    _load_style()
    deadline = time.time() + _SKILL_SEC
    seen = False
    missed = 0
    swipes = 0
    say("スキル中")
    while time.time() < deadline:
        _check_stop(stop)
        if watch_hit is not None and watch_hit.is_set():
            return swipes
        try:
            image = capture_play_frame()
        except Exception:
            _erase_wait(stop)
            continue
        if image.isNull():
            _erase_wait(stop)
            continue
        if _style_idx and _outside_matches(image):
            seen = True
            missed = 0
        elif seen:
            missed += 1
            if missed >= 3:
                say("スキル中が終わりました")
                return swipes
        rgb = _rgb(image)
        if rgb is None:
            continue
        with gpu_lock:
            pieces = predict(rgb)
        tsums = [piece for piece in pieces if _is_tsum(piece) and int(piece.get("group") or 0) > 0]
        alive = set(range(len(tsums)))
        bounds = _board_bounds(tsums)
        frozen: list[dict[str, int]] = []
        halted = False
        while alive:
            _check_stop(stop)
            if watch_hit is not None and watch_hit.is_set():
                halted = True
                break
            if time.time() >= deadline:
                halted = True
                break
            picked = _pick(tsums, alive, bounds)
            if picked is None:
                break
            chain, ice = picked
            if preview is not None:
                preview(draw(image, pieces, chain, game))
            points = [(int(piece["x"]), int(piece["y"])) for piece in chain]
            how = swipe_path(
                points,
                screen_w=image.width(),
                screen_h=image.height(),
                stop=stop,
                abort=watch_hit,
            )
            if how in {"停止", "点が3未満", "なぞり失敗"}:
                break
            say(how)
            swipes += 1
            frozen.extend(ice)
            alive -= {index for index, piece in enumerate(tsums) if piece in ice}
        _tap_ice(frozen, image, say, stop)
        if halted:
            return swipes
        _erase_wait(stop)
    say("スキル中が終わりました")
    return swipes


def _is_tsum(piece: dict) -> bool:
    return str(piece.get("kind") or "") in {"tsum", "big"}


def _load_style() -> None:
    global _style_ready, _style_idx, _style_mean, _style_limit
    if _style_ready:
        return
    _style_ready = True
    shots = [_sample(QImage(str(path))) for path in sorted(_DURING_DIR.glob("IMG_*"))]
    shots = [shot for shot in shots if shot]
    if len(shots) < 2:
        return
    count = len(shots)
    pixels = _WORK_W * _WORK_H
    mean = bytearray(pixels * 3)
    vary: list[float] = []
    for index in range(pixels):
        offset = index * 3
        reds = [shot[offset] for shot in shots]
        greens = [shot[offset + 1] for shot in shots]
        blues = [shot[offset + 2] for shot in shots]
        red = sum(reds) / count
        green = sum(greens) / count
        blue = sum(blues) / count
        mean[offset] = int(red)
        mean[offset + 1] = int(green)
        mean[offset + 2] = int(blue)
        vary.append(
            (
                sum((value - red) ** 2 for value in reds)
                + sum((value - green) ** 2 for value in greens)
                + sum((value - blue) ** 2 for value in blues)
            )
            / count
            / 3
        )
    idx = [index for index, value in enumerate(vary) if value <= _STABLE_VAR]
    if not idx:
        return
    worst = 0.0
    for shot in shots:
        worst = max(worst, _style_distance(shot, mean, idx))
    _style_idx = idx
    _style_mean = mean
    _style_limit = worst * 1.35


def _sample(image: QImage) -> bytes | None:
    if image.isNull():
        return None
    scaled = image.scaled(_WORK_W, _WORK_H, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    scaled = scaled.convertToFormat(QImage.Format.Format_RGB888)
    raw = bytes(scaled.constBits())
    stride = scaled.bytesPerLine()
    width = scaled.width()
    out = bytearray()
    row = width * 3
    for y in range(scaled.height()):
        start = y * stride
        out += raw[start : start + row]
    if len(out) != _WORK_W * _WORK_H * 3:
        return None
    return bytes(out)


def _outside_matches(image: QImage) -> bool:
    if not _style_idx:
        return False
    shot = _sample(image)
    if shot is None:
        return False
    return _style_distance(shot, _style_mean, _style_idx) <= _style_limit


def _style_distance(shot: bytes, mean: bytearray, idx: list[int]) -> float:
    total = 0.0
    for index in idx:
        offset = index * 3
        total += abs(shot[offset] - mean[offset])
        total += abs(shot[offset + 1] - mean[offset + 1])
        total += abs(shot[offset + 2] - mean[offset + 2])
    return total / len(idx) / 3


def _pick(
    tsums: list[dict[str, int]],
    alive: set[int],
    bounds: tuple[int, int, int, int],
) -> tuple[list[dict[str, int]], list[dict[str, int]]] | None:
    options = _threes(tsums, alive, bounds)
    if not options:
        return None
    spacing = _spacing([tsums[index] for index in alive])
    tol = max(spacing * 0.45, 8)
    best: tuple[int, int, int, set[int]] | None = None
    best_n = -1
    for start, mid, end in options:
        frozen = _line_ids(tsums, start, end, alive, tol)
        count = len(frozen)
        if count > best_n:
            best_n = count
            best = (start, mid, end, frozen)
    if best is None:
        return None
    start, mid, end, frozen = best
    return [tsums[start], tsums[mid], tsums[end]], [tsums[index] for index in frozen]


def _threes(
    tsums: list[dict[str, int]],
    alive: set[int],
    bounds: tuple[int, int, int, int],
) -> list[tuple[int, int, int]]:
    nodes = [index for index in alive]
    if len(nodes) < 3:
        return []
    spacing = _spacing([tsums[index] for index in nodes])
    if spacing <= 0:
        return []
    links = _links(tsums, nodes, spacing)
    starts = _edge_ids(tsums, nodes, spacing, bounds)
    found: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for start in starts:
        for mid in links.get(start, ()):
            for end in links.get(mid, ()):
                if end == start or (start, end) in seen:
                    continue
                seen.add((start, end))
                found.append((start, mid, end))
    return found


def _spacing(tsums: list[dict[str, int]]) -> float:
    if len(tsums) < 2:
        return 0.0
    nearest: list[float] = []
    for index, left in enumerate(tsums):
        ax, ay = int(left["x"]), int(left["y"])
        best = 1e18
        for other, right in enumerate(tsums):
            if other == index:
                continue
            dist = _dist(ax, ay, int(right["x"]), int(right["y"]))
            if dist < 4:
                continue
            if dist < best:
                best = dist
        if best < 1e18:
            nearest.append(best)
    if not nearest:
        return 0.0
    nearest.sort()
    return nearest[len(nearest) // 2]


def _links(
    tsums: list[dict[str, int]],
    nodes: list[int],
    spacing: float,
) -> dict[int, list[int]]:
    links: dict[int, list[int]] = {index: [] for index in nodes}
    low = spacing * 0.45
    high = spacing * 1.6
    for pos, left in enumerate(nodes):
        ax, ay = int(tsums[left]["x"]), int(tsums[left]["y"])
        group = int(tsums[left].get("group") or 0)
        for right in nodes[pos + 1 :]:
            if int(tsums[right].get("group") or 0) != group:
                continue
            dist = _dist(ax, ay, int(tsums[right]["x"]), int(tsums[right]["y"]))
            if dist < low or dist > high:
                continue
            links[left].append(right)
            links[right].append(left)
    return links


def _board_bounds(tsums: list[dict[str, int]]) -> tuple[int, int, int, int]:
    if not tsums:
        return 0, 0, 0, 0
    xs = [int(piece["x"]) for piece in tsums]
    ys = [int(piece["y"]) for piece in tsums]
    return min(xs), max(xs), min(ys), max(ys)


def _edge_ids(
    tsums: list[dict[str, int]],
    nodes: list[int],
    spacing: float,
    bounds: tuple[int, int, int, int],
) -> list[int]:
    min_x, max_x, min_y, max_y = bounds
    band = spacing * 0.45
    edges: list[int] = []
    for index in nodes:
        x = int(tsums[index]["x"])
        y = int(tsums[index]["y"])
        if x <= min_x + band or x >= max_x - band or y <= min_y + band or y >= max_y - band:
            edges.append(index)
    return edges


def _line_ids(
    tsums: list[dict[str, int]],
    start: int,
    end: int,
    alive: set[int],
    tol: float,
) -> set[int]:
    ax, ay = int(tsums[start]["x"]), int(tsums[start]["y"])
    bx, by = int(tsums[end]["x"]), int(tsums[end]["y"])
    frozen = {start, end}
    for index in alive:
        if index in frozen:
            continue
        if _on_segment(int(tsums[index]["x"]), int(tsums[index]["y"]), ax, ay, bx, by, tol):
            frozen.add(index)
    return frozen


def _on_segment(px: int, py: int, ax: int, ay: int, bx: int, by: int, tol: float) -> bool:
    abx = bx - ax
    aby = by - ay
    ab2 = abx * abx + aby * aby
    if ab2 <= 0:
        return _dist(px, py, ax, ay) <= tol
    tee = ((px - ax) * abx + (py - ay) * aby) / ab2
    if tee < 0:
        tee = 0
    elif tee > 1:
        tee = 1
    qx = ax + abx * tee
    qy = ay + aby * tee
    return _dist(px, py, qx, qy) <= tol


def _erase_wait(stop: Event | None) -> None:
    from app.play import ERASE_WAIT, _sleep_stop

    _sleep_stop(ERASE_WAIT, stop)


def _rgb(image: QImage):
    from app.play import _qimage_rgb

    return _qimage_rgb(image)


def _tap_ice(
    frozen: list[dict[str, int]],
    image: QImage,
    say: Callable[[str], None],
    stop: Event | None,
) -> None:
    groups = _ice_groups(frozen)
    for group in groups:
        _check_stop(stop)
        cx = sum(int(piece["x"]) for piece in group) / len(group)
        cy = sum(int(piece["y"]) for piece in group) / len(group)
        piece = min(group, key=lambda item: _dist(int(item["x"]), int(item["y"]), cx, cy))
        say(f"氷をタップ {int(piece['x'])},{int(piece['y'])}")
        tap(int(piece["x"]), int(piece["y"]), screen_w=image.width(), screen_h=image.height())


def _ice_groups(frozen: list[dict[str, int]]) -> list[list[dict[str, int]]]:
    if not frozen:
        return []
    spacing = _spacing(frozen)
    reach = spacing * 1.25 if spacing > 0 else 40
    unused = list(frozen)
    groups: list[list[dict[str, int]]] = []
    while unused:
        group = [unused.pop()]
        changed = True
        while changed:
            changed = False
            rest: list[dict[str, int]] = []
            for piece in unused:
                if any(
                    _dist(int(piece["x"]), int(piece["y"]), int(old["x"]), int(old["y"])) <= reach
                    for old in group
                ):
                    group.append(piece)
                    changed = True
                else:
                    rest.append(piece)
            unused = rest
        groups.append(group)
    return groups


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    dx = ax - bx
    dy = ay - by
    return (dx * dx + dy * dy) ** 0.5
