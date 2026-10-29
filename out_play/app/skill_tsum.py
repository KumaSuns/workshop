from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Callable

from PySide6.QtGui import QImage

from app.bluestacks import capture_play_frame, swipe_path, tap
from app.intro import _check_stop
from app.paths import APP_ROOT

SayFn = Callable[[str], None]

_CBUZZ_A = (0.317, 0.556)
_CBUZZ_B = (0.633, 0.556)
_CBUZZ_C = (0.500, 0.204)
_CBUZZ_SECONDS = (2.5, 0.02, 0.30, 0.45, 0.40)
_CBUZZ_PATH = APP_ROOT / "data" / "cbuzz.json"
_CBUZZ_BOARD = Path(__file__).resolve().parent / "cbuzz_board.jpg"


def cbuzz_board_path() -> Path:
    return _CBUZZ_BOARD


def _cbuzz_point(value, default: tuple[float, float]) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return default
    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError):
        return default
    if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
        return default
    return x, y


def _cbuzz_seconds(value) -> tuple[float, float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 5:
        return _CBUZZ_SECONDS
    try:
        seconds = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return _CBUZZ_SECONDS
    if any(item < 0 for item in seconds):
        return _CBUZZ_SECONDS
    return seconds  # type: ignore[return-value]


def cbuzz_settings() -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float, float, float, float],
]:
    try:
        payload = json.loads(_CBUZZ_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return (
        _cbuzz_point(payload.get("a"), _CBUZZ_A),
        _cbuzz_point(payload.get("b"), _CBUZZ_B),
        _cbuzz_point(payload.get("c"), _CBUZZ_C),
        _cbuzz_seconds(payload.get("seconds")),
    )


def set_cbuzz_settings(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    seconds: tuple[float, float, float, float, float],
) -> None:
    point_a = _cbuzz_point(a, _CBUZZ_A)
    point_b = _cbuzz_point(b, _CBUZZ_B)
    point_c = _cbuzz_point(c, _CBUZZ_C)
    delays = _cbuzz_seconds(seconds)
    _CBUZZ_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CBUZZ_PATH.write_text(
        json.dumps(
            {
                "a": [point_a[0], point_a[1]],
                "b": [point_b[0], point_b[1]],
                "c": [point_c[0], point_c[1]],
                "seconds": list(delays),
            }
        ),
        encoding="utf-8",
    )


def reset_cbuzz_settings() -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float, float, float, float],
]:
    set_cbuzz_settings(_CBUZZ_A, _CBUZZ_B, _CBUZZ_C, _CBUZZ_SECONDS)
    return cbuzz_settings()


def cbuzz_steps() -> tuple[tuple[tuple[float, float], float, str], ...]:
    a, b, c, seconds = cbuzz_settings()
    return (
        (b, seconds[0], "B"),
        (a, seconds[1], "A"),
        (c, seconds[2], "C"),
        (c, seconds[3], "C"),
        (c, seconds[4], "C"),
    )


def cbuzz_press_to_b() -> float:
    return float(cbuzz_steps()[0][1])


def skill_tsum_key(name: str) -> str:
    return " ".join((name or "").split()).replace("＋", "+")


def skill_breaks_bombs(name: str) -> bool:
    key = skill_tsum_key(name)
    handler = _AFTER.get(key) or _AFTER.get(key.casefold())
    return handler is _after_cbuzz


def skill_is_gadget(name: str) -> bool:
    key = skill_tsum_key(name)
    return key == "ガジェット" or key.casefold() == "gadget"


def skill_is_cloud(name: str) -> bool:
    key = skill_tsum_key(name)
    return key in {"クラウドKH2ver.", "KH2Cloud"} or key.casefold() == "kh2cloud"


def skill_is_elsa(name: str) -> bool:
    key = skill_tsum_key(name)
    return key in {"戴冠式エルサ", "Coronation_Elsa"} or key.casefold() == "coronation_elsa"


def skill_is_namine(name: str) -> bool:
    key = skill_tsum_key(name)
    return key == "ナミネ" or key.casefold() == "namine"


def skill_is_nightmare(name: str) -> bool:
    key = skill_tsum_key(name)
    return key in {
        "ナイトメアビフォアクリスマス（セット）",
        "Nightmare_Before_Christmas",
    } or key.casefold() == "nightmare_before_christmas"


def skill_is_cinderella(name: str) -> bool:
    key = skill_tsum_key(name)
    return key in {"シンデレラ", "Cinderella"} or key.casefold() == "cinderella"


def skill_is_pooh(name: str) -> bool:
    key = skill_tsum_key(name)
    handler = _AFTER.get(key) or _AFTER.get(key.casefold())
    return handler is _after_pooh


def after_skill_tap(
    name: str,
    image: QImage,
    rgb,
    say: SayFn,
    stop,
    watch_hit=None,
    game=None,
    started_at: float | None = None,
    pose_seen: bool = False,
) -> None:
    key = skill_tsum_key(name)
    handler = _AFTER.get(key) or _AFTER.get(key.casefold())
    if handler is None:
        return
    handler(image, rgb, say, stop, watch_hit, game, started_at, pose_seen)


