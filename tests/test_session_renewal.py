"""A refused session is read again from the sign-in browser's profile, once, on Windows."""

import types

import pytest

pytest.importorskip("gi")
from harmonia import window_account
from harmonia.window_account import WindowAccountMixin


class Login:
    renewed: list = []
    outcome = "cookie-novo"

    def __init__(self, _parent, _data_dir, on_success, on_failure):
        self.on_success, self.on_failure = on_success, on_failure

    def renew_silently(self):
        Login.renewed.append(1)
        if Login.outcome:
            self.on_success(Login.outcome)
        else:
            self.on_failure()


class Window(WindowAccountMixin):
    def __init__(self):
        self.saved, self.synced, self.toasts, self.done = [], [], [], []
        self.storage = types.SimpleNamespace(web_data_dir="/profile", save_cookie=self.saved.append)
        self.toast_overlay = types.SimpleNamespace(add_toast=self.toasts.append)

    def sync(self):
        self.synced.append("library")

    def sync_home(self):
        self.synced.append("home")

    def sync_explore(self):
        self.synced.append("explore")

    def finished(self, data, error):
        self.done.append(error)


@pytest.fixture
def windows_login(monkeypatch):
    monkeypatch.setattr(window_account.host, "LOGIN_MODULE", "auth_webview2")
    monkeypatch.setattr(window_account.host, "INTEGRATED_LOGIN", True)
    module = types.SimpleNamespace(LoginWindow=Login)
    real = window_account.importlib.import_module
    monkeypatch.setattr(
        window_account.importlib,
        "import_module",
        lambda name, *args: module if name == ".auth_webview2" else real(name, *args),
    )
    Login.renewed, Login.outcome = [], "cookie-novo"


def test_a_refused_session_is_renewed_and_the_syncs_run_again(windows_login):
    window = Window()
    window._session_expired(window.finished, "expirou")
    assert window.saved == ["cookie-novo"]
    assert window.synced == ["library", "home", "explore"]
    assert not window.done and not window.toasts  # nothing to tell the user

    # Refused again in the same session: the error shows, no renewal loop.
    window._session_expired(window.finished, "expirou")
    assert Login.renewed == [1] and window.done == ["expirou"]


def test_without_a_session_in_the_profile_the_user_is_asked_to_sign_in(windows_login):
    Login.outcome = None
    window = Window()
    window._session_expired(window.finished, "expirou")
    assert window.done == ["expirou"] and not window.saved
    assert len(window.toasts) == 1


def test_linux_shows_the_error_as_before(monkeypatch):
    monkeypatch.setattr(window_account.host, "LOGIN_MODULE", "auth")
    window = Window()
    window._session_expired(window.finished, "expirou")
    assert window.done == ["expirou"] and not window.saved
