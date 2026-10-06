"""The native window handle (HWND) behind a GTK widget, on Windows.

GdkWin32.Win32Surface.get_handle() is only usable when the GdkWin32 typelib
was imported before PyGObject first wrapped a surface; otherwise PyGObject
has already built a bare GdkWin32Surface class without the typelib's
methods. Calling GDK's C function directly does not depend on import order.
"""

from __future__ import annotations

import ctypes


def _pointer(gobject) -> int:
    capsule = gobject.__gpointer__
    get_name = ctypes.pythonapi.PyCapsule_GetName
    get_name.restype = ctypes.c_char_p
    get_name.argtypes = [ctypes.py_object]
    get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
    get_pointer.restype = ctypes.c_void_p
    get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
    return int(get_pointer(capsule, get_name(capsule)) or 0)


def window_handle(widget) -> int | None:
    """The HWND of the surface ``widget`` is drawn on, or None before it is realized."""
    native = widget.get_native()
    surface = native.get_surface() if native is not None else None
    if surface is None:
        return None
    get_handle = ctypes.CDLL("libgtk-4-1.dll").gdk_win32_surface_get_handle
    get_handle.restype = ctypes.c_void_p
    get_handle.argtypes = [ctypes.c_void_p]
    return get_handle(_pointer(surface)) or None
