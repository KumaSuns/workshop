from __future__ import annotations

import sys

_VK = {
    "Backspace": 0x08,
    "Tab": 0x09,
    "Enter": 0x0D,
    "ShiftLeft": 0xA0,
    "ShiftRight": 0xA1,
    "ControlLeft": 0xA2,
    "ControlRight": 0xA3,
    "AltLeft": 0xA4,
    "AltRight": 0xA5,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "Escape": 0x1B,
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "ArrowLeft": 0x25,
    "ArrowUp": 0x26,
    "ArrowRight": 0x27,
    "ArrowDown": 0x28,
    "Insert": 0x2D,
    "Delete": 0x2E,
    "MetaLeft": 0x5B,
    "MetaRight": 0x5C,
    "ContextMenu": 0x5D,
    "NumpadDivide": 0x6F,
    "NumpadMultiply": 0x6A,
    "NumpadSubtract": 0x6D,
    "NumpadAdd": 0x6B,
    "NumpadDecimal": 0x6E,
    "NumpadEnter": 0x0D,
    "IntlRo": 0xE2,
    "IntlYen": 0xDC,
    "Convert": 0x1C,
    "NonConvert": 0x1D,
    "KanaMode": 0x15,
    "Lang1": 0x15,
    "Lang2": 0x19,
    "Minus": 0xBD,
    "Equal": 0xBB,
    "BracketLeft": 0xDB,
    "BracketRight": 0xDD,
    "Backslash": 0xDC,
    "Semicolon": 0xBA,
    "Quote": 0xDE,
    "Backquote": 0xC0,
    "Comma": 0xBC,
    "Period": 0xBE,
    "Slash": 0xBF,
}


def _fill_vk() -> None:
    for index in range(10):
        _VK[f"Digit{index}"] = 0x30 + index
        _VK[f"Numpad{index}"] = 0x60 + index
    for index, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        _VK[f"Key{letter}"] = 0x41 + index
    for index in range(1, 13):
        _VK[f"F{index}"] = 0x6F + index


_fill_vk()


def move_mouse(nx: float, ny: float, screen: tuple[int, int, int, int]) -> None:
    if sys.platform != "win32":
        return
    left, top, width, height = screen
    if width < 2 or height < 2:
        return
    x = left + int(max(0.0, min(1.0, nx)) * (width - 1))
    y = top + int(max(0.0, min(1.0, ny)) * (height - 1))
    _send_mouse(x, y, 0x0001, absolute=True)


def mouse_button(nx: float, ny: float, button: int, down: bool, screen: tuple[int, int, int, int]) -> None:
    move_mouse(nx, ny, screen)
    flags = {
        0: (0x0002, 0x0004),
        1: (0x0020, 0x0040),
        2: (0x0008, 0x0010),
    }.get(int(button))
    if flags is None:
        return
    flag = flags[0] if down else flags[1]
    left, top, width, height = screen
    x = left + int(max(0.0, min(1.0, nx)) * (width - 1))
    y = top + int(max(0.0, min(1.0, ny)) * (height - 1))
    _send_mouse(x, y, 0x0001 | flag, absolute=True)


def mouse_wheel(delta: int) -> None:
    if sys.platform != "win32":
        return
    amount = int(delta)
    if abs(amount) < 40:
        amount *= 120
    _send_mouse(0, 0, 0x0800, amount, absolute=False)


def key_event(code: str, down: bool) -> None:
    if sys.platform != "win32":
        return
    vk = _VK.get(code)
    if vk is None:
        return
    _send_key(vk, down)


def _send_mouse(x: int, y: int, flags: int, data: int = 0, absolute: bool = True) -> None:
    import ctypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]

    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    ax, ay = x, y
    send_flags = flags
    if absolute:
        vx = user32.GetSystemMetrics(76)
        vy = user32.GetSystemMetrics(77)
        vw = max(1, user32.GetSystemMetrics(78) - 1)
        vh = max(1, user32.GetSystemMetrics(79) - 1)
        ax = int((x - vx) * 65535 / vw)
        ay = int((y - vy) * 65535 / vh)
        send_flags = flags | 0x8000 | 0x4000
    inp = INPUT(
        type=0,
        union=_INPUTunion(mi=MOUSEINPUT(ax, ay, data & 0xFFFFFFFF, send_flags, 0, None)),
    )
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _send_key(vk: int, down: bool) -> None:
    import ctypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.c_ushort),
            ("wScan", ctypes.c_ushort),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]

    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    flags = 0 if down else 0x0002
    inp = INPUT(type=1, union=_INPUTunion(ki=KEYBDINPUT(vk, 0, flags, 0, None)))
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
