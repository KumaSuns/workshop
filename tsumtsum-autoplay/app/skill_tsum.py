from __future__ import annotations

import time
from typing import Callable

from PySide6.QtGui import QImage

from app.bluestacks import tap
from app.intro import _check_stop

SayFn = Callable[[str], None]

_CBUZZ_FPS = 60.0
_CBUZZ_A = (0.293, 0.563)
_CBUZZ_B = (0.643, 0.546)
_CBUZZ_C = (0.500, 0.204)
_CBUZZ_STEPS = (
    (_CBUZZ_B, 130, "B"),
    (_CBUZZ_A, 5, "A"),
    (_CBUZZ_C, 28, "C"),
    (_CBUZZ_C, 28, "C"),
    (_CBUZZ_C, 28, "C"),
)


def skill_tsum_key(name: str) -> str:
    return " ".join((name or "").split())


def skill_breaks_bombs(name: str) -> bool:
    key = skill_tsum_key(name)
    handler = _AFTER.get(key) or _AFTER.get(key.casefold())
    return handler is _after_cbuzz


def after_skill_tap(
    name: str,
    image: QImage,
    rgb,
    say: SayFn,
    stop,
    watch_hit=None,
    game=None,
) -> None:
    key = skill_tsum_key(name)
    handler = _AFTER.get(key) or _AFTER.get(key.casefold()) or _after_plain
    handler(image, rgb, say, stop, watch_hit, game)


def _after_plain(image: QImage, rgb, say: SayFn, stop, watch_hit, game) -> None:
    return


def _after_cbuzz(image: QImage, rgb, say: SayFn, stop, watch_hit, game) -> None:
    width = image.width()
    height = image.height()
    if width < 2 or height < 2:
        return
    start = time.time()
    at = 0.0
    for frac, frames, label in _CBUZZ_STEPS:
        at += frames / _CBUZZ_FPS
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
}
