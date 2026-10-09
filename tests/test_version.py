import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_place_that_states_the_version_agrees():
    from harmonia import __version__

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    meson = re.search(
        r"project\('harmonia', version: '([^']+)'",
        (ROOT / "meson.build").read_text(encoding="utf-8"),
    ).group(1)
    metainfo = ET.parse(ROOT / "data" / "io.github.harmonia.Harmonia.metainfo.xml")
    newest_release = metainfo.find("releases/release").get("version")
    assert pyproject["project"]["version"] == meson == __version__ == newest_release
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {__version__} " in changelog
