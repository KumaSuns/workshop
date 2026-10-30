from __future__ import annotations

import time

from PySide6.QtGui import QImage

from app.bluestacks import tap
from app.intro import _check_stop


_HOLD_SEC = 4.0
_WAIT_DICE_SEC = 8.0


def _blank() -> dict:
    return {
        "roll": 0,
        "tapped": False,
        "last": None,
        "stable": 0,
        "ignore": None,
        "hold_until": 0.0,
        "said": False,
        "seen": False,
        "seen_at": 0.0,
        "face_at": 0.0,
        "block": False,
        "high": False,
        "centers": None,
        "had_dice": False,
    }


def _reset(state: dict) -> None:
    state.clear()
    state.update(_blank())


def _hold(state: dict) -> None:
    state["block"] = True


def pending(state: dict) -> bool:
    return bool(
        state.get("seen")
        or state.get("had_dice")
        or state.get("roll")
        or state.get("tapped")
        or state.get("block")
    )


def _pips(arr, labels, index: int, red_area: int) -> int:
    import cv2
    import numpy as np

    ys, xs = np.where(labels == index)
    if len(xs) == 0:
        return 0
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    crop = arr[y0 : y1 + 1, x0 : x1 + 1]
    dark = (
        (crop[:, :, 0] < 80)
        & (crop[:, :, 1] < 80)
        & (crop[:, :, 2] < 80)
    ).astype(np.uint8)
    count, lab, stats, _centroids = cv2.connectedComponentsWithStats(dark, 8)
    found = 0
    low = max(1, int(red_area * 0.04))
    high = max(low + 1, int(red_area * 0.18))
    height, width = dark.shape
    for comp in range(1, count):
        area = int(stats[comp, cv2.CC_STAT_AREA])
        if area < low or area > high:
            continue
        left = int(stats[comp, cv2.CC_STAT_LEFT])
        top = int(stats[comp, cv2.CC_STAT_TOP])
        box_w = int(stats[comp, cv2.CC_STAT_WIDTH])
        box_h = int(stats[comp, cv2.CC_STAT_HEIGHT])
        border = left <= 1 or top <= 1 or left + box_w >= width - 1 or top + box_h >= height - 1
        mask = (lab == comp).astype(np.uint8)
        contours, _hier = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue
        per = cv2.arcLength(contours[0], True)
        if per <= 0:
            continue
        circ = 4.0 * 3.14159265 * area / (per * per)
        if circ < (0.63 if border else 0.75):
            continue
        found += 1
    return found


def boogie_on(rgb) -> bool:
    import cv2
    import numpy as np

    arr = np.array(rgb)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return False
    height, width = arr.shape[:2]
    if width < 2 or height < 2:
        return False
    red = arr[:, :, 0].astype(np.int16)
    green = arr[:, :, 1].astype(np.int16)
    blue = arr[:, :, 2].astype(np.int16)
    mask = ((green > 120) & (green > red + 30) & (green > blue + 15) & (red < 180)).astype(np.uint8)
    count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        box_w = int(stats[index, cv2.CC_STAT_WIDTH])
        box_h = int(stats[index, cv2.CC_STAT_HEIGHT])
        cx = float(centroids[index][0])
        cy = float(centroids[index][1])
        if area < width * height * 0.06:
            continue
        if box_w < width * 0.35 or box_h < height * 0.18:
            continue
        if not (width * 0.30 <= cx <= width * 0.70 and height * 0.35 <= cy <= height * 0.70):
            continue
        return True
    return False


