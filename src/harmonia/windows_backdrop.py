"""Windows 11 system backdrops (Mica, Acrylic) behind GTK windows.

DWM paints the material behind the whole window once the frame is extended
into the client area; GTK then only has to leave the surfaces that should
show it transparent. On Windows 10 and older Windows 11 builds the attribute
is rejected, and the caller keeps opaque colours.

GDK makes its windows transparent with the legacy blur-behind API (an empty
blur region). Left on, it takes over once the window has been deactivated:
the window turns plainly see-through instead of showing the material or
its inactive colour, and the material does not return on focus. The
extended frame already provides transparency, so blur-behind is switched
off while a material is in use and restored when it is removed.
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
DWM_BB_ENABLE = 0x1
DWM_BB_BLURREGION = 0x2


class _Margins(ctypes.Structure):
    _fields_ = (
        ("left", ctypes.c_int),
        ("right", ctypes.c_int),
        ("top", ctypes.c_int),
        ("bottom", ctypes.c_int),
    )


class _BlurBehind(ctypes.Structure):
    _fields_ = (
        ("flags", wintypes.DWORD),
        ("enable", wintypes.BOOL),
        ("region", wintypes.HRGN),
        ("transition_on_maximized", wintypes.BOOL),
    )


def _attribute(hwnd: int, attribute: int, value: int) -> bool:
    data = ctypes.c_int(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        wintypes.HWND(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
    )
    return result == 0


def _blur_behind(hwnd: int, enable: bool) -> None:
    """Switch GDK's blur-behind transparency (empty blur region) on or off."""
    gdi32 = ctypes.windll.gdi32
    region = gdi32.CreateRectRgn(0, 0, -1, -1) if enable else None
    settings = _BlurBehind(
        DWM_BB_ENABLE | (DWM_BB_BLURREGION if enable else 0), enable, region, False
    )
    try:
        ctypes.windll.dwmapi.DwmEnableBlurBehindWindow(wintypes.HWND(hwnd), ctypes.byref(settings))
    finally:
        if region:
            gdi32.DeleteObject(region)


def set_dark(hwnd: int, dark: bool) -> None:
    """Tint the material (and the native shadow) for the current colour scheme."""
    _attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))


def apply(hwnd: int, kind: str, dark: bool) -> bool:
    """Put ``kind`` ("mica" or "acrylic") behind the window; False if unsupported."""
    set_dark(hwnd, dark)
    _attribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)
    # Order matters: switching blur-behind off after the material is set
    # leaves the window black, so it goes first.
    _blur_behind(hwnd, False)
    margins = _Margins(-1, -1, -1, -1)
    if not ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
        wintypes.HWND(hwnd), ctypes.byref(margins)
    ) and _attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, BACKDROPS[kind]):
        return True
    remove(hwnd)
    return False


def remove(hwnd: int) -> None:
    _attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
    margins = _Margins(0, 0, 0, 0)
    ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins))
    _blur_behind(hwnd, True)
