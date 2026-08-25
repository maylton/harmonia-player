from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "src" / "harmonia" / "qml"


def test_qt_backend_reuses_shared_account_profile_and_cache_keys() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_backend.py").read_text(encoding="utf-8")
    assert "self.youtube.account_profile()" in source
    assert 'get_setting("account_avatar_url", "")' in source
    assert 'set_setting("account_avatar_url", avatar_url)' in source
    assert "def accountAvatarUrl" in source
    assert "def accountName" in source
    assert "_refresh_account_profile()" in source


def test_qt_top_bar_renders_real_avatar_with_symbolic_fallback() -> None:
    source = (QML / "AppTopBar.qml").read_text(encoding="utf-8")
    assert "source: backend.loggedIn ? backend.accountAvatarUrl : \"\"" in source
    assert 'kind: "artist"' in source
    assert 'source: backend.loggedIn ? "user-available" : "user-offline"' in source
    assert "visible: !backend.loggedIn || backend.accountAvatarUrl.length === 0" in source


def test_sidebar_brand_uses_installed_harmonia_icon() -> None:
    source = (QML / "NavigationSidebar.qml").read_text(encoding="utf-8")
    assert 'source: "io.github.harmonia.Harmonia"' in source
    assert "isMask: false" in source
    assert 'source: "audio-headphones"' not in source
