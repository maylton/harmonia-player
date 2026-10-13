"""Ask KWin to blur what is behind the window, as Konsole and Kitty do.

KWin's Blur effect blurs behind any window that asks for it: on Wayland with
the org_kde_kwin_blur protocol, on X11 with the _KDE_NET_WM_BLUR_BEHIND_REGION
property. GTK has no API for either, so this talks to them directly:
libwayland-client on GTK's own connection, in an event queue of its own so
GTK's dispatching is not disturbed, and Xlib for the property.

The region is the window without its client-side shadow, with the rounded
corners cut out, so the blur does not show around them.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_int,
    c_int32,
    c_long,
    c_uint32,
    c_ulong,
    c_void_p,
)

LOGGER = logging.getLogger(__name__)
BLUR_MANAGER = b"org_kde_kwin_blur_manager"
DESTROY = 1  # WL_MARSHAL_FLAG_DESTROY
Rect = tuple[int, int, int, int]


def rounded_rect_region(x: int, y: int, width: int, height: int, radius: int) -> list[Rect]:
    """Rectangles covering a rounded rectangle, the corners stepped every 2 pixels."""
    radius = max(0, min(radius, width // 2, height // 2))
    if radius < 2:
        return [(x, y, width, height)]
    rects: list[Rect] = []
    step = 2
    for top in range(0, radius, step):
        band = min(step, radius - top)
        middle = top + band / 2
        # How far the arc stays inside the corner at this height.
        inset = round(radius - (radius**2 - (radius - middle) ** 2) ** 0.5)
        rects.append((x + inset, y + top, width - 2 * inset, band))
        rects.append((x + inset, y + height - top - band, width - 2 * inset, band))
    rects.append((x, y + radius, width, height - 2 * radius))
    return rects


# --- Wayland -----------------------------------------------------------------


class WlMessage(Structure):
    _fields_ = (("name", c_char_p), ("signature", c_char_p), ("types", POINTER(c_void_p)))


class WlInterface(Structure):
    pass


WlInterface._fields_ = (
    ("name", c_char_p),
    ("version", c_int),
    ("method_count", c_int),
    ("methods", POINTER(WlMessage)),
    ("event_count", c_int),
    ("events", POINTER(WlMessage)),
)

GLOBAL = CFUNCTYPE(None, c_void_p, c_void_p, c_uint32, c_char_p, c_uint32)
GLOBAL_REMOVE = CFUNCTYPE(None, c_void_p, c_void_p, c_uint32)


class RegistryListener(Structure):
    _fields_ = (("global_", GLOBAL), ("global_remove", GLOBAL_REMOVE))


def _messages(*entries: tuple[bytes, bytes, list[int | None]]):
    """A wl_message array, and what must stay alive while it is used."""
    keep = []
    array = (WlMessage * len(entries))()
    for index, (name, signature, types) in enumerate(entries):
        type_array = (c_void_p * max(1, len(types)))(*types)
        keep.append(type_array)
        array[index] = WlMessage(name, signature, ctypes.cast(type_array, POINTER(c_void_p)))
    return array, keep


class WaylandBlur:
    """The org_kde_kwin_blur protocol on GTK's Wayland connection."""

    def __init__(self, display_pointer: int) -> None:
        self._lib = ctypes.CDLL(
            ctypes.util.find_library("wayland-client") or "libwayland-client.so.0"
        )
        self._display = c_void_p(display_pointer)
        self._marshal = self._lib.wl_proxy_marshal_flags
        self._marshal.restype = c_void_p
        self._lib.wl_display_create_queue.restype = c_void_p
        self._lib.wl_proxy_create_wrapper.restype = c_void_p
        self._lib.wl_proxy_get_version.restype = c_uint32
        self._lib.wl_proxy_get_version.argtypes = (c_void_p,)
        self._interfaces()
        self._globals: dict[bytes, tuple[int, int]] = {}
        self.manager = self.compositor = None
        self._blurs: dict[int, int] = {}
        self._bind()

    def _interface(self, name: str) -> int:
        return ctypes.addressof(WlInterface.in_dll(self._lib, name))

    def _interfaces(self) -> None:
        self.registry_interface = self._interface("wl_registry_interface")
        self.compositor_interface = self._interface("wl_compositor_interface")
        self.region_interface = self._interface("wl_region_interface")
        surface = self._interface("wl_surface_interface")
        # org_kde_kwin_blur: commit, set_region(region?), release.
        self.blur = WlInterface()
        blur_methods, keep_blur = _messages(
            (b"commit", b"", []),
            (b"set_region", b"?o", [self.region_interface]),
            (b"release", b"", []),
        )
        self.blur.name, self.blur.version = b"org_kde_kwin_blur", 1
        self.blur.method_count, self.blur.methods = 3, blur_methods
        # org_kde_kwin_blur_manager: create(new_id blur, surface), unset(surface).
        self.manager_interface_struct = WlInterface()
        manager_methods, keep_manager = _messages(
            (b"create", b"no", [ctypes.addressof(self.blur), surface]),
            (b"unset", b"o", [surface]),
        )
        self.manager_interface_struct.name = BLUR_MANAGER
        self.manager_interface_struct.version = 1
        self.manager_interface_struct.method_count = 2
        self.manager_interface_struct.methods = manager_methods
        self._keep = (blur_methods, manager_methods, keep_blur, keep_manager)

    def _call(self, proxy, opcode: int, interface: int | None, *args, flags: int = 0):
        version = self._lib.wl_proxy_get_version(proxy)
        return self._marshal(
            c_void_p(proxy), c_uint32(opcode), c_void_p(interface), c_uint32(version),
            c_uint32(flags), *args,
        )  # fmt: skip

    def _bind(self) -> None:
        lib = self._lib
        self._queue = c_void_p(lib.wl_display_create_queue(self._display))
        wrapper = c_void_p(lib.wl_proxy_create_wrapper(self._display))
        lib.wl_proxy_set_queue(wrapper, self._queue)
        registry = self._call(wrapper, 1, self.registry_interface, c_void_p(None))
        lib.wl_proxy_wrapper_destroy(wrapper)

        def announced(_data, _registry, name, interface, version):
            self._globals[interface] = (name, version)

        self._listener = RegistryListener(GLOBAL(announced), GLOBAL_REMOVE(lambda *_: None))
        lib.wl_proxy_add_listener(c_void_p(registry), byref(self._listener), None)
        lib.wl_display_roundtrip_queue(self._display, self._queue)
        self._registry = registry
        if BLUR_MANAGER in self._globals and b"wl_compositor" in self._globals:
            self.manager = self._bind_global(
                BLUR_MANAGER, ctypes.addressof(self.manager_interface_struct), 1
            )
            self.compositor = self._bind_global(b"wl_compositor", self.compositor_interface, 4)

    def _bind_global(self, name: bytes, interface: int, highest: int) -> int:
        number, version = self._globals[name]
        version = min(version, highest)
        return self._marshal(
            c_void_p(self._registry), c_uint32(0), c_void_p(interface), c_uint32(version),
            c_uint32(0), c_uint32(number), c_char_p(name), c_uint32(version), c_void_p(None),
        )  # fmt: skip

    @property
    def available(self) -> bool:
        return bool(self.manager and self.compositor)

    def set_region(self, surface_pointer: int, rects: list[Rect]) -> None:
        """Blur behind ``rects`` of the surface, from its next commit."""
        blur = self._blurs.get(surface_pointer)
        if blur is None:
            blur = self._call(self.manager, 0, ctypes.addressof(self.blur), c_void_p(None),
                              c_void_p(surface_pointer))  # fmt: skip
            self._blurs[surface_pointer] = blur
        region = self._call(self.compositor, 1, self.region_interface, c_void_p(None))
        for x, y, width, height in rects:
            self._call(region, 1, None, c_int32(x), c_int32(y), c_int32(width), c_int32(height))
        self._call(blur, 1, None, c_void_p(region))
        self._call(blur, 0, None)
        self._call(region, 0, None, flags=DESTROY)
        self._lib.wl_display_flush(self._display)

    def unset(self, surface_pointer: int) -> None:
        blur = self._blurs.pop(surface_pointer, None)
        if blur is not None:
            self._call(self.manager, 1, None, c_void_p(surface_pointer))
            self._call(blur, 2, None, flags=DESTROY)
            self._lib.wl_display_flush(self._display)


