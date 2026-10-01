#!/usr/bin/env python3
"""Vendor GTK 4.22-compatible elementary icons for the HarmoniaElementary overlay.

elementary OS 8 ships elementary icons 8.x. Some of its symbolic icons position
their paths with a ``transform`` on a ``<g>`` element. GTK 4.21+ renders files
that only use its symbolic subset with its own renderer, which ignores group
transforms, so those icons are drawn off-canvas and appear blank in apps built
on the GNOME 50 runtime. elementary icons 9.x rewrote them without transforms.

This script compares two tags of a local elementary/icons checkout, finds the
icons used by Harmonia that are broken in OLD and fixed in NEW, and copies the
NEW versions into ``src/harmonia/icons/HarmoniaElementary``. Run it only when
updating the bundled assets, then review and commit the result.

    python3 tools/sync_elementary_icons.py /path/to/elementary-icons 8.2.0 9.0.0
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src" / "harmonia" / "icons" / "HarmoniaElementary" / "scalable" / "actions"
SVG = "{http://www.w3.org/2000/svg}"
GRAPHICS = {SVG + "g", SVG + "path", SVG + "rect", SVG + "circle"}
# Attributes GTK's symbolic subset understands (or explicitly ignores). A file
# using anything else falls back to the full SVG renderer, which honours
# transforms, so only "pure" files are affected.
SUBSET_ATTRIBUTES = {
    "d", "fill", "fill-opacity", "fill-rule", "stroke", "stroke-opacity", "stroke-width",
    "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray",
    "stroke-dashoffset", "id", "style", "color", "overflow", "class", "transform", "cx",
    "cy", "r", "x", "y", "width", "height", "opacity", "marker", "marker-start",
    "marker-mid", "marker-end", "version", "enable-background", "display", "visibility",
}  # fmt: skip


def used_icon_names() -> set[str]:
    names: set[str] = set()
    for source in (ROOT / "src" / "harmonia").glob("*.py"):
        names.update(re.findall(r'"([a-z0-9][a-z0-9-]*-symbolic)"', source.read_text()))
    return names


def drawn_off_canvas_by_gtk(svg: str) -> bool:
    root = ET.fromstring(svg)
    transformed = any(e.get("transform") for e in root.iter() if e.tag in GRAPHICS)
    foreign = any(
        not element.tag.startswith(SVG)
        or any(a.startswith("{") or a not in SUBSET_ATTRIBUTES for a in element.attrib)
        for element in root.iter()
    )
    return transformed and not foreign


class Checkout:
    def __init__(self, path: Path, tag: str):
        self.path, self.tag = path, tag
        listing = self._git("ls-tree", "-r", tag)
        self.modes = {}
        for line in listing.splitlines():
            meta, name = line.split("\t", 1)
            self.modes[name] = meta.split()[0]

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.path), *args], check=True, capture_output=True, text=True
        ).stdout

    def icon(self, name: str) -> str | None:
        hits = sorted(p for p in self.modes if p.endswith(f"/symbolic/{name}.svg"))
        if not hits:
            return None
        path = hits[0]
        for _ in range(8):  # follow in-theme symlinks
            if self.modes.get(path) != "120000":
                return self._git("show", f"{self.tag}:{path}")
            target = self._git("show", f"{self.tag}:{path}").strip()
            path = os.path.normpath(os.path.join(os.path.dirname(path), target))
        return None


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__)
        return 2
    checkout, old_tag, new_tag = Path(argv[1]), argv[2], argv[3]
    old, new = Checkout(checkout, old_tag), Checkout(checkout, new_tag)
    TARGET.mkdir(parents=True, exist_ok=True)
    for stale in TARGET.glob("*.svg"):
        stale.unlink()
    copied = []
    for name in sorted(used_icon_names()):
        before, after = old.icon(name), new.icon(name)
        if not before or not after:
            continue
        if drawn_off_canvas_by_gtk(before) and "transform" not in after:
            notice = f"<!-- Source: elementary/icons {new_tag} (GPL-3.0-or-later) -->\n"
            body = after.lstrip()
            if body.startswith("<?xml"):  # the XML declaration must stay first
                declaration, body = body.split("?>", 1)
                body = f"{declaration}?>\n{notice}{body.lstrip()}"
            else:
                body = notice + body
            ET.fromstring(body)
            (TARGET / f"{name}.svg").write_text(body, encoding="utf-8")
            copied.append(name)
    print(f"HarmoniaElementary: {len(copied)} icons from {new_tag}: {', '.join(copied)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