_PLAIN_SKILL_WAIT = 2.0


def _after_plain(image: QImage, rgb, say: SayFn, stop, watch_hit, game, started_at=None, pose_seen=False) -> None:
    del started_at, pose_seen
    _wait_until(time.time() + _PLAIN_SKILL_WAIT, stop, watch_hit)


_POOH_SWIPE_AT = 1.8
_POOH_SWIPE = (
    (0.50, 0.40),
    (0.50, 0.52),
    (0.50, 0.64),
    (0.50, 0.74),
)


def _after_pooh(image: QImage, rgb, say: SayFn, stop, watch_hit, game, started_at=None, pose_seen=False) -> None:
    del started_at, pose_seen
    width = image.width()
    height = image.height()
    if width < 2 or height < 2:
        return
    start = time.time()
    _wait_until(start + _POOH_SWIPE_AT, stop, watch_hit)
    if watch_hit is not None and watch_hit.is_set():
        return
    points = [(int(fx * width), int(fy * height)) for fx, fy in _POOH_SWIPE]
    say(f"おしり {points[0][0]},{points[0][1]} → {points[-1][0]},{points[-1][1]}")
    swipe_path(
        points,
        screen_w=width,
        screen_h=height,
        stop=stop,
        abort=watch_hit,
    )


def _cbuzz_pose_on(image: QImage) -> bool:
    width = image.width()
    height = image.height()
    if width < 2 or height < 2:
        return False
    left = int(width * 0.28)
    top = int(height * 0.30)
    right = int(width * 0.72)
    bottom = int(height * 0.72)
    if right - left < 8 or bottom - top < 8:
        return False
    step = max(1, min(right - left, bottom - top) // 70)
    cols = list(range(left, right, step))
    rows = list(range(top, bottom, step))
    mask = []
    for y in rows:
        row = []
        for x in cols:
            color = image.pixel(x, y)
            red = (color >> 16) & 255
            green = (color >> 8) & 255
            blue = color & 255
            row.append(green > 90 and green > red + 15 and green >= blue - 10 and red < 160)
        mask.append(row)
    height_n = len(mask)
    width_n = len(mask[0])
    seen = [[False] * width_n for _ in range(height_n)]
    best = 0
    for y in range(height_n):
        for x in range(width_n):
            if not mask[y][x] or seen[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            count = 0
            while stack:
                cx, cy = stack.pop()
                count += 1
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < width_n and 0 <= ny < height_n and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if count > best:
                best = count
    return best / (height_n * width_n) >= 0.03


def _wait_cbuzz_b(start: float, stop, watch_hit, pose_seen: bool = False) -> bool:
    del watch_hit
    fallback = float(start) + 2.5
    limit = float(start) + 5.0
    saw = bool(pose_seen)
    off = 0
    while True:
        _check_stop(stop)
        now = time.time()
        try:
            shot = capture_play_frame()
        except Exception:
            shot = None
        if shot is None or shot.isNull():
            if now >= limit:
                return True
            time.sleep(0.02)
            continue
        on = _cbuzz_pose_on(shot)
        if on:
            saw = True
            off = 0
        elif saw:
            off += 1
            if off >= 2:
                return True
        elif now >= fallback:
            return True
        if now >= limit:
            return True
        time.sleep(0.02)


def _after_cbuzz(image: QImage, rgb, say: SayFn, stop, watch_hit, game, started_at=None, pose_seen=False) -> None:
    width = image.width()
    height = image.height()
    if width < 2 or height < 2:
        return
    start = float(started_at) if started_at else time.time()
    if not _wait_cbuzz_b(start, stop, watch_hit, pose_seen):
        return
    first = True
    for frac, delay, label in cbuzz_steps():
        if not first:
            wait = float(delay) + random.choice((0.0, 0.01, 0.02))
            _wait_until(time.time() + wait, stop, None)
        first = False
        x = int(frac[0] * width)
        y = int(frac[1] * height)
        say(f"cバズ {label} {x},{y}")
        tap(x, y, hold_ms=40, screen_w=width, screen_h=height)


def _wait_until(deadline: float, stop, watch_hit=None) -> None:
    while time.time() < deadline:
        _check_stop(stop)
        if watch_hit is not None and watch_hit.is_set():
            return
        time.sleep(min(0.02, max(0.0, deadline - time.time())))


_AFTER = {
    "ガジェット": _after_plain,
    "gadget": _after_plain,
    "cバズ": _after_cbuzz,
    "c_bazu": _after_cbuzz,
    "キャプテンライトイヤー": _after_cbuzz,
    "おしりまんまるプー+": _after_pooh,
    "おしりまんまるプー": _after_pooh,
    "RoundButtPooh": _after_pooh,
}
