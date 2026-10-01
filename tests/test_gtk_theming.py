import inspect
import warnings
from pathlib import Path

from harmonia import app, window_preferences
from harmonia.storage import Storage
from harmonia.window_preferences import (
    BUNDLED_ICON_THEME,
    WindowPreferencesMixin,
    icon_theme_installed,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "harmonia"


class IconThemeStub:
    def __init__(self, search_path):
        self._search_path = [str(path) for path in search_path]

    def get_search_path(self):
        return self._search_path


def _make_theme(base: Path, name: str) -> None:
    (base / name).mkdir(parents=True)
    (base / name / "index.theme").write_text("[Icon Theme]\nName=x\n", encoding="utf-8")


def test_icon_theme_detection_requires_an_index_in_the_search_path(tmp_path):
    _make_theme(tmp_path / "system", "Adwaita")
    (tmp_path / "system" / "elementary").mkdir()  # directory without index.theme
    theme = IconThemeStub([tmp_path / "missing", tmp_path / "system"])

    assert icon_theme_installed(theme, "Adwaita")
    assert not icon_theme_installed(theme, "elementary")
    assert not icon_theme_installed(theme, "")


def test_bundled_icon_pack_is_a_loadable_theme():
    theme = IconThemeStub([SOURCE / "icons"])
    assert icon_theme_installed(theme, BUNDLED_ICON_THEME)
    index = (SOURCE / "icons" / BUNDLED_ICON_THEME / "index.theme").read_text(encoding="utf-8")
    declared = index.split("Directories=", 1)[1].splitlines()[0].split(",")
    for directory in declared:
        assert (SOURCE / "icons" / BUNDLED_ICON_THEME / directory).is_dir()


def test_gtk_icon_mode_follows_the_system_instead_of_pinning_it():
    source = inspect.getsource(WindowPreferencesMixin._apply_icon_theme)
    assert 'reset_property("gtk-icon-theme-name")' in source
    assert "_system_icon_theme_name" not in inspect.getsource(app)


def test_icon_refresh_no_longer_tracks_every_image():
    # The old per-image tracking kept references to destroyed widgets and
    # connected a new handler on each page change.
    for module in (app, window_preferences):
        text = inspect.getsource(module)
        assert "_icon_sources" not in text
        assert "_refresh_custom_icons" not in text


def test_gtk_frontend_declares_the_dark_palette_used_by_its_stylesheet():
    startup = inspect.getsource(app.HarmoniaApplication.do_startup)
    assert "Adw.ColorScheme.FORCE_DARK" in startup
    css = (SOURCE / "style.css").read_text(encoding="utf-8")
    assert css.startswith("window { background: #242424;")


def test_gtk_theming_changes_stay_out_of_the_qt_frontend():
    qt_files = [*SOURCE.glob("qt_*.py"), *(SOURCE / "qml").glob("*.qml")]
    assert qt_files
    qt_sources = [path.read_text(encoding="utf-8") for path in qt_files]
    for text in qt_sources:
        assert "style.css" not in text
        assert "FORCE_DARK" not in text


def test_sidebar_navigation_scrolls_instead_of_forcing_window_height():
    source = inspect.getsource(app.HarmoniaWindow._build_sidebar)
    assert "Gtk.ScrolledWindow(" in source
    assert "self.sidebar.append(nav_scroll)" in source
    assert "max-width: 800px" not in inspect.getsource(app.HarmoniaWindow.__init__)


def test_storage_closes_sqlite_connections(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    storage = Storage()
    with storage._connect() as db:
        db.execute("SELECT 1")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            db.execute("SELECT 1")
        except Exception as exc:
            assert "closed" in str(exc).lower()
        else:
            raise AssertionError("a conexão SQLite deveria estar fechada")