# --- X11 ---------------------------------------------------------------------


class X11Blur:
    """KWin's _KDE_NET_WM_BLUR_BEHIND_REGION property on X11."""

    def __init__(self, xdisplay: int) -> None:
        self._lib = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self._display = c_void_p(xdisplay)
        self._lib.XInternAtom.restype = c_ulong
        self._lib.XInternAtom.argtypes = (c_void_p, c_char_p, c_int)
        # Only KWin with its Blur effect knows the atom.
        self._atom = self._lib.XInternAtom(self._display, b"_KDE_NET_WM_BLUR_BEHIND_REGION", 1)

    @property
    def available(self) -> bool:
        return bool(self._atom)

    def set_region(self, xid: int, rects: list[Rect]) -> None:
        values = [value for rect in rects for value in rect]
        data = (c_long * len(values))(*values)
        self._lib.XChangeProperty(
            self._display, c_ulong(xid), c_ulong(self._atom), c_ulong(6),  # XA_CARDINAL
            32, 0, data, len(values),  # PropModeReplace
        )  # fmt: skip
        self._lib.XFlush(self._display)

    def unset(self, xid: int) -> None:
        self._lib.XDeleteProperty(self._display, c_ulong(xid), c_ulong(self._atom))
        self._lib.XFlush(self._display)


def _pointer(value) -> int:
    """A gpointer from introspection: an int, or a PyCapsule on some versions."""
    if isinstance(value, int):
        return value
    getter = ctypes.pythonapi.PyCapsule_GetPointer
    getter.restype, getter.argtypes = c_void_p, (ctypes.py_object, c_char_p)
    return getter(value, None)


def connect(display) -> WaylandBlur | X11Blur | None:
    """KWin's blur for this GdkDisplay, or None when nothing will blur."""
    import gi

    name = type(display).__name__
    try:
        if "Wayland" in name:
            gi.require_version("GdkWayland", "4.0")
            from gi.repository import GdkWayland  # noqa: F401

            backend = WaylandBlur(_pointer(display.get_wl_display()))
        elif "X11" in name and "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            gi.require_version("GdkX11", "4.0")
            from gi.repository import GdkX11  # noqa: F401

            backend = X11Blur(_pointer(display.get_xdisplay()))
        else:
            return None
    except (OSError, ValueError, ImportError, AttributeError):
        LOGGER.debug("Blur do KWin indisponível", exc_info=True)
        return None
    return backend if backend.available else None


def surface_handle(surface) -> int | None:
    """The wl_surface or X11 window of a GdkSurface."""
    if hasattr(surface, "get_wl_surface"):
        return _pointer(surface.get_wl_surface())
    if hasattr(surface, "get_xid"):
        return int(surface.get_xid())
    return None
