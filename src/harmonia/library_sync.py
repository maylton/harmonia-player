"""Merge YouTube Music's library listings into the local cache without losing items.

YouTube Music is the source of truth: what it no longer lists is dropped. Three
cases used to lose data and are handled here:

- An incomplete listing (more pages than were read) only adds: what it lacks
  may just be on the pages not read.
- An empty listing over a cache that still has items is taken as a failed
  response, which YouTube Music sometimes gives, unless every cached item was
  removed here.
- Changes made here (like, subscribe, save, delete) take YouTube a while to
  show. Until a listing reflects them, or PENDING_TTL_S passes, they are kept
  on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import LibraryItem

PENDING_TTL_S = 15 * 60


@dataclass(frozen=True, slots=True)
class Listing:
    """What YouTube Music listed for a category, and whether every page was read."""

    items: list[LibraryItem]
    complete: bool = True


@dataclass(frozen=True, slots=True)
class PendingChange:
    category: str
    item: LibraryItem
    added: bool
    created_at: int = 0


def merge_category(
    cached: list[LibraryItem], listing: Listing, pending: list[PendingChange]
) -> list[LibraryItem]:
    fresh = listing.items
    fresh_ids = {item.id for item in fresh}
    removed = {change.item.id for change in pending if not change.added}
    if not fresh and any(item.id not in removed for item in cached):
        base = cached
    elif listing.complete:
        base = fresh
    else:
        base = fresh + [item for item in cached if item.id not in fresh_ids]
    added = [change.item for change in pending if change.added]
    result: list[LibraryItem] = []
    seen: set[str] = set()
    # Changes made here go first, as YouTube lists the newest first.
    for item in [*added, *base]:
        if item.id in removed or item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def settled(change: PendingChange, listing: Listing) -> bool:
    """True once YouTube's listing shows the change, so it needs no more help."""
    listed = any(item.id == change.item.id for item in listing.items)
    if change.added:
        return listed
    return listing.complete and not listed


def merge_library(
    cached: dict[str, list[LibraryItem]],
    listings: dict[str, Listing],
    pending: list[PendingChange],
) -> tuple[dict[str, list[LibraryItem]], list[PendingChange]]:
    """The merged categories that were listed, and the pending changes now settled."""
    merged: dict[str, list[LibraryItem]] = {}
    done: list[PendingChange] = []
    for category, listing in listings.items():
        changes = [change for change in pending if change.category == category]
        merged[category] = merge_category(cached.get(category, []), listing, changes)
        done.extend(change for change in changes if settled(change, listing))
    return merged, done
