from __future__ import annotations

import time
from typing import Callable

from PySide6.QtGui import QImage

from app.bluestacks import swipe_path, tap
from app.intro import _check_stop

SayFn = Callable[[str], None]

_CBUZZ_A = (0.193, 0.556)
_CBUZZ_B = (0.633, 0.556)
_CBUZZ_C = (0.500, 0.204)
_CBUZZ_STEPS = (
    (_CBUZZ_B, 2.5, "B"),
    (_CBUZZ_A, 0.08, "A"),
    (_CBUZZ_C, 0.45, "C"),
    (_CBUZZ_C, 0.48, "C"),
    (_CBUZZ_C, 0.4, "C"),
)


def cbuzz_press_to_b() -> float:
    return float(_CBUZZ_STEPS[0][1])


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
) -> None:
    key = skill_tsum_key(name)
    handler = _AFTER.get(key) or _AFTER.get(key.casefold())
    if handler is None:
        return
    handler(image, rgb, say, stop, watch_hit, game, started_at)


_PLAIN_SKILL_WAIT = 2.0


def _after_plain(image: QImage, rgb, say: SayFn, stop, watch_hit, game, started_at=None) -> None:
    del started_at
    _wait_until(time.time() + _PLAIN_SKILL_WAIT, stop, watch_hit)


_POOH_SWIPE_AT = 1.8
_POOH_SWIPE = (
    (0.50, 0.40),
    (0.50, 0.52),
    (0.50, 0.64),
    (0.50, 0.74),
)


def _after_pooh(image: QImage, rgb, say: SayFn, stop, watch_hit, game, started_at=None) -> None:
    del started_at
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


def _after_cbuzz(image: QImage, rgb, say: SayFn, stop, watch_hit, game, started_at=None) -> None:
    width = image.width()
    height = image.height()
    if width < 2 or height < 2:
        return
    start = float(started_at) if started_at else time.time()
    at = 0.0
    for frac, delay, label in _CBUZZ_STEPS:
        at += delay
        _wait_until(start + at, stop, watch_hit)
        if watch_hit is not None and watch_hit.is_set():
            return
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
