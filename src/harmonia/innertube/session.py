"""The InnerTube session: the transport, the SAPISIDHASH authentication and the
configuration the YouTube Music page gives the signed-in session.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .. import host
from ..i18n import _
from .protocol import (
    API_URL,
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_VERSION,
    ORIGIN,
    USER_AGENT,
    InnerTubeError,
    sapisid_hash,
)


class InnerTubeSession:
    """Posts InnerTube requests, as the user when there is a session."""

    def __init__(
        self,
        cookie: str,
        hl: str | None = None,
        gl: str | None = None,
        max_bitrate: int | None = None,
        proxy: str = "",
        identity: str = "",
    ):
        self.cookie = cookie.strip()
        # A brand channel of the same login to act as; see accounts.py.
        self.identity = identity
        language = host.user_locale()
        language = language if language and language not in ("C", "POSIX") else "pt_BR"
        self.hl = hl or language.replace("_", "-")
        self.gl = gl or (language.split("_")[-1] if "_" in language else "BR")
        self.client_version = CLIENT_VERSION
        self.visitor_data: str | None = None
        self.data_sync_id: str | None = None
        self.session_data_sync_id = ""
        self.session_index: str | None = None
        self._bootstrapped = False
        self.max_bitrate = max_bitrate or 10_000_000
        self._proxy_opener = (
            urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
            if proxy
            else None
        )

    def _open(self, request, timeout=30):
        """Keep the default opener late-bound so tests and embedders can inject it."""
        if self._proxy_opener:
            return self._proxy_opener.open(request, timeout=timeout)
        return urllib.request.urlopen(request, timeout=timeout)

    @property
    def authenticated(self) -> bool:
        try:
            sapisid_hash(self.cookie)
            return True
        except InnerTubeError:
            return False

    def validate_session(self) -> bool:
        if not self.authenticated:
            return False
        self._bootstrap()
        return True

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._api_post("browse", body, authenticated=True)

    def _api_post(
        self,
        endpoint: str,
        body: dict[str, Any],
        authenticated: bool = True,
        as_identity: bool = True,
    ) -> dict[str, Any]:
        if authenticated:
            self._bootstrap()
        # Acting as a channel needs the session's credentials: an anonymous
        # request with onBehalfOfUser is refused with 401, which used to read
        # as an expired cookie (searches, after a signed-in call on the same
        # client, as video lookups do).
        acting_as = self.data_sync_id if authenticated and as_identity else None
        context = {
            "client": {
                "clientName": CLIENT_NAME,
                "clientVersion": self.client_version,
                "hl": self.hl,
                "gl": self.gl,
                **({"visitorData": self.visitor_data} if self.visitor_data else {}),
            },
            "user": {**({"onBehalfOfUser": acting_as} if acting_as else {})},
        }
        body = {"context": context, **body}
        query_separator = "&" if "?" in endpoint else "?"
        request = urllib.request.Request(
            f"{API_URL}/{endpoint}{query_separator}prettyPrint=false",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Origin": ORIGIN,
                "Referer": f"{ORIGIN}/",
                "X-Origin": ORIGIN,
                "X-Goog-Api-Format-Version": "1",
                "X-YouTube-Client-Name": CLIENT_ID,
                "X-YouTube-Client-Version": self.client_version,
                **({"X-Goog-Visitor-Id": self.visitor_data} if self.visitor_data else {}),
                **(
                    {
                        "Cookie": self.cookie,
                        "Authorization": sapisid_hash(self.cookie),
                        **({"X-Goog-AuthUser": self.session_index} if self.session_index else {}),
                    }
                    if authenticated
                    else {}
                ),
            },
        )
        for attempt in range(3):
            try:
                with self._open(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                if exc.code in (401, 403) and authenticated:
                    raise InnerTubeError(
                        _("A sessão expirou ou o cookie não tem acesso ao YouTube Music.")
                    ) from exc
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    raise InnerTubeError(
                        _("YouTube Music respondeu HTTP {code}: {detail}").format(
                            code=exc.code, detail=detail
                        )
                    ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise InnerTubeError(
                        _("Não foi possível conectar ao YouTube Music: {error}").format(error=exc)
                    ) from exc
            time.sleep(0.2 * (2**attempt))
        raise InnerTubeError(_("Não foi possível concluir a requisição ao YouTube Music."))

    def _bootstrap(self) -> None:
        """Read the live InnerTube configuration associated with this session."""
        if self._bootstrapped:
            return
        request = urllib.request.Request(
            f"{ORIGIN}/",
            headers={"Cookie": self.cookie, "User-Agent": USER_AGENT, "Accept-Language": self.hl},
        )
        try:
            with self._open(request, timeout=30) as response:
                html = response.read().decode(errors="replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            raise InnerTubeError(
                _("Não foi possível iniciar a sessão do YouTube Music: {error}").format(error=exc)
            ) from exc

        def config(name: str) -> str | None:
            match = re.search(rf'"{name}"\s*:\s*(?:"([^"]*)"|([0-9]+))', html)
            return (match.group(1) or match.group(2)) if match else None

        self.client_version = config("INNERTUBE_CLIENT_VERSION") or CLIENT_VERSION
        self.visitor_data = config("VISITOR_DATA")
        data_sync = config("DATASYNC_ID")
        self.session_data_sync_id = data_sync or ""
        self.data_sync_id = self.identity or (data_sync.split("||", 1)[0] if data_sync else None)
        self.session_index = config("SESSION_INDEX")
        self._bootstrapped = True
