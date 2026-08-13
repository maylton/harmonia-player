import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from tools.sync_icons import ICONS, THEMES

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.harmonia.Harmonia"


def test_every_icon_referenced_by_python_has_bundled_variants():
    used = set()
    for source in (ROOT / "src" / "harmonia").glob("*.py"):
        used.update(re.findall(r'"([a-z0-9][a-z0-9-]*-symbolic)"', source.read_text()))

    assert used <= ICONS.keys()


def test_bundled_icon_packs_are_valid_and_record_provenance():
    assert set(THEMES) == {"HarmoniaMaterial"}
    for theme, (prefix, mapping_index, _upstream, _license) in THEMES.items():
        directory = ROOT / "src" / "harmonia" / "icons" / theme / "scalable" / "actions"
        for semantic_name, upstream_names in ICONS.items():
            path = directory / f"{semantic_name}.svg"
            ET.parse(path)
            assert f"Source: Iconify {prefix}:{upstream_names[mapping_index]}" in path.read_text()


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
