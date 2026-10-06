import ctypes

import pytest

from harmonia import host
from harmonia.login import LOGIN_URL, MUSIC_ORIGIN, session_cookie_header


def test_session_header_waits_for_the_sapisid_cookie():
    assert session_cookie_header([("VISITOR_INFO1_LIVE", "x"), ("YSC", "y")]) is None
    assert session_cookie_header([("YSC", "y"), ("SAPISID", "abc")]) == "YSC=y; SAPISID=abc"
    assert session_cookie_header([("__Secure-3PAPISID", "abc")]) == "__Secure-3PAPISID=abc"
    assert LOGIN_URL.startswith("https://accounts.google.com/")
    assert "music.youtube.com" in LOGIN_URL and MUSIC_ORIGIN == "https://music.youtube.com"


def test_each_platform_names_its_login_browser():
    assert host.LOGIN_MODULE in {"auth", "auth_webview2", ""}
    assert bool(host.LOGIN_MODULE) == host.INTEGRATED_LOGIN
    if host.IS_LINUX:
        assert host.LOGIN_MODULE == "auth"
    if host.IS_WINDOWS:
        assert host.LOGIN_MODULE == "auth_webview2"


@pytest.mark.skipif(not host.IS_WINDOWS, reason="usa WINFUNCTYPE e o WebView2 do Windows")
def test_webview2_handlers_are_callable_through_their_vtable():
    from harmonia import auth_webview2

    received = []
    handler = auth_webview2.Handler(
        auth_webview2.COMPLETED, lambda result, value: received.append((result, value))
    )
    com = auth_webview2.Com(handler.pointer.value)
    com.call(3, (auth_webview2.HRESULT, ctypes.c_void_p), -5, ctypes.c_void_p(42))
    assert received == [(-5, 42)]

    # QueryInterface hands back the object itself; AddRef/Release are no-ops.
    same = com.query(auth_webview2.IID_ICOREWEBVIEW2_2)
    assert same.pointer.value == handler.pointer.value
    com.add_ref()
    same.release()


@pytest.mark.skipif(not host.IS_WINDOWS, reason="usa o WebView2 do Windows")
def test_webview2_failures_become_os_errors():
    from harmonia.auth_webview2 import WebView2Error, check

    check(0, "ok")
    with pytest.raises(WebView2Error) as raised:
        check(-2147024894, "CreateCoreWebView2EnvironmentWithOptions")  # 0x80070002
    assert "0x80070002" in str(raised.value)
    assert isinstance(raised.value, OSError)
