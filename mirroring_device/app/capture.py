from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
from ctypes import wintypes
from pathlib import Path

from PySide6.QtGui import QImage

_MIRROR_TITLE = "LetsView[ミラーリング]"


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def letsview_running() -> bool | None:
    if sys.platform == "win32":
        return _windows_letsview_running()
    if sys.platform == "darwin":
        pids = _darwin_letsview_pids()
        if pids is None:
            return None
        return bool(pids)
    return None


def _letsview_pids() -> set[int]:
    if sys.platform == "darwin":
        found = _darwin_letsview_pids()
        return set() if found is None else found
    if sys.platform != "win32":
        return set()
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
    if sys.platform == "darwin":
        return _darwin_mirror_window()
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
    if sys.platform == "darwin":
        return _darwin_capture_mirror()
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


def _windows_letsview_running() -> bool | None:
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
        return None
    if result.returncode != 0:
        return None
    return "letsview.exe" in result.stdout.lower()


def _darwin_letsview_pids() -> set[int] | None:
    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        pid_text, _, command = text.partition(" ")
        if not pid_text.isdigit():
            continue
        base = Path(command).name
        if base.lower() in {"letsview", "letsview.exe"}:
            pids.add(int(pid_text))
    return pids


def _darwin_mirror_window() -> int:
    pids = _letsview_pids()
    if not pids:
        return 0
    windows = _darwin_windows()
    found: list[tuple[int, int]] = []
    for item in windows:
        if item["pid"] not in pids or item["name"] != _MIRROR_TITLE:
            continue
        if item["width"] < 80 or item["height"] < 80:
            continue
        found.append((item["width"] * item["height"], item["number"]))
    if not found:
        return 0
    found.sort()
    return found[-1][1]


def _darwin_capture_mirror() -> QImage | None:
    window_id = _darwin_mirror_window()
    if not window_id:
        return None
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        result = subprocess.run(
            ["screencapture", "-x", "-o", "-l", str(window_id), path],
            check=False,
            capture_output=True,
        )
        if result.returncode != 0:
            return None
        image = QImage(path)
        if image.isNull():
            return None
        return image.copy()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _darwin_windows() -> list[dict[str, int | str]]:
    core = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    core.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    core.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringGetLength.restype = ctypes.c_long
    cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_long,
        ctypes.c_uint32,
    ]
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    array = core.CGWindowListCopyWindowInfo(1, 0)
    if not array:
        return []
    rows: list[dict[str, int | str]] = []
    try:
        count = int(cf.CFArrayGetCount(array))
        for index in range(count):
            item = cf.CFArrayGetValueAtIndex(array, index)
            if not item:
                continue
            name = _cf_dict_string(cf, item, "kCGWindowName")
            number = _cf_dict_int(cf, item, "kCGWindowNumber")
            pid = _cf_dict_int(cf, item, "kCGWindowOwnerPID")
            bounds = _cf_dict_value(cf, item, "kCGWindowBounds")
            width = int(_cf_dict_float(cf, bounds, "Width")) if bounds else 0
            height = int(_cf_dict_float(cf, bounds, "Height")) if bounds else 0
            if number <= 0:
                continue
            rows.append(
                {"number": number, "pid": pid, "name": name, "width": width, "height": height}
            )
    finally:
        cf.CFRelease(array)
    return rows


def _cf_string(cf, text: str) -> ctypes.c_void_p:
    return cf.CFStringCreateWithCString(None, text.encode("utf-8"), 0x08000100)


def _cf_dict_value(cf, item, key: str):
    token = _cf_string(cf, key)
    if not token:
        return None
    try:
        return cf.CFDictionaryGetValue(item, token)
    finally:
        cf.CFRelease(token)


def _cf_dict_string(cf, item, key: str) -> str:
    value = _cf_dict_value(cf, item, key)
    if not value:
        return ""
    length = int(cf.CFStringGetLength(value))
    buf = ctypes.create_string_buffer(max(8, length * 4 + 1))
    if not cf.CFStringGetCString(value, buf, len(buf), 0x08000100):
        return ""
    return buf.value.decode("utf-8", "replace")


def _cf_dict_int(cf, item, key: str) -> int:
    value = _cf_dict_value(cf, item, key)
    if not value:
        return 0
    number = ctypes.c_longlong()
    if not cf.CFNumberGetValue(value, 4, ctypes.byref(number)):
        return 0
    return int(number.value)


def _cf_dict_float(cf, item, key: str) -> float:
    value = _cf_dict_value(cf, item, key)
    if not value:
        return 0.0
    number = ctypes.c_double()
    if not cf.CFNumberGetValue(value, 6, ctypes.byref(number)):
        return 0.0
    return float(number.value)
