"""Embedded Google login on Windows, through the system's Edge WebView2.

WebKitGTK does not exist on Windows, but Windows 10 and 11 ship the WebView2
runtime. This module drives its COM API through ctypes (WebView2Loader.dll
creates the environment) and hosts the browser as a child window of a GTK
dialog, over a placeholder widget that reserves its place below the header
bar. It mirrors auth.LoginWindow: once the page reaches music.youtube.com,
the cookie manager hands over the session cookies, HttpOnly ones included.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkWin32", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, GdkWin32, GLib, Graphene, Gtk  # noqa: E402

from .i18n import _  # noqa: E402
from .login import LOGIN_URL, MUSIC_ORIGIN, session_cookie_header  # noqa: E402

LOGGER = logging.getLogger(__name__)
HRESULT = ctypes.c_long
COINIT_APARTMENTTHREADED = 0x2
RPC_E_CHANGED_MODE = -2147417850

# Method positions in the COM vtables, from WebView2.h.
IUNKNOWN_QUERY, IUNKNOWN_ADD_REF, IUNKNOWN_RELEASE = 0, 1, 2
ENVIRONMENT_CREATE_CONTROLLER = 3
CONTROLLER_PUT_BOUNDS = 6
CONTROLLER_CLOSE = 24
CONTROLLER_GET_WEBVIEW = 25
WEBVIEW_GET_SETTINGS = 3
WEBVIEW_GET_SOURCE = 4
WEBVIEW_NAVIGATE = 5
WEBVIEW_ADD_NAVIGATION_COMPLETED = 15
WEBVIEW_GET_CAN_GO_BACK = 38
WEBVIEW_GO_BACK = 40
WEBVIEW2_GET_COOKIE_MANAGER = 66
SETTINGS_PUT_DEV_TOOLS = 12
SETTINGS_PUT_HOST_OBJECTS = 16
COOKIES_GET = 5
COOKIE_LIST_COUNT = 3
COOKIE_LIST_AT = 4
COOKIE_GET_NAME = 3
COOKIE_GET_VALUE = 4
IID_ICOREWEBVIEW2_2 = "{9E8F0CF8-E670-4B5E-B2BC-73E061E3184C}"


class WebView2Error(OSError):
    pass


def check(result: int, what: str) -> None:
    if result < 0:
        code = result & 0xFFFFFFFF
        raise WebView2Error(code, f"{what}: 0x{code:08X}")


class Com:
    """A raw COM interface pointer whose methods are called by vtable index."""

    def __init__(self, pointer) -> None:
        self.pointer = ctypes.c_void_p(pointer)

    def _slot(self, index: int) -> int:
        vtable = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        return vtable[index]

    def call(self, index: int, argtypes: tuple, *args, what: str = "") -> None:
        method = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *argtypes)(self._slot(index))
        check(method(self.pointer, *args), what or f"método {index}")

    def out_pointer(self, index: int, what: str = "") -> Com:
        result = ctypes.c_void_p()
        self.call(index, (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(result), what=what)
        return Com(result.value)

    def out_string(self, index: int, what: str = "") -> str:
        result = ctypes.c_void_p()
        self.call(index, (ctypes.POINTER(ctypes.c_void_p),), ctypes.byref(result), what=what)
        if not result.value:
            return ""
        try:
            return ctypes.wstring_at(result.value)
        finally:
            ctypes.windll.ole32.CoTaskMemFree(result)

    def query(self, iid: str) -> Com:
        guid = (ctypes.c_byte * 16)()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(iid), ctypes.byref(guid))
        result = ctypes.c_void_p()
        self.call(
            IUNKNOWN_QUERY,
            (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)),
            ctypes.byref(guid),
            ctypes.byref(result),
            what="QueryInterface",
        )
        return Com(result.value)

    def add_ref(self) -> Com:
        """Keep a borrowed pointer (a handler's argument) after the call returns."""
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(self._slot(IUNKNOWN_ADD_REF))(
            self.pointer
        )
        return self

    def release(self) -> None:
        if self.pointer.value:
            ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(self._slot(IUNKNOWN_RELEASE))(
                self.pointer
            )
            self.pointer = ctypes.c_void_p()


_QUERY = ctypes.WINFUNCTYPE(
    HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
)
_REFCOUNT = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
# Completion handlers receive (HRESULT, result); event handlers (sender, args).
COMPLETED = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, HRESULT, ctypes.c_void_p)
EVENT = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class Handler:
    """A minimal COM object implementing one WebView2 handler interface.

    WebView2 only calls Invoke and the IUnknown methods. Reference counting is
    left to Python: the dialog keeps every handler until it closes.
    """

    def __init__(self, prototype, callback) -> None:
        def invoke(_this, first, second):
            callback(first, second)
            return 0

        def query(this, _iid, result):
            result[0] = this
            return 0

        self._functions = (
            _QUERY(query),
            _REFCOUNT(lambda _this: 1),
            _REFCOUNT(lambda _this: 1),
            prototype(invoke),
        )
        self._vtable = (ctypes.c_void_p * 4)(
            *(ctypes.cast(function, ctypes.c_void_p).value for function in self._functions)
        )
        self._object = (ctypes.c_void_p * 1)(ctypes.addressof(self._vtable))

    @property
    def pointer(self) -> ctypes.c_void_p:
        return ctypes.c_void_p(ctypes.addressof(self._object))


