from __future__ import annotations

import os
import re
import subprocess
import tempfile
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


def swipe_path(points: list[tuple[int, int]], duration_ms: int = 450) -> None:
    if len(points) < 2:
        return
    dense = _dense_points(points)
    x0, y0 = dense[0]
    cmds = [f"input motionevent DOWN {x0} {y0}"]
    for x, y in dense[1:]:
        cmds.append(f"input motionevent MOVE {x} {y}")
    xl, yl = dense[-1]
    cmds.append(f"input motionevent UP {xl} {yl}")
    result = adb(["shell", " ; ".join(cmds)], timeout=20)
    if result.returncode == 0:
        return
    x1, y1 = points[0]
    x2, y2 = points[-1]
    fallback = adb(
        ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(int(duration_ms))],
        timeout=10,
    )
    if fallback.returncode != 0:
        err = (fallback.stderr or fallback.stdout or b"").decode("utf-8", "ignore").strip()
        raise RuntimeError(err or "なぞれませんでした。")


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
