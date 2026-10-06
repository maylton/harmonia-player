"""Pack the hicolor launcher PNGs into a Windows .ico (PNG-compressed entries).

    python packaging/windows/make_ico.py data/icons/hicolor build/harmonia.ico
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

SIZES = (16, 32, 48, 64, 128, 256)
ICON_NAME = "io.github.harmonia.Harmonia.png"


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for size, data in images:
        # Width and height 0 mean 256 in the ICONDIRENTRY.
        dimension = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return header + entries + b"".join(data for _size, data in images)


def main(source: str, target: str) -> int:
    root = Path(source)
    images = [(size, (root / f"{size}x{size}" / "apps" / ICON_NAME).read_bytes()) for size in SIZES]
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_bytes(build_ico(images))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
