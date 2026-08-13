from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CATALOGS = ("pt_BR", "en")
GETTEXT_CALL = re.compile(r"(?:^|[^A-Za-z0-9_])(?:_|ngettext)\(")


def test_potfiles_covers_every_translatable_python_module() -> None:
    listed = {
        line.strip()
        for line in (ROOT / "po" / "POTFILES").read_text().splitlines()
        if line.strip().endswith(".py")
    }
    translatable = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "harmonia").glob("*.py")
        if GETTEXT_CALL.search(path.read_text())
    }

    assert translatable <= listed


@pytest.mark.parametrize("language", CATALOGS)
def test_catalog_is_complete_and_valid(language: str, tmp_path: Path) -> None:
    catalog = ROOT / "po" / f"{language}.po"
    output = tmp_path / f"{language}.mo"
    subprocess.run(
        ["msgfmt", "--check", "--check-format", "-o", output, catalog],
        check=True,
        capture_output=True,
        text=True,
    )
    untranslated = subprocess.run(
        ["msgattrib", "--untranslated", "--no-obsolete", catalog],
        check=True,
        capture_output=True,
        text=True,
    )
    assert not untranslated.stdout.strip()


@pytest.mark.parametrize(
    ("language", "expected_library", "expected_plural"),
    (
        ("pt_BR", "Biblioteca", "2 músicas"),
        ("en", "Library", "2 songs"),
    ),
)
def test_runtime_loads_catalog(
    language: str,
    expected_library: str,
    expected_plural: str,
    tmp_path: Path,
) -> None:
    locale_dir = tmp_path / "locale"
    messages = locale_dir / language / "LC_MESSAGES"
    messages.mkdir(parents=True)
    subprocess.run(
        ["msgfmt", "-o", messages / "harmonia.mo", ROOT / "po" / f"{language}.po"],
        check=True,
    )
    code = (
        "from harmonia.i18n import _, ngettext; "
        "print(_('Biblioteca')); "
        "print(ngettext('{count} música', '{count} músicas', 2).format(count=2))"
    )
    environment = os.environ.copy()
    environment.update(
        {
            "HARMONIA_LOCALE_DIR": str(locale_dir),
            "LANGUAGE": language,
            "LC_ALL": "C.UTF-8",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.stdout.splitlines() == [expected_library, expected_plural]
