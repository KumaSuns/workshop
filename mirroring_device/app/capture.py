from __future__ import annotations

import ctypes
import subprocess
from ctypes import wintypes

from PySide6.QtGui import QImage

_MIRROR_TITLE = "LetsView[ミラーリング]"


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _letsview_pids() -> set[int]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Letsview.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=flags,
            check=False,
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split(",")
        if len(parts) < 2 or "letsview.exe" not in parts[0].lower():
            continue
        try:
            pids.add(int(parts[1].strip('"')))
        except ValueError:
            continue
    return pids


def mirror_window() -> int:
    pids = _letsview_pids()
    if not pids:
        return 0
    user32 = ctypes.windll.user32
    found: list[tuple[int, int]] = []

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _lparam):
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if int(proc.value) not in pids or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value != _MIRROR_TITLE:
            return True
        rect = _RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width < 80 or height < 80:
            return True
        found.append((width * height, int(hwnd)))
        return True

    user32.EnumWindows(enum_proc(visit), 0)
    if not found:
        return 0
    found.sort()
    return found[-1][1]


def capture_mirror() -> QImage | None:
    hwnd = mirror_window()
    if not hwnd:
        return None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    rect = _RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if width < 80 or height < 80:
        return None
    hdc = user32.GetDC(0)
    if not hdc:
        return None
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, width, height)
    old = gdi32.SelectObject(mem, bmp)
    ok = gdi32.BitBlt(mem, 0, 0, width, height, hdc, int(rect.left), int(rect.top), 0x00CC0020)
    image = _image_from_bitmap(gdi32, mem, bmp, width, height) if ok else None
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, hdc)
    if image is None or image.isNull():
        return None
    return image


def _image_from_bitmap(gdi32, hdc, hbmp, width: int, height: int) -> QImage | None:
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height
    header.biPlanes = 1
    header.biBitCount = 32
    buf = (ctypes.c_ubyte * (width * height * 4))()
    got = gdi32.GetDIBits(hdc, hbmp, 0, height, buf, ctypes.byref(header), 0)
    if not got:
        return None
    raw = bytes(buf)
    return QImage(raw, width, height, width * 4, QImage.Format.Format_ARGB32).copy()
