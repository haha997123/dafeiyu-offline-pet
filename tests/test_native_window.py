from types import SimpleNamespace
from unittest.mock import patch
import ctypes
import pytest
from app.native_window import set_mouse_passthrough


class WinFunction:
    def __init__(self, result):
        self.result = result
        self.calls = []
    def __call__(self, *args):
        self.calls.append(args)
        return self.result


def test_passthrough_keeps_full_win64_style_and_handle():
    existing = 0x123456780
    get = WinFunction(existing)
    set_ = WinFunction(existing)
    api = SimpleNamespace(GetWindowLongPtrW=get, SetWindowLongPtrW=set_, GetWindowLongW=get, SetWindowLongW=set_)
    with patch("app.native_window.ctypes.WinDLL", return_value=api), \
         patch("app.native_window.ctypes.set_last_error"), \
         patch("app.native_window.ctypes.get_last_error", return_value=0), \
         patch("app.native_window.sys.platform", "win32"):
        set_mouse_passthrough(0x123456789, True)
        assert set_.calls[-1][0].value == 0x123456789
        assert set_.calls[-1][2] == existing | 0x80000 | 0x20
        assert get.restype is ctypes.c_ssize_t
        assert set_.restype is ctypes.c_ssize_t
        set_mouse_passthrough(0x123456789, False)
        assert set_.calls[-1][2] & 0x20 == 0


def test_winapi_failure_is_not_reported_as_a_success():
    get = WinFunction(0)
    set_ = WinFunction(0)
    api = SimpleNamespace(GetWindowLongPtrW=get, SetWindowLongPtrW=set_, GetWindowLongW=get, SetWindowLongW=set_)
    with patch("app.native_window.ctypes.WinDLL", return_value=api), \
         patch("app.native_window.ctypes.set_last_error"), \
         patch("app.native_window.ctypes.get_last_error", return_value=5), \
         patch("app.native_window.sys.platform", "win32"):
        with pytest.raises(OSError):
            set_mouse_passthrough(123, True)
    assert not set_.calls
