"""The Linux installer's decisions, run with a POSIX shell against fake tools."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("dash") or shutil.which("sh")
pytestmark = pytest.mark.skipif(SHELL is None, reason="no POSIX shell")


def shell_path(path: Path) -> str:
    """``path`` as the shell sees it (MSYS2 on Windows has no "C:" in PATH)."""
    if shutil.which("cygpath"):
        return subprocess.check_output(["cygpath", "-u", str(path)], text=True).strip()
    return path.as_posix()


def run(script: str) -> str:
    """Run ``script`` after sourcing install.sh's functions; returns stdout."""
    prelude = f'HARMONIA_INSTALLER_FUNCTIONS_ONLY=1; . "{shell_path(ROOT)}/install.sh"\n'
    result = subprocess.run(
        [SHELL, "-c", prelude + script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_versions_compare_numerically():
    script = """
    for pair in "1.8.1 1.7" "1.7 1.7" "1.10 1.7" "1.5.1 1.7" "1.6.9 1.7"; do
        set -- $pair
        if version_at_least "$1" "$2"; then echo yes; else echo no; fi
    done
    """
    assert run(script).split() == ["yes", "yes", "yes", "no", "no"]


def fake_tools(folder: Path, tools: dict[str, str]) -> str:
    """Executables standing in for the package managers, first on PATH."""
    for name, body in tools.items():
        tool = folder / name
        tool.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8", newline="\n")
        tool.chmod(0o755)
    # The fakes come first on PATH; "has" only sees them, so the package
    # managers of the machine running the tests are ignored.
    folder_path = shell_path(folder)
    return f'PATH="{folder_path}:$PATH"\nhas() {{ [ -x "{folder_path}/$1" ]; }}\n'


@pytest.mark.parametrize(
    ("candidate", "method"),
    [
        ("1.7.2-1ubuntu1", "deb"),  # Ubuntu 25.04
        ("1:1.8.0-1", "deb"),  # with an epoch
        ("1.5.0-1ubuntu2", "flatpak"),  # Ubuntu 24.04 and elementary OS 8
        ("(none)", "flatpak"),
    ],
)
def test_debian_systems_get_the_deb_only_with_a_new_enough_libadwaita(tmp_path, candidate, method):
    path = fake_tools(
        tmp_path,
        {
            "apt-get": "true",
            "dpkg": "true",
            "apt-cache": "printf 'gir1.2-adw-1:\\n  Installed: (none)\\n"
            f"  Candidate: {candidate}\\n'",
        },
    )
    output = run(path + 'choose_method; echo "=$method"')
    assert output.splitlines()[-1] == f"={method}"


@pytest.mark.parametrize(("version", "method"), [("1.8.2", "rpm"), ("1.4.4", "flatpak")])
def test_dnf_systems_get_the_rpm_only_with_a_new_enough_libadwaita(tmp_path, version, method):
    path = fake_tools(tmp_path, {"dnf": f"printf '%s\\n' '{version}'"})
    output = run(path + 'choose_method; echo "=$method"')
    assert output.splitlines()[-1] == f"={method}"


def test_other_systems_get_the_flatpak(tmp_path):
    path = fake_tools(tmp_path, {})
    assert run(path + 'choose_method; echo "=$method"').splitlines()[-1] == "=flatpak"


def test_the_latest_release_comes_from_the_github_listing(tmp_path):
    listing = tmp_path / "releases.json"
    listing.write_text(
        '[\n  {\n    "url": "x",\n    "tag_name": "v0.1.0-beta.2",\n'
        '    "name": "Harmonia 0.1.0-beta.2"\n  }\n]\n',
        encoding="utf-8",
    )
    script = f"""
    download_file() {{ cp "{shell_path(listing)}" "$2"; }}
    find_latest_release
    echo "$release"
    cleanup
    """
    assert run(script) == "0.1.0-beta.2"
