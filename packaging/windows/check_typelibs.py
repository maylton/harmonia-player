"""Fail when a bundled GObject typelib depends on one the bundle lacks.

    python packaging/windows/check_typelibs.py build/windows/dist/Harmonia/_internal/gi_typelibs

A typelib records its dependencies in its string table as one
"Namespace-Version|Namespace-Version" string, such as "win32-1.0|Gdk-4.0".
This reads it without loading the typelib, so the check does not depend on
the build machine's own GObject introspection search path.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_NAME = rb"[A-Za-z][A-Za-z0-9]*-\d+\.\d+"
DEPENDENCIES = re.compile(rb"\x00(" + _NAME + rb"(?:\|" + _NAME + rb")*)\x00")


def dependencies(typelib: Path) -> set[str]:
    found = set()
    for match in DEPENDENCIES.findall(typelib.read_bytes()):
        found.update(name.decode() for name in match.split(b"|"))
    return found - {typelib.stem}


def main(folder: str) -> int:
    bundled = {path.stem: path for path in Path(folder).glob("*.typelib")}
    missing = {
        name: sorted(dependencies(path) - set(bundled))
        for name, path in sorted(bundled.items())
        if dependencies(path) - set(bundled)
    }
    for name, absent in missing.items():
        print(f"{name}: faltam {', '.join(absent)}", file=sys.stderr)
    if missing:
        return 1
    print(f"{len(bundled)} typelibs, todas as dependências presentes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
