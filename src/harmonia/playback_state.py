"""Toolkit-free playback queue rules shared by presentation frontends."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .models import LibraryItem, PlaybackState

AUTOPLAY_PREFETCH_REMAINING = 5


@dataclass(frozen=True, slots=True)
class QueueRemoval:
    index: int
    removed_current: bool
    empty: bool


def shuffled_queue_keep_current(
    queue: list[LibraryItem],
    current_index: int,
    *,
    shuffle: Callable[[list[LibraryItem]], None] = random.shuffle,
) -> tuple[list[LibraryItem], int]:
    """Return a shuffled copy with the current item kept at the front."""
    if not queue or not 0 <= current_index < len(queue):
        return list(queue), current_index
    current = queue[current_index]
    remainder = [item for index, item in enumerate(queue) if index != current_index]
    shuffle(remainder)
    return [current, *remainder], 0


def move_queue_item(
    queue: list[LibraryItem],
    current_index: int,
    index: int,
    direction: int,
) -> tuple[int, bool]:
    """Move one queue entry in place and return the adjusted current index."""
    target = index + direction
    if not (0 <= index < len(queue) and 0 <= target < len(queue)):
        return current_index, False
    queue[index], queue[target] = queue[target], queue[index]
    if current_index == index:
        current_index = target
    elif current_index == target:
        current_index = index
    return current_index, True


def remove_queue_item(
    queue: list[LibraryItem],
    current_index: int,
    index: int,
) -> QueueRemoval | None:
    """Remove one queue entry in place and describe the resulting selection."""
    if not 0 <= index < len(queue):
        return None
    removed_current = index == current_index
    queue.pop(index)
    if not queue:
        return QueueRemoval(-1, removed_current, True)
    if index < current_index:
        current_index -= 1
    elif current_index >= len(queue):
        current_index = len(queue) - 1
    return QueueRemoval(current_index, removed_current, False)


def filter_new_recommendations(
    queue: Iterable[LibraryItem],
    recommendations: Iterable[LibraryItem] | None,
) -> list[LibraryItem]:
    """Keep radio recommendations whose IDs are not already in the queue."""
    existing = {item.id for item in queue}
    return [item for item in recommendations or [] if item.id not in existing]


def radio_seed_for_autoplay(
    queue: list[LibraryItem],
    current_index: int,
    *,
    force: bool = False,
) -> LibraryItem | None:
    """Return the radio seed when autoplay should prefetch more queue entries."""
    if not queue:
        return None
    remaining = len(queue) - current_index - 1
    if not force and remaining > AUTOPLAY_PREFETCH_REMAINING:
        return None
    return queue[-1]


def playback_state_snapshot(
    queue: Iterable[LibraryItem],
    related: Iterable[LibraryItem],
    current_index: int,
    position_ms: int,
    *,
    shuffle: bool,
    repeat: bool,
    autoplay: bool,
) -> PlaybackState:
    """Build a normalized persistence snapshot without sharing mutable lists."""
    return PlaybackState(
        list(queue),
        list(related),
        max(0, current_index),
        max(0, position_ms),
        shuffle,
        repeat,
        autoplay,
    )


class StreamEndedEarly(str):
    """A player error for a stream that stopped before its known duration.

    It reads as its message; ``position_us`` says where the sound stopped,
    so playback can resume there instead of starting the track over.
    """

    position_us: int
    duration_us: int

    def __new__(cls, message: str, position_us: int, duration_us: int) -> StreamEndedEarly:
        error = super().__new__(cls, message)
        error.position_us = max(0, int(position_us))
        error.duration_us = max(0, int(duration_us))
        return error


@dataclass(frozen=True, slots=True)
class StreamRecovery:
    """What to do after a playback error: "renew" the stream and resume at
    ``resume_ms``, go to the "next" track, or "fail" and say why."""

    action: str
    resume_ms: int = 0


def stream_recovery(
    error: str, attempts: int, position_ms: int, *, renewable: bool = True
) -> StreamRecovery:
    """The same rule for both frontends.

    The first failure renews the stream and resumes where the sound stopped:
    starting over made the track play twice. A stream that ends early again
    has really ended (YouTube can announce more than it serves), so the queue
    moves on instead of stopping.
    """
    early = isinstance(error, StreamEndedEarly)
    if renewable and attempts < 1:
        resume_ms = error.position_us // 1000 if early else max(0, position_ms)
        return StreamRecovery("renew", resume_ms)
    return StreamRecovery("next" if early else "fail")
