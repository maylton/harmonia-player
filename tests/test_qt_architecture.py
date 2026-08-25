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


def test_qt_app_requests_multisampling_without_touching_cover_mask() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_app.py").read_text(encoding="utf-8")
    assert "QSurfaceFormat" in source
    assert "surface_format.setSamples(4)" in source
    assert "QSurfaceFormat.setDefaultFormat(surface_format)" in source


def test_qt_app_exposes_shared_preferences_controller() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_app.py").read_text(encoding="utf-8")
    assert 'setContextProperty("preferences", backend.settings)' in source
    preferences = (ROOT / "src" / "harmonia" / "qt_preferences.py").read_text(encoding="utf-8")
    assert "def backgroundBlur" in preferences
    assert "self.values.background_blur" in preferences
    assert "def setBackgroundBlur" in preferences


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


def test_loaded_cover_art_keeps_the_known_good_mask_pipeline() -> None:
    source = (QML / "CoverArt.qml").read_text(encoding="utf-8")
    assert "import QtQuick.Effects" in source
    assert 'import "Artwork.js" as Artwork' in source
    assert "layer.effect: MultiEffect" in source
    assert "maskEnabled: true" in source
    assert "maskSource: artworkMask" in source
    assert "maskThresholdMin: 0.5" in source
    assert "maskSpreadAtMin: 0.0" in source
    assert "layer.samples:" not in source
    assert "mipmap: true" in source
    assert "layer.smooth: true" in source
    assert 'kind === "artist"' in source


def test_home_cover_hover_is_explicitly_above_layered_artwork() -> None:
    media = (QML / "MediaShelf.qml").read_text(encoding="utf-8")
    songs = (QML / "SongShelf.qml").read_text(encoding="utf-8")
    assert "background: null" in media
    assert "z: 0" in media
    assert "z: 1" in media
    assert "z: 2" in media
    assert "antialiasing: true" in media
    assert "z: 0" in songs
    assert "z: 1" in songs
    assert "z: 2" in songs


def test_ambient_backdrops_share_one_component_and_setting() -> None:
    backdrop = (QML / "AmbientBackdrop.qml").read_text(encoding="utf-8")
    assert "MultiEffect {" in backdrop
    assert 'import "Artwork.js" as Artwork' in backdrop
    assert "blurEnabled: true" in backdrop

    main = (QML / "Main.qml").read_text(encoding="utf-8")
    detail = (QML / "DetailPage.qml").read_text(encoding="utf-8")
    expanded = (QML / "ExpandedPlayer.qml").read_text(encoding="utf-8")
    settings = (QML / "SettingsPage.qml").read_text(encoding="utf-8")

    assert "AmbientBackdrop {" in main
    assert "active: preferences.backgroundBlur" in main
    assert "AmbientBackdrop {" in detail
    assert "preferences.backgroundBlur" in detail
    assert "AmbientBackdrop {" in expanded
    assert "preferences.backgroundBlur" in expanded
    assert "checked: preferences.backgroundBlur" in settings
    assert "preferences.setBackgroundBlur(checked)" in settings


def test_sidebar_uses_one_masked_icon_component() -> None:
    sidebar = (QML / "NavigationSidebar.qml").read_text(encoding="utf-8")
    button = (QML / "SidebarButton.qml").read_text(encoding="utf-8")
    assert sidebar.count("SidebarButton {") >= 10
    assert 'iconName: "applications-multimedia"' not in sidebar
    assert "isMask: true" in button
    assert "fallback:" in button


def test_visible_player_controls_do_not_use_missing_autoplay_icon() -> None:
    for filename in ("PlayerBar.qml", "ExpandedPlayer.qml", "QueuePanel.qml"):
        source = (QML / filename).read_text(encoding="utf-8")
        assert "media-playlist-consecutive" not in source, filename
