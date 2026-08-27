from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class _ClientState:
    failures: int = 0
    blocked_until: float = 0.0
    last_success: float = 0.0
    last_failure: float = 0.0


class ClientHealthTracker:
    """In-memory health/cooldown tracker for InnerTube playback identities.

    A broken YouTube client/profile should not be retried for every track. The
    cooldown grows with consecutive failures and is cleared immediately after a
    successful extraction. This mirrors InnerTubeX's client-health concept while
    keeping state local to the running Harmonia process.
    """

    def __init__(self) -> None:
        self._states: dict[str, _ClientState] = {}
        self._lock = threading.Lock()

    def available(self, profile_id: str) -> bool:
        now = time.monotonic()
        with self._lock:
            state = self._states.get(profile_id)
            return state is None or state.blocked_until <= now

    def order_key(self, profile_id: str, priority: int) -> tuple[int, int, float]:
        """Sort healthy/low-failure profiles before degraded ones, preserving priority."""
        now = time.monotonic()
        with self._lock:
            state = self._states.get(profile_id) or _ClientState()
            blocked = 1 if state.blocked_until > now else 0
            return blocked, state.failures, -float(priority)

    def success(self, profile_id: str) -> None:
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(profile_id, _ClientState())
            state.failures = 0
            state.blocked_until = 0.0
            state.last_success = now

    def failure(
        self,
        profile_id: str,
        *,
        transient: bool = False,
        severe: bool = False,
    ) -> None:
        now = time.monotonic()
        with self._lock:
            state = self._states.setdefault(profile_id, _ClientState())
            state.failures = min(8, state.failures + 1)
            state.last_failure = now
            if transient:
                base = 5.0
            elif severe:
                base = 180.0
            else:
                base = 30.0
            state.blocked_until = max(
                state.blocked_until,
                now + min(15 * 60.0, base * (2 ** max(0, state.failures - 1))),
            )

    def reset(self) -> None:
        with self._lock:
            self._states.clear()


CLIENT_HEALTH = ClientHealthTracker()
