from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def start_text(image: QImage) -> str:
    if image.width() < 8 or image.height() <= image.width():
        return ""
    small = image.scaled(48, 104, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    small = small.convertToFormat(QImage.Format.Format_RGB32)
    all_band = _band(small, 0, 1)
    line = _band(small, 0.24, 0.38)
    play = _band(small, 0.42, 0.58)
    top = _band(small, 0, 0.18)
    bottom = _band(small, 0.84, 1)
    chars = _band(small, 0.48, 0.75)
    logo = _band(small, 0.22, 0.40)
    button = _band(small, 0.73, 0.84)
    if all_band[1] > 0.82 and line[4] > 0.10 and play[2] > 0.08 and button[3] < 0.05:
        return "起動画面"
    if top[1] > 0.90 and bottom[1] > 0.90 and button[3] > 0.12 and chars[2] > 0.20 and logo[2] > 0.15:
        return "ゲームスタート"
    return ""


def play_mark(image: QImage) -> str:
    if image.width() < 8 or image.height() <= image.width():
        return ""
    word = _play_band(image, 0.18, 0.28, 0.82, 0.50)
    lower = _play_band(image, 0.18, 0.50, 0.82, 0.74)
    if word[0] == 0 or lower[0] == 0:
        return ""
    cyan = word[2] / word[0]
    pink = word[1] / word[0]
    dark = word[3] / word[0]
    blue = word[4] / word[0]
    lower_blue = lower[4] / lower[0]
    lower_dark = lower[3] / lower[0]
    if cyan >= 0.10 and blue >= 0.80 and pink < 0.04 and dark < 0.45 and lower_blue >= 0.90 and lower_dark >= 0.55:
        return "go"
    if _time_up(image):
        return "timeup"
    return ""


def _band(image: QImage, y0: float, y1: float) -> tuple[int, float, float, float, float]:
    width = image.width()
    height = image.height()
    top = int(height * y0)
    bottom = max(top + 1, int(height * y1))
    count = white = sat = yellow = green = 0
    for y in range(top, min(bottom, height)):
        for x in range(width):
            pixel = image.pixel(x, y)
            red = (pixel >> 16) & 255
            green_c = (pixel >> 8) & 255
            blue = pixel & 255
            high = max(red, green_c, blue)
            low = min(red, green_c, blue)
            count += 1
            if red > 230 and green_c > 230 and blue > 230:
                white += 1
            if high - low > 40 and high > 80:
                sat += 1
            if red > 180 and green_c > 140 and blue < 90 and red > blue + 60:
                yellow += 1
            if green_c > red + 30 and green_c > blue + 20 and green_c > 80:
                green += 1
    if count == 0:
        return (0, 0.0, 0.0, 0.0, 0.0)
    return (count, white / count, sat / count, yellow / count, green / count)


def _play_band(image: QImage, x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int, int]:
    width = image.width()
    height = image.height()
    left = min(max(int(width * x0), 0), width - 1)
    top = min(max(int(height * y0), 0), height - 1)
    right = min(max(int(width * x1), left + 1), width)
    bottom = min(max(int(height * y1), top + 1), height)
    crop = image.copy(left, top, right - left, bottom - top)
    small = crop.scaled(40, 16, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    small = small.convertToFormat(QImage.Format.Format_RGB32)
    pink = cyan = dark = blue_n = 0
    for y in range(small.height()):
        for x in range(small.width()):
            pixel = small.pixel(x, y)
            red = (pixel >> 16) & 255
            green = (pixel >> 8) & 255
            blue = pixel & 255
            if red > 180 and blue > 140 and green < 160 and red > green + 40:
                pink += 1
            if green > 150 and blue > 170 and red < 190 and blue > red + 15 and green > red:
                cyan += 1
            if red < 70 and green < 90 and blue < 120:
                dark += 1
            if blue > red + 30 and blue > green and blue > 80 and red < 120:
                blue_n += 1
    return (small.width() * small.height(), pink, cyan, dark, blue_n)


def _time_up(image: QImage) -> bool:
    if image.width() > 180:
        height = max(1, int(image.height() * 180 / image.width()))
        image = image.scaled(
            180,
            height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
    strips = 16
    width = image.width()
    height = image.height()
    x0 = int(width * 0.12)
    x1 = int(width * 0.88)
    x_steps = max(1, len(range(x0, x1, 3)))
    ratios = [[0.0] * 5 for _ in range(strips)]
    samples = [0] * strips
    core_cols = [0] * (strips * x_steps)
    frame = image.convertToFormat(QImage.Format.Format_ARGB32)
    for index in range(strips):
        y0 = height * index // strips
        y1 = height * (index + 1) // strips
        cyan = dark = blue_n = bright = core = total = rows = 0
        for y in range(y0, y1, 3):
            rows += 1
            col = 0
            for x in range(x0, x1, 3):
                pixel = frame.pixel(x, y)
                red = (pixel >> 16) & 255
                green = (pixel >> 8) & 255
                blue = pixel & 255
                total += 1
                if blue > 160 and green > 140 and blue > red + 10 and green + 20 > red:
                    cyan += 1
                if red < 80 and green < 100 and blue < 140:
                    dark += 1
                if blue > red + 30 and blue > green and blue > 90 and red < 140:
                    blue_n += 1
                if red + green + blue > 500:
                    bright += 1
                if blue > 180 and green > 170 and red > 120 and blue > red and green > red - 10:
                    core += 1
                    core_cols[index * x_steps + col] += 1
                col += 1
        samples[index] = rows
        if total == 0:
            continue
        ratios[index][0] = cyan / total
        ratios[index][1] = dark / total
        ratios[index][2] = blue_n / total
        ratios[index][3] = bright / total
        ratios[index][4] = core / total
    for index in range(strips):
        band_y = index / strips
        if band_y < 0.18 or band_y > 0.55:
            continue
        if ratios[index][0] < 0.18 or ratios[index][3] < 0.12 or ratios[index][4] < 0.15:
            continue
        if samples[index] == 0 or x_steps == 0:
            continue
        marked = 0
        for col in range(x_steps):
            if core_cols[index * x_steps + col] / samples[index] > 0.08:
                marked += 1
        if marked / x_steps < 0.48:
            continue
        run = 0
        for follow in range(index + 1, strips):
            if follow / strips >= 0.84:
                break
            if ratios[follow][1] < 0.80 or ratios[follow][2] >= 0.30:
                break
            run += 1
        if run >= 4:
            return True
    return False
