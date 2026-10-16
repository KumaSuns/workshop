from __future__ import annotations

import importlib.util
import sys
import time
import types
from collections.abc import Callable
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
_run_chains_fn = None


def _run_chains(
    pieces: list[dict],
    game: dict[str, int] | None,
    locked: list[dict] | None = None,
) -> list[dict]:
    global _run_chains_fn
    if _run_chains_fn is None:
        path = (
            APP_ROOT.parent
            / "tsumtsum-screen-recognition"
            / "app"
            / "elsa_run.py"
        )
        stub = types.ModuleType("app.regions")
        stub.is_tsum_kind = lambda kind: str(kind or "") in {"tsum", "big"}
        previous = sys.modules.get("app.regions")
        sys.modules["app.regions"] = stub
        try:
            spec = importlib.util.spec_from_file_location("elsa_run_skill", path)
            if spec is None or spec.loader is None:
                raise ImportError(str(path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _run_chains_fn = module.elsa_freeze_most
        finally:
            if previous is None:
                sys.modules.pop("app.regions", None)
            else:
                sys.modules["app.regions"] = previous
    return _run_chains_fn(pieces, game, locked)


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
    skill_lamp: Callable[[bool], None] | None = None,
) -> int:
    _load_style()
    deadline = time.time() + _SKILL_SEC
    off_run = 0
    swipes = 0
    lit = False

    def set_lamp(on: bool) -> None:
        nonlocal lit
        if skill_lamp is None or on == lit:
            return
        lit = on
        skill_lamp(on)

    say("スキル中")
    frozen: list[dict] = []
    seen_ice: set[tuple[int, int]] = set()
    locked: list[dict] = []
    seen_lock: set[tuple[int, int]] = set()
    just_swiped = False
    image: QImage | None = None
    pieces: list = []

    def finish_ice() -> None:
        nonlocal frozen, seen_ice, locked, seen_lock
        if not frozen or image is None or image.isNull():
            return
        _tap_ice(frozen, pieces, image, say, stop)
        frozen = []
        seen_ice = set()
        locked = []
        seen_lock = set()

    try:
        while time.time() < deadline:
            _check_stop(stop)
            if watch_hit is not None and watch_hit.is_set():
                finish_ice()
                return swipes
            try:
                image = capture_play_frame()
            except Exception:
                _erase_wait(stop)
                continue
            if image.isNull():
                _erase_wait(stop)
                continue
            if bool(_style_idx) and _outside_matches(image):
                off_run = 0
                set_lamp(False)
            elif _style_idx:
                off_run += 1
                if off_run >= 3:
                    set_lamp(True)
            rgb = _rgb(image)
            if rgb is None:
                continue
            with gpu_lock:
                pieces = predict(rgb)
            chains = _run_chains(pieces, game, locked)
            halted = False
            swiped_now = False
            for line in chains:
                _check_stop(stop)
                if watch_hit is not None and watch_hit.is_set():
                    halted = True
                    break
                if time.time() >= deadline:
                    halted = True
                    break
                trace = line.get("trace") or []
                if len(trace) < 3:
                    continue
                points = [(int(piece["x"]), int(piece["y"])) for piece in trace]
                if preview is not None:
                    preview(draw(image, pieces, trace, game))
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
                swiped_now = True
                for piece in line.get("trace") or []:
                    key = (int(piece["x"]), int(piece["y"]))
                    if key in seen_lock:
                        continue
                    seen_lock.add(key)
                    locked.append(piece)
                for piece in line.get("ice") or []:
                    key = (int(piece["x"]), int(piece["y"]))
                    if key in seen_ice:
                        continue
                    seen_ice.add(key)
                    frozen.append(piece)
            if halted:
                finish_ice()
                return swipes
            if swiped_now:
                just_swiped = True
                continue
            if chains:
                continue
            if just_swiped:
                just_swiped = False
                continue
            if not frozen:
                _erase_wait(stop)
                continue
            finish_ice()
            just_swiped = False
            _erase_wait(stop)
        finish_ice()
        say("スキル中が終わりました")
        return swipes
    finally:
        set_lamp(False)


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


def _erase_wait(stop: Event | None) -> None:
    from app.play import ERASE_WAIT, _sleep_stop

    _sleep_stop(ERASE_WAIT, stop)


def _rgb(image: QImage):
    from app.play import _qimage_rgb

    return _qimage_rgb(image)


def _tap_ice(
    frozen: list[dict[str, int]],
    pieces: list,
    image: QImage,
    say: Callable[[str], None],
    stop: Event | None,
) -> None:
    _check_stop(stop)
    target = _ice_still_there(frozen, pieces)
    if target is None:
        return
    say(f"氷をタップ {int(target['x'])},{int(target['y'])}")
    tap(int(target["x"]), int(target["y"]), screen_w=image.width(), screen_h=image.height())


def _ice_still_there(frozen: list[dict], pieces: list) -> dict | None:
    for piece in pieces:
        if str(piece.get("kind") or "") not in {"tsum", "big"}:
            continue
        radius = float(piece.get("r") or 0)
        if radius <= 0:
            continue
        x = float(piece["x"])
        y = float(piece["y"])
        limit = radius * radius
        for old in frozen:
            dx = x - float(old["x"])
            dy = y - float(old["y"])
            if dx * dx + dy * dy <= limit:
                return piece
    return None


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
