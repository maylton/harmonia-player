import inspect
import warnings
from pathlib import Path

import pytest

from harmonia import app, window_preferences
from harmonia.host import slash_path
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


def test_gtk_frontend_starts_with_the_dark_default_theme():
    from harmonia.theming import DEFAULT_THEME, get_theme

    startup = inspect.getsource(app.HarmoniaApplication.do_startup)
    assert "GtkThemeController(" in startup
    assert "apply(DEFAULT_THEME)" in startup
    assert get_theme(DEFAULT_THEME).default_variant == "dark"


def test_gtk_theming_changes_stay_out_of_the_qt_frontend():
    qt_files = [*SOURCE.glob("qt_*.py"), *(SOURCE / "qml").glob("*.qml")]
    assert qt_files
    qt_sources = [path.read_text(encoding="utf-8") for path in qt_files]
    for text in qt_sources:
        assert "style.css" not in text
        assert "gtk_theme" not in text


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


def test_gtk_theme_is_dropped_unless_explicitly_kept():
    from harmonia.frontend import ignore_foreign_gtk_theme

    environ = {"GTK_THEME": "Adwaita:dark"}
    assert ignore_foreign_gtk_theme(environ) == "Adwaita:dark"
    assert "GTK_THEME" not in environ

    kept = {"GTK_THEME": "Adwaita:dark", "HARMONIA_KEEP_GTK_THEME": "1"}
    assert ignore_foreign_gtk_theme(kept) is None
    assert kept["GTK_THEME"] == "Adwaita:dark"
    assert ignore_foreign_gtk_theme({}) is None


def test_gtk_theme_is_dropped_before_gtk_is_imported_and_only_for_gtk():
    from harmonia import frontend

    source = inspect.getsource(frontend.main)
    qt_branch = source.index("qt_main()")
    dropped = source.index("ignore_foreign_gtk_theme()")
    imported = source.index('import_module(".app"')
    assert qt_branch < dropped < imported


def test_elementary_shadow_ships_only_fixed_used_icons_and_no_theme_index():
    import re
    import xml.etree.ElementTree as ET

    root = SOURCE / "icons-compat" / "elementary"
    # Without an index.theme the tree never becomes a theme of its own: GTK
    # merges it into the installed elementary theme and its variants.
    assert not list((SOURCE / "icons-compat").rglob("index.theme"))
    used = set()
    for source in SOURCE.glob("*.py"):
        used.update(re.findall(r'"([a-z0-9][a-z0-9-]*-symbolic)"', source.read_text()))
    icons = sorted(root.rglob("*.svg"))
    assert icons
    for path in icons:
        text = path.read_text(encoding="utf-8")
        assert path.stem in used
        assert "Source: elementary/icons" in text
        assert not any(element.get("transform") for element in ET.fromstring(text).iter())
    # HiDPI: elementary lists <context>@2x and @3x directories, mirror them all.
    for path in icons:
        context, *rest = path.relative_to(root).parts
        if "@" not in context:
            for scale in (2, 3):
                assert root.joinpath(f"{context}@{scale}x", *rest).is_file(), (path, scale)


def _fake_elementary(tmp_path):
    host = tmp_path / "host"
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><path d="M0 0h16v16H0z"/></svg>'
    (host / "elementary" / "actions" / "symbolic").mkdir(parents=True)
    (host / "elementary" / "index.theme").write_text(
        "[Icon Theme]\nName=elementary\nInherits=hicolor\nDirectories=actions/symbolic\n\n"
        "[actions/symbolic]\nSize=16\nMinSize=8\nMaxSize=512\nType=Scalable\n"
    )
    for name in ("go-home-symbolic", "find-location-symbolic"):
        (host / "elementary" / "actions" / "symbolic" / f"{name}.svg").write_text(svg)
    (host / "elementary-grape" / "places" / "48").mkdir(parents=True)
    (host / "elementary-grape" / "index.theme").write_text(
        "[Icon Theme]\nName=elementary Grape\nInherits=elementary\nDirectories=places/48\n\n"
        "[places/48]\nSize=48\nType=Fixed\n"
    )
    return host


def test_elementary_shadow_reaches_accent_variants_on_new_gtk(tmp_path):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from harmonia.window_preferences import ELEMENTARY_SHADOW_PATH, install_elementary_shadow

    host = _fake_elementary(tmp_path)
    theme = Gtk.IconTheme()
    theme.set_search_path([str(host)])
    theme.set_theme_name("elementary-grape")  # an elementary-accent-folders variant

    def resolved(name):
        icon = theme.lookup_icon(name, None, 16, 1, Gtk.TextDirection.LTR, Gtk.IconLookupFlags(0))
        return slash_path(icon.get_file().get_path())

    assert install_elementary_shadow(theme, (4, 20)) is False
    assert theme.get_search_path() == [str(host)]
    assert install_elementary_shadow(theme, (4, 22)) is True
    assert resolved("go-home-symbolic").startswith(slash_path(ELEMENTARY_SHADOW_PATH))
    assert resolved("find-location-symbolic").startswith(slash_path(str(host)))  # untouched
    install_elementary_shadow(theme, (4, 22))  # idempotent
    assert theme.get_search_path().count(ELEMENTARY_SHADOW_PATH) == 1


def test_elementary_shadow_moves_first_when_gtk_prefers_earlier_paths():
    from harmonia.window_preferences import ELEMENTARY_SHADOW_PATH, install_elementary_shadow

    class File:
        def __init__(self, path):
            self.path = path

        def get_path(self):
            return self.path

    class Icon:
        def __init__(self, path):
            self.path = path

        def get_file(self):
            return File(self.path)

    class FirstWinsTheme:
        """Simulates a GTK where the earliest search path wins for equal matches."""

        def __init__(self):
            self.paths = ["/run/host/share/icons"]

        def get_search_path(self):
            return list(self.paths)

        def set_search_path(self, paths):
            self.paths = list(paths)

        def lookup_icon(self, *_args):
            return Icon(f"{self.paths[0]}/elementary/actions/symbolic/go-home-symbolic.svg")

    theme = FirstWinsTheme()
    install_elementary_shadow(theme, (4, 22))
    assert theme.paths == [ELEMENTARY_SHADOW_PATH, "/run/host/share/icons"]


def test_navigation_icons_ignore_icon_theme_status_colours():
    # elementary's starred-symbolic is a "warning" star that GTK paints yellow;
    # in the sidebar and compact menu it must match the other icons.
    css = (Path(__file__).resolve().parents[1] / "src" / "harmonia" / "style.css").read_text()
    rule = css.split(".sidebar-item image, .compact-menu image, .item-menu-list image {", 1)[1]
    rule = rule.split("}", 1)[0]
    for status in ("success", "warning", "error"):
        assert f"{status} currentColor" in rule
