from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "harmonia"

QT_MODULES = (
    "qt_backend.py",
    "qt_catalog.py",
    "qt_library.py",
    "qt_playback.py",
    "qt_integrated_playback.py",
    "qt_activity.py",
    "qt_preferences.py",
    "qt_integrations.py",
    "qt_mutations.py",
    "qt_presenters.py",
)

SHARED_MODULES = (
    "models.py",
    "services.py",
    "storage.py",
    "preferences.py",
    "downloads.py",
    "lyrics.py",
    "lyrics_state.py",
    "playback_state.py",
    "auth_state.py",
    "backup.py",
    "insights.py",
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_qt_controllers_do_not_depend_on_gtk_or_adwaita() -> None:
    for filename in QT_MODULES:
        source = _source(PACKAGE / filename)
        assert 'gi.require_version("Gtk"' not in source, filename
        assert "from gi.repository import Adw" not in source, filename
        assert "from gi.repository import Gtk" not in source, filename


def test_gtk_presentation_does_not_depend_on_pyside_or_qt_controllers() -> None:
    paths = [PACKAGE / "app.py", *sorted(PACKAGE.glob("window_*.py"))]
    for path in paths:
        source = _source(path)
        assert "PySide6" not in source, path.name
        assert "from .qt_" not in source, path.name
        assert "import harmonia.qt_" not in source, path.name


def test_shared_domain_modules_remain_toolkit_free() -> None:
    forbidden = (
        "PySide6",
        'gi.require_version("Gtk"',
        "from gi.repository import Adw",
        "from gi.repository import Gtk",
    )
    for filename in SHARED_MODULES:
        source = _source(PACKAGE / filename)
        for token in forbidden:
            assert token not in source, f"{filename}: {token}"


def test_qt_backend_stays_a_facade_instead_of_absorbing_domain_implementations() -> None:
    source = _source(PACKAGE / "qt_backend.py")
    for controller in (
        "QtCatalogController",
        "QtLibraryController",
        "QtPlaybackController",
        "QtHistoryController",
        "QtLyricsController",
        "QtPreferencesController",
        "QtMutationController",
    ):
        assert controller in source

    assert "from .player import NativePlayer" not in source
    assert "from .lyrics import LyricsResolver" not in source
    assert "from .backup import BackupManager" not in source
    assert len(source.splitlines()) <= 1300


def test_both_frontends_use_shared_playback_state_rules() -> None:
    helpers = (
        "shuffled_queue_keep_current",
        "move_queue_item",
        "remove_queue_item",
        "filter_new_recommendations",
        "radio_seed_for_autoplay",
        "playback_state_snapshot",
    )
    for filename in ("qt_playback.py", "window_playback.py"):
        source = _source(PACKAGE / filename)
        assert "from .playback_state import (" in source
        for helper in helpers:
            assert helper in source, f"{filename}: {helper}"
        assert "playback_state_snapshot(" in source, filename
        assert "PlaybackState(" not in source, filename
