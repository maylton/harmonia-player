from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "src" / "harmonia" / "qml"


def test_qt_app_uses_modular_backend() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_app.py").read_text(encoding="utf-8")
    assert "from .qt_backend import HarmoniaQtBackend" in source
    assert "from .qt_bridge import" not in source
    assert not (ROOT / "src" / "harmonia" / "qt_bridge.py").exists()


def test_qt_app_resolves_installed_application_icon() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_app.py").read_text(encoding="utf-8")
    assert "def _application_icon()" in source
    assert 'Path("/app/share")' in source
    assert "QIcon.setThemeSearchPaths" in source


def test_main_qml_keeps_major_regions_componentized() -> None:
    source = (QML / "Main.qml").read_text(encoding="utf-8")
    assert "NavigationSidebar {" in source
    assert "AppTopBar {" in source
    assert "SearchPage {" in source
    assert "id: searchList" not in source


def test_media_popups_use_the_window_overlay() -> None:
    source = (QML / "Main.qml").read_text(encoding="utf-8")
    assert source.count("parent: Controls.Overlay.overlay") >= 3


def test_repeated_artwork_uses_cover_art_helper() -> None:
    consumers = (
        "DetailPage.qml",
        "DownloadsPage.qml",
        "HistoryPage.qml",
        "InsightsPage.qml",
        "LibraryPage.qml",
        "MediaShelf.qml",
        "PlayerBar.qml",
        "QueuePanel.qml",
        "SearchPage.qml",
        "SongShelf.qml",
    )
    for filename in consumers:
        source = (QML / filename).read_text(encoding="utf-8")
        assert "CoverArt {" in source, filename


def test_cover_art_is_the_only_shared_artwork_loader() -> None:
    for filename in (
        "DownloadsPage.qml",
        "HistoryPage.qml",
        "InsightsPage.qml",
        "LibraryPage.qml",
        "MediaShelf.qml",
        "PlayerBar.qml",
        "QueuePanel.qml",
        "SearchPage.qml",
        "SongShelf.qml",
    ):
        source = (QML / filename).read_text(encoding="utf-8")
        assert "Image {" not in source, filename


def test_loaded_cover_art_uses_a_real_qt_quick_mask() -> None:
    source = (QML / "CoverArt.qml").read_text(encoding="utf-8")
    assert "import QtQuick.Effects" in source
    assert "maskEnabled: true" in source
    assert "maskSource: artworkMask" in source
    assert 'kind === "artist"' in source


def test_visible_player_controls_do_not_use_missing_autoplay_icon() -> None:
    for filename in ("PlayerBar.qml", "ExpandedPlayer.qml"):
        source = (QML / filename).read_text(encoding="utf-8")
        assert "media-playlist-consecutive" not in source, filename
