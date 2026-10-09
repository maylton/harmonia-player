"""The YouTube channels one Google login can act as: the personal one and brand accounts.

account/accounts_list (the channel switcher) answers with ``accountItem``
renderers; each one's selectActiveIdentityEndpoint carries a
``datasyncIdToken`` ("<channel>||<google user>", or "<google user>||" for the
personal channel). Requests act as a channel by sending its first part as
``context.user.onBehalfOfUser``, which only works for channels of the same
Google login; other logins would need their own session.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

IDENTITY_SETTING = "youtube_identity"


@dataclass(frozen=True, slots=True)
class YouTubeIdentity:
    name: str
    data_sync_id: str  # "<channel>||<google user>"
    handle: str = ""
    byline: str = ""
    thumbnail: str | None = None
    selected: bool = False

    @property
    def id(self) -> str:
        """What requests send as onBehalfOfUser to act as this channel."""
        return self.data_sync_id.split("||", 1)[0]

    @property
    def google_user(self) -> str:
        channel, _sep, user = self.data_sync_id.partition("||")
        return user or channel


def _walk(value: Any) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if value.get("simpleText"):
        return str(value["simpleText"])
    return "".join(str(run.get("text", "")) for run in value.get("runs") or [])


def _token(item: dict, token: str, key: str) -> str:
    for node in _walk(item.get("serviceEndpoint") or item):
        for supported in node.get("supportedTokens") or []:
            value = ((supported or {}).get(token) or {}).get(key)
            if value:
                return str(value)
    return ""


def parse_identities(payload: Any) -> list[YouTubeIdentity]:
    found: list[YouTubeIdentity] = []
    for node in _walk(payload):
        item = node.get("accountItem") or node.get("accountItemRenderer")
        if not isinstance(item, dict):
            continue
        name = _text(item.get("accountName"))
        data_sync_id = _token(item, "datasyncIdToken", "datasyncIdToken")
        if not name or not data_sync_id or any(i.data_sync_id == data_sync_id for i in found):
            continue
        thumbnails = (item.get("accountPhoto") or {}).get("thumbnails") or [{}]
        found.append(
            YouTubeIdentity(
                name=name,
                data_sync_id=data_sync_id,
                handle=_text(item.get("channelHandle")),
                byline=_text(item.get("accountByline")),
                thumbnail=thumbnails[-1].get("url"),
                selected=bool(item.get("isSelected")),
            )
        )
    return found


def same_login(identities: list[YouTubeIdentity], data_sync_id: str) -> list[YouTubeIdentity]:
    """The channels of the Google login that ``data_sync_id`` (the session's) belongs to."""
    if not data_sync_id:
        return identities
    user = YouTubeIdentity("", data_sync_id).google_user
    return [identity for identity in identities if identity.google_user == user]
