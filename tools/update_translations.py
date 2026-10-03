"""Regenerate po/harmonia.pot and merge it into every catalog in po/LINGUAS.

Python sources (po/POTFILES) and QML sources (po/POTFILES.qml) need different
xgettext parsers: run as C, which is what xgettext guesses for .qml, an
apostrophe in a QML comment starts a character literal and silently hides the
strings after it. So each group is extracted with its own language and the
results are concatenated. Merged catalogs keep no obsolete entries; new
messages are left untranslated for a translator (the tests list them).

    python3 tools/update_translations.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PO = ROOT / "po"
BUGS_ADDRESS = "https://github.com/maylton/harmonia-player/issues"
SOURCES = (
    ("POTFILES", "Python", ("--keyword=_", "--keyword=ngettext:1,2")),
    (
        "POTFILES.qml",
        "JavaScript",
        ("--keyword=tr", "--keyword=trf", "--keyword=ntr:1,2", "--keyword=ntrf:1,2"),
    ),
)


def extract(target: Path) -> None:
    with tempfile.TemporaryDirectory() as folder:
        parts = []
        for listing, language, keywords in SOURCES:
            files = (PO / listing).read_text(encoding="utf-8").split()
            part = Path(folder) / f"{language}.pot"
            subprocess.run(
                [
                    "xgettext",
                    f"--language={language}",
                    "--from-code=UTF-8",
                    "--add-comments=TRANSLATORS",
                    "--package-name=harmonia",
                    f"--msgid-bugs-address={BUGS_ADDRESS}",
                    *keywords,
                    "-o",
                    str(part),
                    *files,
                ],
                cwd=ROOT,
                check=True,
            )
            parts.append(str(part))
        subprocess.run(["msgcat", "--use-first", "-o", str(target), *parts], check=True)


def main() -> int:
    template = PO / "harmonia.pot"
    extract(template)
    for language in (PO / "LINGUAS").read_text(encoding="utf-8").split():
        catalog = PO / f"{language}.po"
        subprocess.run(
            ["msgmerge", "--quiet", "--update", "--backup=none", "--no-fuzzy-matching",
             str(catalog), str(template)],
            check=True,
        )  # fmt: skip
        subprocess.run(["msgattrib", "--no-obsolete", "-o", str(catalog), str(catalog)], check=True)
        untranslated = (
            subprocess.run(
                ["msgattrib", "--untranslated", "--no-obsolete", str(catalog)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.count("\nmsgid ")
            - 1
        )
        print(f"{catalog.relative_to(ROOT)}: {max(untranslated, 0)} sem tradução")
    return 0


if __name__ == "__main__":
    sys.exit(main())
