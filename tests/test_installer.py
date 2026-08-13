from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def test_installer_is_valid_posix_shell() -> None:
    result = subprocess.run(
        ["sh", "-n", str(INSTALLER)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_installer_help_documents_safe_installation() -> None:
    result = subprocess.run(
        ["sh", str(INSTALLER), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "io.github.harmonia.Harmonia" not in result.stderr
    assert "--bundle FILE" in result.stdout
    assert "SHA-256" in result.stdout
    assert "--uninstall" in result.stdout
