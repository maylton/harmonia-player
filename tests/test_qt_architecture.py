from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "src" / "harmonia" / "qml"


def test_qt_app_uses_modular_backend() -> None:
    source = (ROOT / "src" / "harmonia" / "qt_app.py").read_text(encoding="utf-8")
    assert "from .qt_backend import HarmoniaQtBackend" in source
    assert "from .qt_bridge import" not in source


def test_main_qml_keeps_major_regions_componentized() -> None:
    source = (QML / "Main.qml").read_text(encoding="utf-8")
    assert "NavigationSidebar {" in source
    assert "AppTopBar {" in source
    assert "SearchPage {" in source
    assert "id: searchList" not in source


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
