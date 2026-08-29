from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QRect, QThread, Signal
from PySide6.QtGui import QImage

from app.bluestacks import capture_screen, tap, tsum_is_running

SAMPLE_W = 160
SAMPLE_H = 90
BOOT_TIMEOUT = 120
FLOW_TIMEOUT = 180
PRE_CLICK_WAIT = 1.2
TAP_GAP = 0.55
DIALOG_STABLE = 3
VIDEO_STABLE = 5
START_STABLE = 3
POPUP_GONE = 8
POPUP_STABLE = 2
PLAY_STABLE = 3

StatusFn = Callable[[str], None]


class IntroWorker(QThread):
    succeeded = Signal()
    failed = Signal(str)
    status = Signal(str)

    def run(self) -> None:
        try:
            run_intro_flow(self.status.emit)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
            return
        self.succeeded.emit()


def run_intro_flow(report: StatusFn | None = None) -> None:
    def say(text: str) -> None:
        if report is not None:
            report(text)

    say("画面を待っています")
    deadline = time.time() + BOOT_TIMEOUT + FLOW_TIMEOUT
    previous: QImage | None = None
    motion_hits = 0
    dialog_hits = 0
    start_hits = 0
    clicked_center = False
    clicked_allow = False
    while time.time() < deadline:
        try:
            image = capture_screen()
        except Exception:
            say("画面を待っています（起動中）")
            time.sleep(1.2)
            continue
        dialog = _white_dialog(image)
        if dialog is not None and not clicked_allow:
            dialog_hits += 1
            start_hits = 0
            say(f"許可画面を検出 {dialog_hits}/{DIALOG_STABLE}")
            if dialog_hits >= DIALOG_STABLE:
                say("許可するをクリックします")
                _click_allow(dialog, say)
                clicked_allow = True
                deadline = max(deadline, time.time() + 90)
                say("TAP TO STARTを待っています")
            previous = image
            time.sleep(0.35)
            continue
        dialog_hits = 0
        start_btn = _tap_to_start_button(image)
        if start_btn is not None:
            start_hits += 1
            say(f"TAP TO STARTを検出 {start_hits}/{START_STABLE}")
            if start_hits >= START_STABLE:
                say("TAP TO STARTをクリックします")
                _click_start(start_btn, say)
                deadline = max(deadline, time.time() + 120)
                _dismiss_popups(say, deadline)
                return
            previous = image
            time.sleep(0.35)
            continue
        start_hits = 0
        if not clicked_center and not clicked_allow and tsum_is_running():
            if _is_video_motion(previous, image):
                motion_hits += 1
                say(f"動画を検出 {motion_hits}/{VIDEO_STABLE}")
            else:
                motion_hits = 0
                say("許可画面なし、動画を待っています")
            if motion_hits >= VIDEO_STABLE:
                say("画面中央をクリックします")
                _slow_tap(image.width() // 2, image.height() // 2)
                clicked_center = True
                say("許可画面を待っています")
        elif clicked_allow:
            say("TAP TO STARTを待っています")
        elif not tsum_is_running():
            say("ツムツムの起動を待っています")
        else:
            say("許可画面を待っています")
        previous = image
        time.sleep(0.35)
    raise TimeoutError("動画、許可画面、または TAP TO START を待てませんでした。")


def _click_allow(dialog: QRect, say: StatusFn) -> None:
    x = dialog.x() + int(dialog.width() * 0.92)
    y = dialog.y() + int(dialog.height() * 0.92)
    say(f"許可するをタップ ({x}, {y})")
    _slow_tap(x, y)
    time.sleep(0.9)
    try:
        still = _white_dialog(capture_screen())
    except Exception:
        return
    if still is not None:
        x = still.x() + int(still.width() * 0.92)
        y = still.y() + int(still.height() * 0.92)
        say(f"まだ残っているので再タップ ({x}, {y})")
        _slow_tap(x, y)


def _click_start(button: QRect, say: StatusFn) -> None:
    x = button.center().x()
    y = button.center().y()
    say(f"TAP TO STARTをタップ ({x}, {y})")
    _slow_tap(x, y)
    time.sleep(0.9)
    try:
        still = _tap_to_start_button(capture_screen())
    except Exception:
        return
    if still is not None:
        say(f"まだ残っているので再タップ ({still.center().x()}, {still.center().y()})")
        _slow_tap(still.center().x(), still.center().y())


def _dismiss_popups(say: StatusFn, deadline: float) -> None:
    play_hits = 0
    popup_hits = 0
    while time.time() < deadline:
        try:
            image = capture_screen()
        except Exception:
            say("画面を待っています")
            time.sleep(1.0)
            continue
        play = _play_button(image)
        if play is not None:
            popup_hits = 0
            play_hits += 1
            say(f"プレイを検出 {play_hits}/{PLAY_STABLE}")
            if play_hits >= PLAY_STABLE:
                say("プレイをクリックします")
                _slow_tap(play.center().x(), play.center().y())
                time.sleep(0.8)
                try:
                    still = _play_button(capture_screen())
                except Exception:
                    still = None
                if still is not None:
                    say("プレイを再タップします")
                    _slow_tap(still.center().x(), still.center().y())
                say("プレイまで終わりました")
                return
            time.sleep(0.35)
            continue
        play_hits = 0
        cancel = _cancel_button(image)
        close = None if cancel is not None else _close_button(image)
        target = cancel or close
        if target is not None:
            popup_hits += 1
            if popup_hits < POPUP_STABLE:
                say("ポップアップを検出")
                time.sleep(0.35)
                continue
            if cancel is not None:
                say("キャンセルをクリックします")
            else:
                say("とじるをクリックします")
            _slow_tap(target.center().x(), target.center().y())
            popup_hits = 0
            time.sleep(0.7)
            continue
        popup_hits = 0
        say("プレイを待っています")
        time.sleep(0.35)
    raise TimeoutError("プレイが出ませんでした。")


def _slow_tap(x: int, y: int) -> None:
    time.sleep(PRE_CLICK_WAIT)
    tap(x, y)
    time.sleep(TAP_GAP)
    tap(x, y)


def _is_video_motion(previous: QImage | None, current: QImage) -> bool:
    if previous is None or previous.isNull() or current.isNull():
        return False
    prev = _sample(previous)
    curr = _sample(current)
    if _mean_luma(curr) < 28:
        return False
    total = 0.0
    count = 0
    for y, row in enumerate(curr):
        for x, pixel in enumerate(row):
            before = prev[y][x]
            total += abs(pixel[0] - before[0]) + abs(pixel[1] - before[1]) + abs(pixel[2] - before[2])
            count += 1
    return count > 0 and (total / count) > 24


def _white_dialog(image: QImage) -> QRect | None:
    sample = _sample(image)
    height = len(sample)
    width = len(sample[0]) if sample else 0
    if width == 0:
        return None
    blob = _largest_white_blob(sample)
    if len(blob) < width * height * 0.04:
        return None
    area = len(blob) / (width * height)
    if area > 0.62:
        return None
    xs = [p[0] for p in blob]
    ys = [p[1] for p in blob]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    box_w = right - left + 1
    box_h = bottom - top + 1
    if box_w < width * 0.22 or box_h < height * 0.12:
        return None
    if box_w > width * 0.95 or box_h > height * 0.80:
        return None
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    if abs(cx - width / 2) > width * 0.28 or abs(cy - height / 2) > height * 0.32:
        return None
    scale_x = image.width() / width
    scale_y = image.height() / height
    return QRect(
        int(left * scale_x),
        int(top * scale_y),
        int(box_w * scale_x),
        int(box_h * scale_y),
    )


def _tap_to_start_button(image: QImage) -> QRect | None:
    sample = _sample(image)
    height = len(sample)
    width = len(sample[0]) if sample else 0
    if width == 0:
        return None
    blob = _largest_blob(sample, _is_start_yellow)
    if len(blob) < 20:
        return None
    xs = [p[0] for p in blob]
    ys = [p[1] for p in blob]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    box_w = right - left + 1
    box_h = bottom - top + 1
    if box_h < 3 or box_w < box_h * 2.2:
        return None
    if box_w < width * 0.18 or box_w > width * 0.85:
        return None
    if box_h > height * 0.28:
        return None
    cx = (left + right) / 2
    if abs(cx - width / 2) > width * 0.22:
        return None
    scale_x = image.width() / width
    scale_y = image.height() / height
    return QRect(
        int(left * scale_x),
        int(top * scale_y),
        int(box_w * scale_x),
        int(box_h * scale_y),
    )


def _yellow_pills(image: QImage) -> list[QRect]:
    sample = _sample(image)
    height = len(sample)
    width = len(sample[0]) if sample else 0
    if width == 0:
        return []
    scale_x = image.width() / width
    scale_y = image.height() / height
    pills: list[QRect] = []
    for blob in _all_blobs(sample, _is_start_yellow):
        if len(blob) < 12:
            continue
        xs = [p[0] for p in blob]
        ys = [p[1] for p in blob]
        left, right = min(xs), max(xs)
        top, bottom = min(ys), max(ys)
        box_w = right - left + 1
        box_h = bottom - top + 1
        if box_h < 3 or box_w < box_h * 1.6:
            continue
        if box_w < width * 0.08 or box_w > width * 0.55:
            continue
        if box_h > height * 0.22:
            continue
        pills.append(
            QRect(
                int(left * scale_x),
                int(top * scale_y),
                int(box_w * scale_x),
                int(box_h * scale_y),
            )
        )
    pills.sort(key=lambda rect: rect.x())
    return pills


def _play_button(image: QImage) -> QRect | None:
    bottom = [
        pill
        for pill in _yellow_pills(image)
        if pill.center().y() > image.height() * 0.58
    ]
    if not bottom:
        return None
    play = max(bottom, key=lambda rect: rect.width() * rect.height())
    if play.width() < image.width() * 0.18:
        return None
    if abs(play.center().x() - image.width() / 2) > image.width() * 0.22:
        return None
    return play


def _cancel_button(image: QImage) -> QRect | None:
    pills = _yellow_pills(image)
    if len(pills) < 2:
        return None
    for index, left in enumerate(pills[:-1]):
        right = pills[index + 1]
        if abs(left.center().y() - right.center().y()) > max(left.height(), right.height()) * 0.6:
            continue
        if abs(left.height() - right.height()) > max(left.height(), right.height()) * 0.5:
            continue
        gap = right.x() - left.right()
        if gap < -left.width() * 0.2 or gap > left.width() * 2.2:
            continue
        if _play_button(image) is not None:
            return None
        return left
    return None


def _close_button(image: QImage) -> QRect | None:
    if _play_button(image) is not None or _cancel_button(image) is not None:
        return None
    pills = _yellow_pills(image)
    if not pills:
        return None
    if len(pills) >= 3:
        return pills[len(pills) // 2]
    return max(pills, key=lambda rect: rect.width() * rect.height())


def _is_start_yellow(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red > 200 and green > 110 and blue < 70 and red >= green and green > blue + 60


def _is_white(pixel: tuple[int, int, int]) -> bool:
    return pixel[0] > 200 and pixel[1] > 200 and pixel[2] > 200


def _largest_white_blob(sample: list[list[tuple[int, int, int]]]) -> list[tuple[int, int]]:
    return _largest_blob(sample, _is_white)


def _all_blobs(
    sample: list[list[tuple[int, int, int]]],
    match,
) -> list[list[tuple[int, int]]]:
    height = len(sample)
    width = len(sample[0]) if sample else 0
    seen = [[False] * width for _ in range(height)]
    blobs: list[list[tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            if seen[y][x] or not match(sample[y][x]):
                continue
            stack = [(x, y)]
            seen[y][x] = True
            cells: list[tuple[int, int]] = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if nx < 0 or ny < 0 or nx >= width or ny >= height:
                        continue
                    if seen[ny][nx] or not match(sample[ny][nx]):
                        continue
                    seen[ny][nx] = True
                    stack.append((nx, ny))
            blobs.append(cells)
    return blobs


def _largest_blob(
    sample: list[list[tuple[int, int, int]]],
    match,
) -> list[tuple[int, int]]:
    blobs = _all_blobs(sample, match)
    if not blobs:
        return []
    return max(blobs, key=len)


def _sample(image: QImage) -> list[list[tuple[int, int, int]]]:
    scaled = image.scaled(SAMPLE_W, SAMPLE_H)
    rows: list[list[tuple[int, int, int]]] = []
    for y in range(scaled.height()):
        row: list[tuple[int, int, int]] = []
        for x in range(scaled.width()):
            color = scaled.pixelColor(x, y)
            row.append((color.red(), color.green(), color.blue()))
        rows.append(row)
    return rows


def _mean_luma(rows: list[list[tuple[int, int, int]]]) -> float:
    total = 0.0
    count = 0
    for row in rows:
        for pixel in row:
            total += 0.299 * pixel[0] + 0.587 * pixel[1] + 0.114 * pixel[2]
            count += 1
    return total / count if count else 0.0