def _dice_pair(rgb):
    import cv2
    import numpy as np

    arr = np.array(rgb)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return None
    red = arr[:, :, 0].astype(np.int16)
    green = arr[:, :, 1].astype(np.int16)
    blue = arr[:, :, 2].astype(np.int16)
    mask = ((red > 150) & (red > green + 60) & (red > blue + 60) & (green < 80)).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    height, width = mask.shape[:2]
    if width < 2 or height < 2:
        return None
    min_side = width * 0.08
    min_area = max(1, int(width * height * 0.0008))
    found = []
    for index in range(1, count):
        area = int(stats[index, cv2.CC_STAT_AREA])
        box_w = int(stats[index, cv2.CC_STAT_WIDTH])
        box_h = int(stats[index, cv2.CC_STAT_HEIGHT])
        if area >= min_area and box_w > width * 0.35 and box_h > width * 0.2:
            return None
        if area < min_area or box_w < min_side or box_h < min_side:
            continue
        aspect = box_w / box_h
        if aspect < 0.6 or aspect > 2.0:
            continue
        cx = float(centroids[index][0])
        cy = float(centroids[index][1])
        if not (height * 0.32 <= cy <= height * 0.68):
            continue
        found.append((area, index, int(cx), int(cy)))
    if len(found) < 2:
        return None
    found.sort(reverse=True)
    pair = sorted(found[:2], key=lambda item: item[2])
    faces = []
    for area, index, cx, cy in pair:
        faces.append((_pips(arr, labels, index, area), cx, cy))
    return faces


def dice_on(rgb) -> bool:
    if rgb is None:
        return False
    try:
        return _dice_pair(rgb) is not None
    except Exception:
        return False


def dice_values(rgb) -> list[tuple[int, int, int]] | None:
    pair = _dice_pair(rgb)
    if pair is None:
        return None
    if any(item[0] < 1 or item[0] > 6 for item in pair):
        return None
    return pair


def nightmare_dice_step(image: QImage, rgb, state: dict, say, stop, watch_hit) -> bool:
    if image is None or image.isNull() or rgb is None:
        state["block"] = False
        return False
    _check_stop(stop)
    try:
        faces = _dice_pair(rgb)
    except Exception:
        faces = None
    roll = int(state.get("roll") or 0)
    tapped = bool(state.get("tapped"))
    if faces is not None:
        _hold(state)
        state["face_at"] = time.time()
        state["had_dice"] = True
        counts = (int(faces[0][0]), int(faces[1][0]))
        total = counts[0] + counts[1]
        if any(item < 1 or item > 6 for item in counts):
            return True
        if total >= 7:
            if roll == 0:
                say(f"サイコロ {counts[0]}+{counts[1]}={total}")
                state["roll"] = 1
            return True
        if roll == 0:
            say(f"サイコロ {counts[0]}+{counts[1]}={total}")
            state["roll"] = 1
            x = int((faces[0][1] + faces[1][1]) / 2)
            y = int((faces[0][2] + faces[1][2]) / 2)
            say("振り直し")
            tap(x, y, hold_ms=40, screen_w=image.width(), screen_h=image.height())
            state["tapped"] = True
            state["ignore"] = counts
            state["hold_until"] = time.time() + _HOLD_SEC
            state["last"] = None
            state["stable"] = 0
            return True
        if roll == 1 and tapped and counts != state.get("ignore"):
            say(f"サイコロ {counts[0]}+{counts[1]}={total}")
            state["roll"] = 2
        return True
    if time.time() - float(state.get("face_at") or 0.0) < 0.45 and state.get("face_at"):
        _hold(state)
        return True
    try:
        boogie = boogie_on(rgb)
    except Exception:
        boogie = False
    if boogie:
        state["seen"] = True
        state["seen_at"] = time.time()
        if not state.get("said"):
            say("ブギー")
            state["said"] = True
        _hold(state)
        return True
    if state.get("seen") and not state.get("had_dice"):
        if time.time() - float(state.get("seen_at") or 0.0) < _WAIT_DICE_SEC:
            _hold(state)
            return True
        _reset(state)
        return False
    if tapped and roll < 2 and time.time() < float(state.get("hold_until") or 0.0):
        _hold(state)
        return True
    if roll or tapped or state.get("had_dice"):
        _reset(state)
        return False
    state["block"] = False
    return False
