"""What every Qt integration (Last.fm, Discord, Listen Together, recognition,
UPnP/DLNA) needs from the controller that exposes them to QML.

Each integration lives in its own module (qt_lastfm, qt_discord, qt_together,
qt_recognition, qt_cast) and keeps its state and logic there; the controller in
qt_integrations.py only declares the properties and slots QML uses.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Job:
    """A background operation and what to do on the Qt thread when it ends."""

    name: str
    on_done: Callable[[Any], None] | None = None
    on_failure: Callable[[str], None] | None = None
    # Shown as "<label>: <error>"; an empty label keeps the failure silent.
    failure_label: str = ""


@dataclass(slots=True)
class IntegrationContext:
    settings: Any  # QtPreferencesController
    playback: Any  # QtIntegratedPlaybackController
    storage: Any
    set_status: Callable[..., None]
    # run(job, operation): operation runs on the executor, the job's
    # callbacks on the Qt thread.
    run: Callable[[Job, Callable[[], Any]], None]
    save_preferences: Callable[[], None]
    changed: Callable[[], None] = field(default=lambda: None)
