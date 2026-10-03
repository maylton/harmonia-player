import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

ADW_VERSION = subprocess.run(
    [
        sys.executable,
        "-c",
        "import gi; gi.require_version('Adw', '1'); from gi.repository import Adw; "
        "print(Adw.MAJOR_VERSION, Adw.MINOR_VERSION)",
    ],
    capture_output=True,
    text=True,
).stdout.split()


@pytest.mark.skipif(
    len(ADW_VERSION) != 2 or tuple(map(int, ADW_VERSION)) < (1, 7),
    reason="a janela GTK exige libadwaita >= 1.7; o CI roda o smoke no Flatpak GNOME",
)
def test_every_page_theme_and_icon_style_opens_without_warnings():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gtk_smoke.py")],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
