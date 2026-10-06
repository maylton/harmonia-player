"""Windows 11 system backdrops (Mica, Acrylic) behind GTK windows.

DWM paints the material behind the whole window once the frame is extended
into the client area; GTK then only has to leave the surfaces that should
show it transparent. On Windows 10 and older Windows 11 builds the attribute
is rejected, and the caller keeps opaque colours.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_ROUND = 2
DWMSBT_NONE = 1
BACKDROPS = {"mica": 2, "acrylic": 3}


class _Margins(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_int),
        ("right", ctypes.c_int),
        ("top", ctypes.c_int),
        ("bottom", ctypes.c_int),
    )


def _attribute(hwnd: int, attribute: int, value: int) -> bool:
    data = ctypes.c_int(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
    )
    return result == 0


def set_dark(hwnd: int, dark: bool) -> None:
    """Tint the material (and the native shadow) for the current colour scheme."""
    _attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))


def apply(hwnd: int, kind: str, dark: bool) -> bool:
    """Put ``kind`` ("mica" or "acrylic") behind the window; False if unsupported."""
    set_dark(hwnd, dark)
    _attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    margins = _Margins(-1, -1, -1, -1)
    if ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
        wintypes.HWND(hwnd), ctypes.byref(margins)
    ):
        return False
    if _attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, BACKDROPS[kind]):
        return True
    remove(hwnd)
    return False


def remove(hwnd: int) -> None:
    _attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
    margins = _Margins(0, 0, 0, 0)
    ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins))
