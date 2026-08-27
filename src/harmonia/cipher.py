from __future__ import annotations

import logging
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .cipher_config import CipherConfig, RemoteCipherConfigStore
from .js_runtime import JavaScriptRuntime, JavaScriptRuntimeError, create_javascript_runtime
from .player_config import PlayerConfig, PlayerConfigResolver, WEB_USER_AGENT

LOGGER = logging.getLogger(__name__)
_PLAYER_IIFE_TRAILER = "})(_yt_player);"
_MAX_PLAYER_JS = 8 * 1024 * 1024
_N_PROBE_INPUT = "KdrqFlzJXl9EcCwlmEy"
_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
_SIGNATURE_PATTERNS = (
    re.compile(rf"\.sig\|\|({_IDENTIFIER})\("),
    re.compile(rf"[\"']signature[\"']\s*,\s*({_IDENTIFIER})\("),
    re.compile(rf"\bc\s*&&\s*d\.set\([^,]+,\s*({_IDENTIFIER})\("),
    re.compile(
        rf"({_IDENTIFIER})\s*=\s*function\(([A-Za-z_$][A-Za-z0-9_$]*)\)"
        rf"\{{\2=\2\.split\([\"'][\"']\)"
    ),
)
_N_PATTERNS = (
    re.compile(
        rf"\.get\([\"']n[\"']\)\)\s*&&\s*\([^=]+="
        rf"({_IDENTIFIER}(?:\[\d+\])?)\("
    ),
    re.compile(rf"\bn\s*=\s*({_IDENTIFIER}(?:\[\d+\])?)\(n\)"),
)
_YOUTUBE_GLOBALS = r"""
if (typeof globalThis.XMLHttpRequest === "undefined") {
  globalThis.XMLHttpRequest = { prototype: {} };
}
if (typeof URL === "undefined") {
  globalThis.location = {
    hash: "", host: "www.youtube.com", hostname: "www.youtube.com",
    href: "https://www.youtube.com/watch?v=yt-dlp-wins",
    origin: "https://www.youtube.com", password: "", pathname: "/watch",
    port: "", protocol: "https:", search: "?v=yt-dlp-wins", username: ""
  };
} else {
  globalThis.location = new URL("https://www.youtube.com/watch?v=yt-dlp-wins");
}
if (typeof globalThis.document === "undefined") globalThis.document = Object.create(null);
if (typeof globalThis.navigator === "undefined") globalThis.navigator = Object.create(null);
if (typeof globalThis.self === "undefined") globalThis.self = globalThis;
if (typeof globalThis.window === "undefined") globalThis.window = globalThis;
if (typeof globalThis.Intl === "undefined") {
  const NumberFormat = function(locale, options) { this.options = options || {}; };
  NumberFormat.supportedLocalesOf = function(locales) {
    return Array.isArray(locales) ? locales : [locales];
  };
  NumberFormat.prototype.format = function(value) {
    let formatted = String(value);
    const minimumDigits = this.options.minimumIntegerDigits || 0;
    while (formatted.length < minimumDigits) formatted = "0" + formatted;
    return formatted;
  };
  const DateTimeFormat = function() {};
  DateTimeFormat.prototype.resolvedOptions = function() { return { timeZone: "UTC" }; };
  DateTimeFormat.prototype.format = function(value) { return String(value); };
  globalThis.Intl = { NumberFormat, DateTimeFormat };
}
"""


@dataclass(frozen=True, slots=True)
class CipherResult:
    url: str
    transformed_signature: bool = False
    transformed_n: bool = False


