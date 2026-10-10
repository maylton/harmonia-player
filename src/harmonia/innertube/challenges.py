"""YouTube's player script: its signature timestamp and the n/sig challenges.

The clients that return age-restricted tracks give encrypted stream URLs: a
``sig`` to compute from the ``s`` parameter and an ``n`` parameter to
transform, both with functions inside YouTube's player JavaScript. The
solver of yt-dlp/ejs (ejs/) finds and runs them in a JavaScript engine
(js_runtime.py). The player changes every few days; each version is
fetched once, and the solver's preprocessed copy of it is kept on disk.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import host
from ..js_runtime import JsRuntime, JsRuntimeError, find_runtime
from .protocol import InnerTubeError

WWW = "https://www.youtube.com"
_PLAYER_ID = re.compile(r"player\\?/([0-9a-fA-F]{8})\\?/")
_STS = re.compile(r"(?:signatureTimestamp|sts)\s*:\s*([0-9]{5})")
_SOLVER = Path(__file__).with_name("ejs")
# How long the current player id is trusted before asking YouTube again.
PLAYER_ID_TTL_S = 6 * 60 * 60
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


class NoJsRuntimeError(InnerTubeError):
    """There is no JavaScript engine to run the player's challenges."""


@dataclass(frozen=True, slots=True)
class Player:
    id: str
    sts: int


class PlayerChallenges:
    """The current player and the answers to its challenges."""

    def __init__(self, cache_dir: Path | None = None, runtime_finder=find_runtime, opener=None):
        self._cache_dir = cache_dir
        self._find_runtime = runtime_finder
        self._open = opener or (lambda request: urllib.request.urlopen(request, timeout=30))
        self._lock = threading.Lock()
        self._player: Player | None = None
        self._player_checked = 0.0

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir or host.cache_dir() / "player"

    def _get(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with self._open(request) as response:
                return response.read().decode("utf-8", "replace")
        except OSError as exc:
            raise InnerTubeError(f"player: {exc}") from exc

    def _code_path(self, player_id: str, kind: str) -> Path:
        return self.cache_dir / f"{player_id}.{kind}.js"

    def player(self) -> Player:
        """The player YouTube serves now, fetched once per version."""
        with self._lock:
            if self._player and time.monotonic() - self._player_checked < PLAYER_ID_TTL_S:
                return self._player
            match = _PLAYER_ID.search(self._get(f"{WWW}/iframe_api"))
            if not match:
                raise InnerTubeError("player: id not found")
            player_id = match.group(1)
            sts = _STS.search(self._player_code(player_id))
            if not sts:
                raise InnerTubeError("player: signatureTimestamp not found")
            self._player = Player(player_id, int(sts.group(1)))
            self._player_checked = time.monotonic()
            return self._player

    def _player_code(self, player_id: str) -> str:
        path = self._code_path(player_id, "base")
        if path.is_file():
            return path.read_text(encoding="utf-8")
        code = self._get(f"{WWW}/s/player/{player_id}/player_ias.vflset/en_US/base.js")
        self._store(path, code)
        return code

    def _store(self, path: Path, code: str) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Old versions are useless once YouTube moved on.
            for old in path.parent.glob("*.js"):
                if not old.name.startswith(path.name.split(".", 1)[0]):
                    old.unlink(missing_ok=True)
            path.write_text(code, encoding="utf-8")
        except OSError:
            pass  # without the cache it is only slower

    def solve(
        self, player: Player, n: list[str], sig: list[str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Answers to the n and sig challenges, by challenge."""
        runtime: JsRuntime | None = self._find_runtime()
        if runtime is None:
            raise NoJsRuntimeError("no JavaScript engine")
        requests = [
            {"type": kind, "challenges": sorted(set(values))}
            for kind, values in (("n", n), ("sig", sig))
            if values
        ]
        if not requests:
            return {}, {}
        preprocessed_path = self._code_path(player.id, "pre")
        if preprocessed_path.is_file():
            data = {
                "type": "preprocessed",
                "preprocessed_player": preprocessed_path.read_text(encoding="utf-8"),
                "requests": requests,
            }
        else:
            data = {
                "type": "player",
                "player": self._player_code(player.id),
                "requests": requests,
                "output_preprocessed": True,
            }
        body = "\n".join(
            (
                (_SOLVER / "lib.min.js").read_text(encoding="utf-8"),
                "Object.assign(globalThis, lib);",
                (_SOLVER / "core.min.js").read_text(encoding="utf-8"),
            )
        )
        try:
            output = json.loads(runtime.run(body, f"JSON.stringify(jsc({json.dumps(data)}))"))
        except (JsRuntimeError, ValueError) as exc:
            raise InnerTubeError(f"{runtime.name}: {exc}") from exc
        if output.get("type") == "error":
            raise InnerTubeError(f"solver: {output.get('error')}")
        if output.get("preprocessed_player"):
            self._store(preprocessed_path, output["preprocessed_player"])
        answers: dict[str, dict[str, str]] = {"n": {}, "sig": {}}
        for request, response in zip(requests, output.get("responses", []), strict=False):
            if response.get("type") != "result":
                raise InnerTubeError(f"solver {request['type']}: {response.get('error')}")
            answers[request["type"]] = dict(response.get("data") or {})
        return answers["n"], answers["sig"]


CHALLENGES = PlayerChallenges()
