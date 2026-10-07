import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.sync_icons import (
    FALLBACK_THEME,
    ICONS,
    THEME_EXTRAS,
    THEMES,
    UNTHEMED_FALLBACKS,
    theme_icons,
)

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.harmonia.Harmonia"


def test_every_icon_referenced_by_python_has_bundled_variants():
    used = set()
    for source in (ROOT / "src" / "harmonia").rglob("*.py"):
        used.update(re.findall(r'"([a-z0-9][a-z0-9-]*-symbolic)"', source.read_text()))

    assert used <= ICONS.keys()


def test_icons_recent_adwaita_dropped_have_unthemed_fallbacks():
    root = ROOT / "src" / "harmonia" / "icons"
    assert {path.stem for path in root.glob("*.svg")} == set(UNTHEMED_FALLBACKS)
    source = root / FALLBACK_THEME / "scalable" / "actions"
    for name in UNTHEMED_FALLBACKS:
        assert (root / f"{name}.svg").read_bytes() == (source / f"{name}.svg").read_bytes()


def test_bundled_icon_packs_are_valid_and_record_provenance():
    assert set(THEMES) == {"HarmoniaMaterial", "HarmoniaFluent"}
    for theme, (prefix, _mapping_index, _upstream, _license) in THEMES.items():
        folder = ROOT / "src" / "harmonia" / "icons" / theme
        assert (folder / "index.theme").is_file()
        directory = folder / "scalable" / "actions"
        icons = theme_icons(theme)
        assert {path.stem for path in directory.glob("*.svg")} == set(icons)
        for semantic_name, upstream_name in icons.items():
            path = directory / f"{semantic_name}.svg"
            ET.parse(path)
            assert f"Source: Iconify {prefix}:{upstream_name}" in path.read_text(encoding="utf-8")


def test_fluent_icons_also_replace_the_windows_caption_buttons():
    extras = THEME_EXTRAS["HarmoniaFluent"]
    assert set(extras) == {
        "window-minimize-symbolic",
        "window-maximize-symbolic",
        "window-restore-symbolic",
    }
    # Material keeps GTK's caption buttons, so nothing changes for it.
    assert "HarmoniaMaterial" not in THEME_EXTRAS
    assert all(len(names) == 3 for names in ICONS.values())


def test_windows_uses_the_bundled_fluent_icons_as_its_system_theme():
    from harmonia import host

    assert host.SYSTEM_ICON_THEME in {"", "HarmoniaFluent"}
    assert ("HarmoniaFluent" if host.IS_WINDOWS else "") == host.SYSTEM_ICON_THEME
    assert not host.SYSTEM_ICON_THEME or host.SYSTEM_ICON_THEME in THEMES


def test_launcher_icon_has_standard_hicolor_sizes_and_transparency():
    expected_sizes = {16, 32, 48, 64, 128, 256, 512, 1024}
    icons = ROOT / "data" / "icons" / "hicolor"

    for size in expected_sizes:
        path = icons / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
        data = path.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", data[16:24]) == (size, size)
        color_type = data[25]
        assert color_type in (4, 6) or (color_type == 3 and b"tRNS" in data)

    desktop_entry = (ROOT / "data" / f"{APP_ID}.desktop").read_text()
    assert "Exec=@BINDIR@/harmonia\n" in desktop_entry
    assert f"Icon={APP_ID}\n" in desktop_entry
    assert f"StartupWMClass={APP_ID}\n" in desktop_entry


def test_elementary_shadow_detects_hidden_guide_layers():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from sync_elementary_icons import misdrawn_by_gtk, without_hidden

    guide = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
        '<path d="M 2 2 L 14 14" style="fill:#555761"/>'
        '<g style="display:none"><rect x="0" y="0" width="16" height="16"/></g></svg>'
    )
    assert misdrawn_by_gtk(guide)  # GTK draws the hidden rect: a solid square
    cleaned = without_hidden(guide)
    assert "rect" not in cleaned and "M 2 2" in cleaned
    assert not misdrawn_by_gtk(cleaned)
