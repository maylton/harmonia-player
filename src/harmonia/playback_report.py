"""A plain-text report of a playback failure, for the user to paste in an issue.

It names the versions involved and the track, and keeps the error as given
(stream resolution errors list each InnerTube client's failure). URL query
strings are cut: YouTube's stream links carry the user's IP address.
"""

from __future__ import annotations

import platform
import re

from . import __version__, host
from .models import LibraryItem

_URL_QUERY = re.compile(r"(https?://[^\s?#]+)[?#][^\s)\"']*")


def scrub(text: str) -> str:
    return _URL_QUERY.sub(r"\1?…", text)


def gstreamer_version() -> str:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        return Gst.version_string()
    except (ImportError, ValueError):
        return "GStreamer ?"


def playback_report(error: str, item: LibraryItem | None) -> str:
    lines = [
        f"Harmonia {__version__} ({host.PLATFORM})",
        f"OS: {platform.platform()}",
        f"Python {platform.python_version()} · {gstreamer_version()}",
    ]
    if item is not None:
        lines.append(f"Track: {item.title} [{item.id}]")
    lines += ["", "Error:", scrub(error.strip())]
    return "\n".join(lines)
