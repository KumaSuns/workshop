from __future__ import annotations

import ctypes
import sys
import uuid
from ctypes import wintypes


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _GUID:
    value = uuid.UUID(text)
    return _GUID(
        value.time_low,
        value.time_mid,
        value.time_hi_version,
        (ctypes.c_ubyte * 8).from_buffer_copy(value.bytes[8:]),
    )


def _method(ptr, index, restype, *argtypes):
    table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])


def playback_muted() -> bool | None:
    endpoint = _endpoint()
    if endpoint is None:
        return None
    muted = wintypes.BOOL()
    hr = _method(endpoint, 15, ctypes.HRESULT, ctypes.POINTER(wintypes.BOOL))(
        endpoint, ctypes.byref(muted)
    )
    _release(endpoint)
    if hr < 0:
        return None
    return bool(muted.value)


def mute_playback() -> bool:
    return _set_muted(True)


def _set_muted(on: bool) -> bool:
    if sys.platform != "win32":
        return False
    endpoint = _endpoint()
    if endpoint is None:
        return False
    hr = _method(endpoint, 14, ctypes.HRESULT, wintypes.BOOL, ctypes.c_void_p)(
        endpoint, on, None
    )
    _release(endpoint)
    return hr >= 0


def _endpoint():
    if sys.platform != "win32":
        return None
    ole32 = ctypes.windll.ole32
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.HRESULT
    ole32.CoInitialize(None)
    clsid = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
    iid_enum = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
    device = ctypes.c_void_p()
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    hr = ole32.CoCreateInstance(
        ctypes.byref(clsid), None, 23, ctypes.byref(iid_enum), ctypes.byref(device)
    )
    if hr < 0 or not device.value:
        return None
    endpoint = ctypes.c_void_p()
    hr = _method(
        device,
        4,
        ctypes.HRESULT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    )(device, 0, 0, ctypes.byref(endpoint))
    _release(device)
    if hr < 0 or not endpoint.value:
        return None
    volume = ctypes.c_void_p()
    iid_volume = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")
    hr = _method(
        endpoint,
        3,
        ctypes.HRESULT,
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )(endpoint, ctypes.byref(iid_volume), 23, None, ctypes.byref(volume))
    _release(endpoint)
    if hr < 0 or not volume.value:
        return None
    return volume


def _release(ptr) -> None:
    _method(ptr, 2, ctypes.c_ulong)(ptr)
