"""Small, correctly typed Win32 helpers for the pet's own window only."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def set_mouse_passthrough(handle: int, enabled: bool) -> None:
    if sys.platform != "win32":
        raise OSError("鼠标穿透仅在 Windows 上可用")
    api = ctypes.WinDLL("user32", use_last_error=True)
    get_style = getattr(api, "GetWindowLongPtrW", api.GetWindowLongW)
    set_style = getattr(api, "SetWindowLongPtrW", api.SetWindowLongW)
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    set_style.restype = ctypes.c_ssize_t
    ctypes.set_last_error(0)
    current = get_style(wintypes.HWND(handle), -20)
    error = ctypes.get_last_error()
    if current == 0 and error:
        raise ctypes.WinError(error)
    updated = current | 0x80000
    updated = updated | 0x20 if enabled else updated & ~0x20
    ctypes.set_last_error(0)
    result = set_style(wintypes.HWND(handle), -20, updated)
    error = ctypes.get_last_error()
    if result == 0 and error:
        raise ctypes.WinError(error)

