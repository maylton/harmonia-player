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


# Messages after which Windows or GDK may have dropped the material: the
# window coming back to the front, a desktop composition or display mode
# change (fullscreen games cause both), a theme change and a DPI change.
# GDK, for one, turns blur-behind back on when composition changes.
WM_ACTIVATE = 0x0006
WM_DISPLAYCHANGE = 0x007E
WM_DPICHANGED = 0x02E0
WM_THEMECHANGED = 0x031A
WM_DWMCOMPOSITIONCHANGED = 0x031E
RESET_MESSAGES = {WM_DISPLAYCHANGE, WM_DPICHANGED, WM_THEMECHANGED, WM_DWMCOMPOSITIONCHANGED}
SWP_REFRESH_FRAME = (
    0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020
)  # no move/size/z/activate + framechanged

_SUBCLASS_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,  # LRESULT
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    ctypes.c_size_t,  # UINT_PTR id
    ctypes.c_size_t,  # DWORD_PTR data
)
_watchers: dict[int, object] = {}


def needs_reapply(message: int, wparam: int) -> bool:
    """Whether the material should be set again after ``message``."""
    if message == WM_ACTIVATE:
        return (wparam & 0xFFFF) != 0  # WA_ACTIVE or WA_CLICKACTIVE
    return message in RESET_MESSAGES


def refresh_frame(hwnd: int) -> None:
    """Make DWM recompute the frame, as minimizing and restoring does."""
    ctypes.windll.user32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, 0, 0, SWP_REFRESH_FRAME)


def watch(hwnd: int, callback) -> None:
    """Call ``callback()`` after the window handled a message that may reset the material.

    A Win32 subclass sees each message after GDK's own window procedure, so
    the material is set once GDK is done with it.
    """
    if hwnd in _watchers:
        return
    comctl32 = ctypes.windll.comctl32
    comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
    comctl32.DefSubclassProc.argtypes = (
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    def procedure(window, message, wparam, lparam, _id, _data):
        result = comctl32.DefSubclassProc(window, message, wparam, lparam)
        if needs_reapply(message, wparam):
            callback()
        return result

    native = _SUBCLASS_PROC(procedure)
    comctl32.SetWindowSubclass.argtypes = (
        wintypes.HWND,
        _SUBCLASS_PROC,
        ctypes.c_size_t,
        ctypes.c_size_t,
    )
    if comctl32.SetWindowSubclass(wintypes.HWND(hwnd), native, 1, 0):
        _watchers[hwnd] = native  # keeps the callback alive


def unwatch(hwnd: int) -> None:
    native = _watchers.pop(hwnd, None)
    if native is not None:
        comctl32 = ctypes.windll.comctl32
        comctl32.RemoveWindowSubclass.argtypes = (wintypes.HWND, _SUBCLASS_PROC, ctypes.c_size_t)
        comctl32.RemoveWindowSubclass(wintypes.HWND(hwnd), native, 1)


def remove(hwnd: int) -> None:
    _attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, DWMSBT_NONE)
    margins = _Margins(0, 0, 0, 0)
    ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(margins))
    _blur_behind(hwnd, True)