class _ZemerSolver:
    def __init__(
        self,
        player_code: str,
        config: CipherConfig,
        runtime_factory: Callable[[], JavaScriptRuntime] = create_javascript_runtime,
    ) -> None:
        self.config = config
        self.runtime = runtime_factory()
        self.runtime.execute(_YOUTUBE_GLOBALS)
        self.runtime.execute("globalThis._yt_player = globalThis._yt_player || {};")
        self.runtime.execute(self._modified_player_script(player_code, config))

        probe = self.solve_n(_N_PROBE_INPUT)
        if (
            not probe
            or probe == _N_PROBE_INPUT
            or len(probe) < 5
            or not all(char.isalnum() or char in "_-" for char in probe)
        ):
            raise JavaScriptRuntimeError("YouTube n-transform probe failed")

    @staticmethod
    def _modified_player_script(player_code: str, config: CipherConfig) -> str:
        signature = config.signature_expression.replace("INPUT", "sig")
        n_expression = (
            "(function(n){try{var u=new g."
            + config.n_class
            + "('https://x.googlevideo.com/videoplayback?n='+n,true);"
            + "var t=u.get('n');return(t&&t!==n)?t:n;}catch(e){return n;}})(n)"
        )
        exports = (
            ";window._cipherSigFunc=function(sig){try{return "
            + signature
            + ";}catch(e){return null;}};"
            + "window._nTransformFunc=function(n){try{return "
            + n_expression
            + ";}catch(e){return n;}};"
        )
        if _PLAYER_IIFE_TRAILER in player_code:
            return player_code.replace(
                _PLAYER_IIFE_TRAILER,
                exports + _PLAYER_IIFE_TRAILER,
                1,
            )
        return player_code + "\n" + exports

    def solve_signature(self, value: str) -> str | None:
        return self.runtime.call("_cipherSigFunc", value)

    def solve_n(self, value: str) -> str | None:
        return self.runtime.call("_nTransformFunc", value)


class _PlayerScriptFallbackSolver:
    """Best-effort local fallback for a player hash not present in Zemer.

    Modern YouTube players still expose the selected signature and n transform
    through call sites in base.js. The solver discovers those lexical symbols,
    exports them immediately before the player's IIFE closes, and executes the
    real functions instead of attempting to reimplement their operations.
    """

    def __init__(
        self,
        player_code: str,
        runtime_factory: Callable[[], JavaScriptRuntime] = create_javascript_runtime,
    ) -> None:
        signature_expression = self._find_expression(player_code, _SIGNATURE_PATTERNS)
        n_expression = self._find_expression(player_code, _N_PATTERNS)
        if signature_expression is None and n_expression is None:
            raise JavaScriptRuntimeError("Unable to discover YouTube cipher entry points")

        exports: list[str] = []
        if signature_expression is not None:
            exports.append(
                "window._cipherSigFunc=(typeof "
                + signature_expression
                + "==='function'?"
                + signature_expression
                + ":null);"
            )
        if n_expression is not None:
            exports.append(
                "window._nTransformFunc=(typeof "
                + n_expression
                + "==='function'?"
                + n_expression
                + ":null);"
            )
        export_code = ";" + "".join(exports)
        modified = (
            player_code.replace(
                _PLAYER_IIFE_TRAILER,
                export_code + _PLAYER_IIFE_TRAILER,
                1,
            )
            if _PLAYER_IIFE_TRAILER in player_code
            else player_code + "\n" + export_code
        )

        self.runtime = runtime_factory()
        self.runtime.execute(_YOUTUBE_GLOBALS)
        self.runtime.execute("globalThis._yt_player = globalThis._yt_player || {};")
        self.runtime.execute(modified)

    @staticmethod
    def _find_expression(player_code: str, patterns: tuple[re.Pattern[str], ...]) -> str | None:
        for pattern in patterns:
            match = pattern.search(player_code)
            if match:
                return match.group(1)
        return None

    def solve_signature(self, value: str) -> str | None:
        try:
            return self.runtime.call("_cipherSigFunc", value)
        except JavaScriptRuntimeError:
            return None

    def solve_n(self, value: str) -> str | None:
        try:
            return self.runtime.call("_nTransformFunc", value)
        except JavaScriptRuntimeError:
            return None


