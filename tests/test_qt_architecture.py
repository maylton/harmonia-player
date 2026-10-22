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


def test_qt_app_exposes_shared_preferences_controller() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_app.py").read_text(encoding="utf-8")
    assert 'setContextProperty("preferences", backend.settings)' in source


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


def test_loaded_cover_art_uses_curve_renderer_for_native_antialiasing() -> None:
    source = (QML / "CoverArt.qml").read_text(encoding="utf-8")
    assert "import QtQuick.Shapes" in source
    assert 'import "Artwork.js" as Artwork' in source
    assert "preferredRendererType: Shape.CurveRenderer" in source
    assert "fillItem: artwork" in source
    assert source.count("PathArc {") == 4
    assert "layer.effect: MultiEffect" not in source
    assert "maskThresholdMin" not in source
    assert "layer.textureSize" not in source
    assert "mipmap: true" in source
    assert 'kind === "artist"' in source


def test_curve_cover_fill_preserves_image_crop_via_layered_texture() -> None:
    source = (QML / "CoverArt.qml").read_text(encoding="utf-8")
    assert "fillMode: Image.PreserveAspectCrop" in source
    assert "layer.enabled: true" in source
    assert "layer.smooth: true" in source
    assert "layer.mipmap: true" in source
    assert "fillItem: artwork" in source


def test_qt_app_does_not_force_global_msaa_for_curve_covers() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_app.py").read_text(encoding="utf-8")
    assert "QSurfaceFormat" not in source
    assert "setSamples(" not in source


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


def test_no_artwork_is_blurred_behind_the_interface() -> None:
    # The blurred-artwork backdrops are gone from both frontends: the window
    # shows the theme, and on Linux the compositor's blur through Mica.
    assert not (QML / "AmbientBackdrop.qml").exists()
    for page in ("Main.qml", "DetailPage.qml", "ExpandedPlayer.qml", "SettingsPage.qml"):
        source = (QML / page).read_text(encoding="utf-8")
        assert "AmbientBackdrop" not in source and "backgroundBlur" not in source, page


def test_sidebar_uses_one_theme_aware_icon_component() -> None:
    sidebar = (QML / "NavigationSidebar.qml").read_text(encoding="utf-8")
    button = (QML / "SidebarButton.qml").read_text(encoding="utf-8")
    assert sidebar.count("SidebarButton {") >= 10
    assert 'iconName: "applications-multimedia"' not in sidebar
    assert "property bool monochromeIcon: false" in button
    assert "isMask: root.monochromeIcon" in button
    assert "fallback:" in button
    assert sidebar.count("monochromeIcon: true") == 1
    assert sidebar.count("iconSize:") == 0


def test_visible_player_controls_do_not_use_missing_autoplay_icon() -> None:
    for filename in ("PlayerBar.qml", "ExpandedPlayer.qml", "QueuePanel.qml"):
        source = (QML / filename).read_text(encoding="utf-8")
        assert "media-playlist-consecutive" not in source, filename


def test_qt_video_uses_shared_dash_source_with_client_headers() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_video.py").read_text(encoding="utf-8")
    assert "allow_video_only=True" in source
    assert "self._start_video_layer(stream)" in source
    assert "stream.url" in source
    assert "stream.request_headers" in source
    assert "self.playback.player._source_uri(" in source
    # The settle tolerance is the shared video_sync policy, as in GTK.
    assert "video_sync.is_settled(drift_ms * 1000)" in source
    assert "self._complete_video_start(generation)" in source
