"""GNOME's timed wallpapers: XML files whose image changes through the day.

The file has an optional <starttime>, then <static> images, each shown for
its <duration> in seconds, and <transition>s that fade <from> one image <to>
the next; the whole sequence repeats. Dynamic wallpapers (a different image
for dawn, day, dusk and night) are written this way, so the image shown now
depends on the clock, not on the file's first entry.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Slide:
    duration: float
    image: Path
    # A transition's second image: it shows from the transition's midpoint on.
    next_image: Path | None = None


def _number(element: ET.Element | None, default: float = 0.0) -> float:
    try:
        return float((element.text or "").strip()) if element is not None else default
    except ValueError:
        return default


def _file(element: ET.Element | None, locate: Callable[[Path], Path]) -> Path | None:
    """A <file>, <from> or <to>: a path, or <size> variants (the largest wins)."""
    if element is None:
        return None
    sizes = element.findall("size")
    if sizes:
        largest = max(sizes, key=lambda size: _area(size.get("width"), size.get("height")))
        text = largest.text
    else:
        text = element.text
    text = (text or "").strip()
    return locate(Path(text)) if text else None


def _area(width: str | None, height: str | None) -> int:
    try:
        return int(width or 0) * int(height or 0)
    except ValueError:
        return 0


def _start(root: ET.Element) -> datetime | None:
    start = root.find("starttime")
    if start is None:
        return None
    parts = [int(_number(start.find(name))) for name in ("year", "month", "day", "hour", "minute")]
    try:
        return datetime(*parts, int(_number(start.find("second"))))
    except ValueError:
        return None


def slides(
    path: Path, locate: Callable[[Path], Path] = lambda path: path
) -> tuple[datetime | None, list[Slide]]:
    """The start time and the sequence of a slideshow file."""
    root = ET.parse(path).getroot()
    found: list[Slide] = []
    for element in root:
        duration = _number(element.find("duration"))
        if element.tag == "static":
            image = _file(element.find("file"), locate)
            if image is not None:
                found.append(Slide(duration, image))
        elif element.tag == "transition":
            first = _file(element.find("from"), locate)
            second = _file(element.find("to"), locate)
            if first is not None and second is not None:
                found.append(Slide(duration, first, second))
    return _start(root), found


def current_image(
    path: Path,
    now: datetime | None = None,
    locate: Callable[[Path], Path] = lambda path: path,
) -> tuple[Path | None, float | None]:
    """The image the desktop shows now, and in how many seconds it changes.

    None for the seconds when the slideshow never changes (one image).
    """
    start, sequence = slides(path, locate)
    if not sequence:
        return None, None
    total = sum(max(0.0, slide.duration) for slide in sequence)
    if len(sequence) == 1 or total <= 0:
        return sequence[0].image, None
    now = now or datetime.now()
    elapsed = (now - start).total_seconds() if start else now.timestamp()
    offset = elapsed % total
    for slide in sequence:
        duration = max(0.0, slide.duration)
        if offset < duration:
            if slide.next_image is None:
                return slide.image, duration - offset
            middle = duration / 2
            if offset < middle:
                return slide.image, middle - offset
            return slide.next_image, duration - offset
        offset -= duration
    return sequence[-1].next_image or sequence[-1].image, None