def load_loader():
    """WebView2Loader.dll, from the bundle, next to the interpreter or on PATH."""
    folders = [getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
    for folder in filter(None, folders):
        candidate = Path(folder) / "WebView2Loader.dll"
        if candidate.is_file():
            return ctypes.WinDLL(str(candidate))
    return ctypes.WinDLL("WebView2Loader.dll")


class LoginWindow(Adw.Window):
    """Embedded Google login that extracts the resulting YouTube Music session."""

    def __init__(self, parent: Gtk.Window, data_dir: Path, on_success, on_manual):
        create = load_loader().CreateCoreWebView2EnvironmentWithOptions
        create.restype = HRESULT
        create.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p)
        if ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED) == RPC_E_CHANGED_MODE:
            raise WebView2Error(RPC_E_CHANGED_MODE, "o WebView2 exige uma thread STA")
        super().__init__(
            title=_("Conectar ao YouTube Music"),
            default_width=860,
            default_height=680,
            modal=True,
            transient_for=parent,
        )
        self._create_environment = create
        self.on_success = on_success
        self.on_manual = on_manual
        self.completing = False
        self.data_dir = data_dir / "webview2"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._handlers: list[Handler] = []
        self._objects: dict[str, Com] = {}

        toolbar = Adw.HeaderBar()
        back = Gtk.Button(icon_name="go-previous-symbolic", tooltip_text=_("Voltar"))
        back.connect("clicked", lambda *_: self._go_back())
        toolbar.pack_start(back)
        manual = Gtk.Button(label=_("Usar cookie manualmente"))
        manual.connect("clicked", lambda *_: (self.close(), on_manual()))
        toolbar.pack_end(manual)
        # Reserves the browser's place; the WebView2 child window covers it.
        self.host = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.host.connect("resize", lambda *_: GLib.idle_add(self._place))
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(toolbar)
        box.append(self.host)
        self.set_content(box)
        self.connect("map", lambda *_: GLib.idle_add(self._start))
        self.connect("close-request", self._close_request)

    def _handler(self, prototype, callback) -> ctypes.c_void_p:
        """Wrap a step; any failure in it falls back to the manual login."""

        def guarded(first, second):
            if self.completing:
                return
            try:
                callback(first, second)
            except Exception as exc:
                self._fail(exc)

        handler = Handler(prototype, guarded)
        self._handlers.append(handler)
        return handler.pointer

    def _keep(self, name: str, com: Com) -> Com:
        previous = self._objects.pop(name, None)
        if previous is not None:
            previous.release()
        self._objects[name] = com
        return com

    def _start(self) -> bool:
        try:
            hwnd = GdkWin32.Win32Surface.get_handle(self.get_surface())
            check(
                self._create_environment(
                    None,
                    str(self.data_dir),
                    None,
                    self._handler(
                        COMPLETED,
                        lambda result, environment: self._environment_ready(
                            result, environment, hwnd
                        ),
                    ),
                ),
                "CreateCoreWebView2EnvironmentWithOptions",
            )
        except Exception as exc:
            self._fail(exc)
        return GLib.SOURCE_REMOVE

    def _environment_ready(self, result: int, environment, hwnd: int) -> None:
        check(result, "ambiente do WebView2")
        environment = self._keep("environment", Com(environment).add_ref())
        environment.call(
            ENVIRONMENT_CREATE_CONTROLLER,
            (wintypes.HWND, ctypes.c_void_p),
            wintypes.HWND(hwnd),
            self._handler(COMPLETED, self._controller_ready),
            what="CreateCoreWebView2Controller",
        )

    def _controller_ready(self, result: int, controller) -> None:
        check(result, "controlador do WebView2")
        controller = self._keep("controller", Com(controller).add_ref())
        webview = self._keep("webview", controller.out_pointer(CONTROLLER_GET_WEBVIEW))
        settings = webview.out_pointer(WEBVIEW_GET_SETTINGS, "get_Settings")
        settings.call(SETTINGS_PUT_DEV_TOOLS, (wintypes.BOOL,), False)
        settings.call(SETTINGS_PUT_HOST_OBJECTS, (wintypes.BOOL,), False)
        settings.release()
        token = ctypes.c_int64()
        webview.call(
            WEBVIEW_ADD_NAVIGATION_COMPLETED,
            (ctypes.c_void_p, ctypes.POINTER(ctypes.c_int64)),
            self._handler(EVENT, self._navigation_completed),
            ctypes.byref(token),
            what="add_NavigationCompleted",
        )
        self._place()
        webview.call(WEBVIEW_NAVIGATE, (wintypes.LPCWSTR,), LOGIN_URL, what="Navigate")

    def _place(self) -> bool:
        """Cover the placeholder with the browser, in physical pixels."""
        controller = self._objects.get("controller")
        if controller is None or self.get_surface() is None:
            return GLib.SOURCE_REMOVE
        ok, origin = self.host.compute_point(self, Graphene.Point())
        if not ok:
            return GLib.SOURCE_REMOVE
        # The surface includes the client-side shadow around the window.
        offset_x, offset_y = self.get_native().get_surface_transform()
        scale = self.get_surface().get_scale()
        left = round((origin.x + offset_x) * scale)
        top = round((origin.y + offset_y) * scale)
        bounds = wintypes.RECT(
            left,
            top,
            left + round(self.host.get_width() * scale),
            top + round(self.host.get_height() * scale),
        )
        try:
            controller.call(CONTROLLER_PUT_BOUNDS, (wintypes.RECT,), bounds, what="put_Bounds")
        except OSError as exc:
            self._fail(exc)
        return GLib.SOURCE_REMOVE

    def _go_back(self) -> None:
        webview = self._objects.get("webview")
        can_go_back = wintypes.BOOL()
        if webview is not None:
            webview.call(
                WEBVIEW_GET_CAN_GO_BACK, (ctypes.POINTER(wintypes.BOOL),), ctypes.byref(can_go_back)
            )
        if can_go_back.value:
            webview.call(WEBVIEW_GO_BACK, ())
        else:
            self.close()

    def _navigation_completed(self, _sender, _args) -> None:
        webview = self._objects["webview"]
        if not webview.out_string(WEBVIEW_GET_SOURCE, "get_Source").startswith(MUSIC_ORIGIN):
            return
        webview2 = webview.query(IID_ICOREWEBVIEW2_2)
        try:
            manager = self._keep(
                "cookies", webview2.out_pointer(WEBVIEW2_GET_COOKIE_MANAGER, "get_CookieManager")
            )
        finally:
            webview2.release()
        manager.call(
            COOKIES_GET,
            (wintypes.LPCWSTR, ctypes.c_void_p),
            MUSIC_ORIGIN,
            self._handler(COMPLETED, self._cookies_ready),
            what="GetCookies",
        )

    def _cookies_ready(self, result: int, cookies) -> None:
        check(result, "GetCookies")
        cookie_list = Com(cookies)  # borrowed for the duration of the callback
        count = ctypes.c_uint32()
        cookie_list.call(COOKIE_LIST_COUNT, (ctypes.POINTER(ctypes.c_uint32),), ctypes.byref(count))
        pairs = []
        for index in range(count.value):
            pointer = ctypes.c_void_p()
            cookie_list.call(
                COOKIE_LIST_AT,
                (ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)),
                index,
                ctypes.byref(pointer),
            )
            cookie = Com(pointer.value)
            try:
                pairs.append(
                    (cookie.out_string(COOKIE_GET_NAME), cookie.out_string(COOKIE_GET_VALUE))
                )
            finally:
                cookie.release()
        raw = session_cookie_header(pairs)
        if raw is None:
            return  # still signing in: wait for the next navigation
        self.completing = True
        GLib.idle_add(self._finish, raw)

    def _finish(self, raw: str) -> bool:
        self.on_success(raw)
        self.close()
        return GLib.SOURCE_REMOVE

    def _fail(self, error: Exception) -> None:
        LOGGER.warning("O login pelo WebView2 falhou: %s", error)
        if self.completing:
            return
        self.completing = True

        def fallback() -> bool:
            self.close()
            self.on_manual()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(fallback)

    def _close_request(self, *_args) -> bool:
        self.completing = True
        controller = self._objects.get("controller")
        if controller is not None:
            try:
                controller.call(CONTROLLER_CLOSE, (), what="Close")
            except OSError:
                LOGGER.debug("O WebView2 já estava fechado", exc_info=True)
        for name in ("cookies", "webview", "controller", "environment"):
            com = self._objects.pop(name, None)
            if com is not None:
                com.release()
        return False