class YouTubeCipherService:
    """Resolve signatureCipher and n-throttling using the active YouTube player JS.

    Zemer/Faraday-style player configs remain the fast path. When a player hash
    rotates before the remote catalog catches up, Harmonia falls back to lexical
    entry-point discovery in the live base.js instead of discarding every
    ciphered format.
    """

    def __init__(
        self,
        client,
        *,
        config_resolver: PlayerConfigResolver | None = None,
        config_store: RemoteCipherConfigStore | None = None,
        runtime_factory: Callable[[], JavaScriptRuntime] = create_javascript_runtime,
    ) -> None:
        self.client = client
        self.config_resolver = config_resolver or PlayerConfigResolver(client)
        self.config_store = config_store or RemoteCipherConfigStore(client)
        self.runtime_factory = runtime_factory
        self._solver_cache: dict[str, Any] = {}
        self._player_code_cache: dict[str, str] = {}

    def _player_js(self, player_url: str) -> str:
        cached = self._player_code_cache.get(player_url)
        if cached is not None:
            return cached
        request = urllib.request.Request(
            player_url,
            headers={"User-Agent": WEB_USER_AGENT, "Accept": "*/*"},
        )
        with self.client._open(request, timeout=15) as response:
            raw = response.read(_MAX_PLAYER_JS + 1)
        if len(raw) > _MAX_PLAYER_JS:
            raise OSError("YouTube player JavaScript exceeded size limit")
        code = raw.decode(errors="replace")
        self._player_code_cache[player_url] = code
        while len(self._player_code_cache) > 4:
            self._player_code_cache.pop(next(iter(self._player_code_cache)))
        return code

    def _solver(self, video_id: str, *, authenticated: bool) -> tuple[Any, PlayerConfig]:
        player = self.config_resolver.fetch(
            video_id,
            use_login_cookies=authenticated,
        )
        cached = self._solver_cache.get(player.player_url)
        if cached is not None:
            return cached, player

        player_code = self._player_js(player.player_url)
        config = self.config_store.for_player(player.player_url)
        solver = None
        if config is not None:
            try:
                solver = _ZemerSolver(
                    player_code,
                    config,
                    runtime_factory=self.runtime_factory,
                )
            except Exception as exc:
                LOGGER.debug("Zemer cipher initialization failed: %s", exc)
        if solver is None:
            solver = _PlayerScriptFallbackSolver(
                player_code,
                runtime_factory=self.runtime_factory,
            )
        self._solver_cache[player.player_url] = solver
        while len(self._solver_cache) > 4:
            self._solver_cache.pop(next(iter(self._solver_cache)))
        return solver, player

    def refresh_after_stream_rejection(self) -> bool:
        changed = self.config_store.refresh_after_stream_rejection()
        if changed:
            self._solver_cache.clear()
        return changed

    def invalidate(self) -> None:
        self._solver_cache.clear()
        self._player_code_cache.clear()

    @staticmethod
    def _cipher_values(fmt: dict[str, Any]) -> dict[str, list[str]]:
        raw = fmt.get("signatureCipher") or fmt.get("cipher") or ""
        return urllib.parse.parse_qs(str(raw), keep_blank_values=True)

    @staticmethod
    def _set_query_parameter(url: str, key: str, value: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        query = [(name, current) for name, current in query if name != key]
        query.append((key, value))
        return urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urllib.parse.urlencode(query),
                parsed.fragment,
            )
        )

    def resolve_format_url(
        self,
        fmt: dict[str, Any],
        video_id: str,
        *,
        authenticated: bool = False,
    ) -> CipherResult | None:
        direct = fmt.get("url")
        values = self._cipher_values(fmt)
        encrypted_signature = (values.get("s") or [None])[0]
        clear_signature = (values.get("sig") or values.get("signature") or [None])[0]
        signature_parameter = (values.get("sp") or ["signature"])[0]
        cipher_url = (values.get("url") or [None])[0]
        url = str(direct or cipher_url or "")
        if not url:
            return None

        signature_changed = False
        n_changed = False
        solver = None

        if encrypted_signature:
            try:
                solver, _player = self._solver(video_id, authenticated=authenticated)
                signature = solver.solve_signature(encrypted_signature)
            except Exception as exc:
                LOGGER.debug("YouTube signature decipher failed: %s", exc)
                return None
            if not signature:
                return None
            url = self._set_query_parameter(url, signature_parameter, signature)
            signature_changed = True
        elif clear_signature:
            url = self._set_query_parameter(url, signature_parameter, clear_signature)

        parsed = urllib.parse.urlsplit(url)
        values_n = urllib.parse.parse_qs(parsed.query, keep_blank_values=True).get("n")
        if values_n:
            original_n = values_n[0]
            try:
                if solver is None:
                    solver, _player = self._solver(video_id, authenticated=authenticated)
                transformed_n = solver.solve_n(original_n)
            except Exception as exc:
                LOGGER.debug("YouTube n-transform failed: %s", exc)
                transformed_n = None
            if transformed_n and transformed_n != original_n:
                url = self._set_query_parameter(url, "n", transformed_n)
                n_changed = True

        return CipherResult(
            url=url,
            transformed_signature=signature_changed,
            transformed_n=n_changed,
        )
