from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtGui import QImage

PACKAGE = "com.linecorp.LGTMTM"
SHORTCUT_NAME = "ツムツム.lnk"
INSTANCE = "Pie64"
PLAYER = Path(r"C:\Program Files\BlueStacks_nxt\HD-Player.exe")
ADB = Path(r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe")
CONF = Path(r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf")
_REMOTE_CAP = "/data/local/tmp/tsum_autoplay.png"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_REMOTE_DRAG = "/data/local/tmp/tsum_drag.sh"
_touch_dev: tuple[str, int, int] | None | bool = None


def tsum_is_running() -> bool:
    if not _hd_player_running():
        return False
    return _package_running()


def start_tsum(desktop: str) -> Path | None:
    shortcut = _find_shortcut(desktop)
    if shortcut is not None:
        os.startfile(str(shortcut))
        return shortcut
    if not PLAYER.exists():
        raise FileNotFoundError("BlueStacks が見つかりませんでした。")
    subprocess.Popen(
        [
            str(PLAYER),
            "--instance",
            INSTANCE,
            "--cmd",
            "launchApp",
            "--package",
            PACKAGE,
            "--source",
            "desktop_shortcut",
        ],
        cwd=str(PLAYER.parent),
        creationflags=_NO_WINDOW,
    )
    return None


def _find_shortcut(desktop: str) -> Path | None:
    dirs = [Path(desktop)]
    public = os.environ.get("PUBLIC")
    if public:
        dirs.append(Path(public) / "Desktop")
    for folder in dirs:
        path = folder / SHORTCUT_NAME
        if path.is_file():
            return path
    return None


def _hd_player_running() -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq HD-Player.exe", "/FO", "CSV", "/NH"],
        check=False,
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
    )
    return "HD-Player.exe" in (result.stdout or "")


def _adb_port() -> str:
    if CONF.exists():
        text = CONF.read_text(encoding="utf-8", errors="ignore")
        match = re.search(rf'bst\.instance\.{re.escape(INSTANCE)}\.adb_port="(\d+)"', text)
        if match:
            return match.group(1)
    return "5555"


def _package_running() -> bool:
    if not ADB.exists():
        return False
    serial = f"127.0.0.1:{_adb_port()}"
    try:
        subprocess.run(
            [str(ADB), "connect", serial],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=_NO_WINDOW,
        )
        result = subprocess.run(
            [str(ADB), "-s", serial, "shell", "pidof", PACKAGE],
            check=False,
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    out = (result.stdout or "").strip()
    return bool(out) and any(part.isdigit() for part in out.replace("\t", " ").split())


def adb_serial() -> str:
    return f"127.0.0.1:{_adb_port()}"


def adb(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess[bytes]:
    if not ADB.exists():
        raise FileNotFoundError("BlueStacks の adb が見つかりませんでした。")
    serial = adb_serial()
    subprocess.run(
        [str(ADB), "connect", serial],
        check=False,
        capture_output=True,
        timeout=4,
        creationflags=_NO_WINDOW,
    )
    return subprocess.run(
        [str(ADB), "-s", serial, *args],
        check=False,
        capture_output=True,
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )


def capture_screen_path() -> Path:
    local = Path(tempfile.gettempdir()) / "tsum_autoplay.png"
    result = adb(["shell", "screencap", "-p", _REMOTE_CAP], timeout=10)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(err or "画面を取れませんでした。")
    pulled = adb(["pull", _REMOTE_CAP, str(local)], timeout=10)
    if pulled.returncode != 0 or not local.exists():
        err = (pulled.stderr or pulled.stdout or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(err or "画面の保存に失敗しました。")
    return local


def capture_screen() -> QImage:
    local = capture_screen_path()
    image = QImage(str(local))
    if image.isNull():
        raise RuntimeError("画面画像を読めませんでした。")
    return image


def tap(x: int, y: int, hold_ms: int = 180) -> None:
    xi, yi = str(int(x)), str(int(y))
    result = adb(["shell", "input", "tap", xi, yi], timeout=6)
    if result.returncode != 0:
        result = adb(
            ["shell", "input", "swipe", xi, yi, xi, yi, str(int(hold_ms))],
            timeout=6,
        )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(err or "タップできませんでした。")


def halt_input() -> None:
    for args in (
        ["shell", "pkill", "-9", "monkey"],
        ["shell", "killall", "-9", "monkey"],
    ):
        try:
            adb(args, timeout=3)
        except Exception:
            pass


def swipe_path(
    points: list[tuple[int, int]],
    duration_ms: int = 800,
    screen_w: int = 0,
    screen_h: int = 0,
    stop=None,
) -> str:
    if stop is not None and stop.is_set():
        return "停止"
    if len(points) < 3:
        return "点が3未満"
    hops = [
        ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        for (x0, y0), (x1, y1) in zip(points, points[1:])
    ]
    if min(hops) < 32:
        return "ツムが近すぎる"
    dense = _dense_points(points, step=12)
    how = _swipe_mouse(dense, screen_w, screen_h)
    if how:
        return how
    if stop is not None and stop.is_set():
        return "停止"
    if _swipe_sendevent(dense, screen_w, screen_h):
        return "sendeventでなぞった"
    return "なぞり失敗"


def _swipe_mouse(dense: list[tuple[int, int]], screen_w: int, screen_h: int) -> str:
    if sys.platform != "win32" or screen_w < 2 or screen_h < 2:
        return ""
    import ctypes
    from ctypes import wintypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    user32 = ctypes.windll.user32
    rect = _android_view_rect(user32, wintypes, screen_w, screen_h)
    if rect is None:
        return ""
    left, top, right, bottom = rect
    rw = right - left
    rh = bottom - top
    if rw < 50 or rh < 50:
        return ""
    scale = min(rw / screen_w, rh / screen_h)
    ox = left + (rw - screen_w * scale) / 2
    oy = top + (rh - screen_h * scale) / 2
    mapped = [
        (int(ox + x * scale), int(oy + y * scale))
        for x, y in dense
    ]
    hwnd = _player_hwnd(user32, wintypes)
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_SHOWWINDOW = 0x0040
    if hwnd:
        user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
        )
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
    try:
        x0, y0 = mapped[0]
        user32.SetCursorPos(x0, y0)
        time.sleep(0.03)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.08)
        for x, y in mapped[1:]:
            user32.SetCursorPos(x, y)
            time.sleep(0.016)
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    finally:
        if hwnd:
            user32.SetWindowPos(
                hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
            )
    return f"マウス {len(dense)}点"


def _player_hwnd(user32, wintypes):
    import ctypes

    found: list[tuple[int, int]] = []

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.lower()
        if "bluestacks" in title or "pie64" in title or "hd-player" in title:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            found.append((area, hwnd))
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(enum_proc(_cb), 0)
    if not found:
        return 0
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1]


def _android_view_rect(
    user32, wintypes, screen_w: int = 0, screen_h: int = 0
) -> tuple[int, int, int, int] | None:
    import ctypes

    hwnd = _player_hwnd(user32, wintypes)
    if not hwnd:
        return None
    kids: list[tuple[float, int, tuple[int, int, int, int]]] = []
    want = (screen_w / screen_h) if screen_w > 0 and screen_h > 0 else 0.0

    def _cb(ch, _lparam):
        if not user32.IsWindowVisible(ch):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(ch, ctypes.byref(rect))
        rw = max(0, rect.right - rect.left)
        rh = max(0, rect.bottom - rect.top)
        area = rw * rh
        if area < 40000 or rh < 80:
            return True
        aspect = rw / rh
        mismatch = abs(aspect - want) if want else 0.0
        kids.append((mismatch, -area, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumChildWindows(hwnd, enum_proc(_cb), 0)
    if kids:
        kids.sort()
        return kids[0][2]
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return (pt.x, pt.y, pt.x + rect.right, pt.y + rect.bottom)


def _swipe_sendevent(dense: list[tuple[int, int]], screen_w: int, screen_h: int) -> bool:
    info = _touch_device()
    if info is None:
        return False
    dev, max_x, max_y = info
    lines = ["#!/system/bin/sh"]
    sx, sy = _scale_touch(dense[0][0], dense[0][1], max_x, max_y, screen_w, screen_h)
    lines.extend(
        [
            f"sendevent {dev} 1 330 1",
            f"sendevent {dev} 3 47 0",
            f"sendevent {dev} 3 57 1",
            f"sendevent {dev} 3 53 {sx}",
            f"sendevent {dev} 3 54 {sy}",
            f"sendevent {dev} 3 48 8",
            f"sendevent {dev} 3 58 40",
            f"sendevent {dev} 0 0 0",
            "usleep 100000",
        ]
    )
    for x, y in dense[1:]:
        mx, my = _scale_touch(x, y, max_x, max_y, screen_w, screen_h)
        lines.extend(
            [
                f"sendevent {dev} 3 53 {mx}",
                f"sendevent {dev} 3 54 {my}",
                f"sendevent {dev} 0 0 0",
                "usleep 25000",
            ]
        )
    lines.extend(
        [
            "usleep 60000",
            f"sendevent {dev} 3 57 4294967295",
            f"sendevent {dev} 1 330 0",
            f"sendevent {dev} 0 0 0",
        ]
    )
    local = Path(tempfile.gettempdir()) / "tsum_drag.sh"
    local.write_text("\n".join(lines) + "\n", encoding="ascii")
    pushed = adb(["push", str(local), _REMOTE_DRAG], timeout=10)
    if pushed.returncode != 0:
        return False
    result = adb(["shell", "sh", _REMOTE_DRAG], timeout=25)
    return result.returncode == 0


def _touch_device() -> tuple[str, int, int] | None:
    global _touch_dev
    if _touch_dev is False:
        return None
    if isinstance(_touch_dev, tuple):
        return _touch_dev
    parsed = _touch_from_proc()
    if parsed is None:
        result = adb(["shell", "getevent", "-pl"], timeout=8)
        text = ((result.stdout or b"") + (result.stderr or b"")).decode("utf-8", "ignore")
        parsed = _parse_touch_device(text)
    _touch_dev = parsed if parsed is not None else False
    return parsed


def _touch_from_proc() -> tuple[str, int, int] | None:
    result = adb(["shell", "cat", "/proc/bus/input/devices"], timeout=6)
    text = ((result.stdout or b"") + (result.stderr or b"")).decode("utf-8", "ignore")
    path = _parse_proc_touch(text)
    if path is None:
        return None
    props = adb(["shell", "getevent", "-p", path], timeout=6)
    prop_text = ((props.stdout or b"") + (props.stderr or b"")).decode("utf-8", "ignore")
    parsed = _parse_touch_device(prop_text)
    if parsed is not None:
        return parsed
    return path, 0, 0


def _parse_proc_touch(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for block in text.split("\n\n"):
        name = ""
        handler = None
        has_abs = False
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("H: Handlers="):
                match = re.search(r"event(\d+)", line)
                if match:
                    handler = f"/dev/input/event{match.group(1)}"
            elif line.startswith("B: ABS=") and not line.rstrip().endswith("=0"):
                has_abs = True
        if not handler or not has_abs:
            continue
        lowered = name.lower()
        score = 1
        if any(word in lowered for word in ("touch", "finger", "tscreen")):
            score = 3
        elif "mouse" in lowered:
            score = 0
        if score == 0:
            continue
        if best is None or score > best[0]:
            best = (score, handler)
    return best[1] if best else None


def _parse_touch_device(text: str) -> tuple[str, int, int] | None:
    devices: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        match = re.match(r"add device \d+:\s+(\S+)", line)
        if match:
            if current is not None:
                devices.append(current)
            current = {"path": match.group(1), "codes": {}}
            continue
        if current is None:
            continue
        code = re.match(r"\s+([0-9a-f]{4})\s+:.*max\s+(\d+)", line, re.I)
        if code:
            current["codes"][int(code.group(1), 16)] = int(code.group(2))
    if current is not None:
        devices.append(current)
    for device in devices:
        codes = device["codes"]
        if 0x35 in codes and 0x36 in codes:
            return str(device["path"]), int(codes[0x35]), int(codes[0x36])
    for device in devices:
        codes = device["codes"]
        if 0x00 in codes and 0x01 in codes and int(codes[0x00]) > 100:
            return str(device["path"]), int(codes[0x00]), int(codes[0x01])
    return None


def _scale_touch(x: int, y: int, max_x: int, max_y: int, screen_w: int, screen_h: int) -> tuple[int, int]:
    if screen_w > 1 and screen_h > 1 and max_x > 0 and max_y > 0:
        sx = int(round(x * max_x / (screen_w - 1)))
        sy = int(round(y * max_y / (screen_h - 1)))
        return min(max_x, max(0, sx)), min(max_y, max(0, sy))
    return int(x), int(y)


def _dense_points(points: list[tuple[int, int]], step: int = 14) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for index, (x1, y1) in enumerate(points):
        if index == 0:
            out.append((int(x1), int(y1)))
            continue
        x0, y0 = out[-1]
        dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        count = max(1, int(dist / step))
        for k in range(1, count + 1):
            t = k / count
            out.append((int(round(x0 + (x1 - x0) * t)), int(round(y0 + (y1 - y0) * t))))
    return out
