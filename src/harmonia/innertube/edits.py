"""Changes to the account: likes, subscriptions and playlists."""

from __future__ import annotations

from typing import Any

from ..i18n import _
from ..playlist_position import added_set_video_id, move_before_action
from .protocol import (
    InnerTubeError,
)


class EditsMixin:
    """Needs InnerTubeSession's _api_post."""

    def like_song(self, video_id: str, liked: bool = True) -> None:
        self._api_post(
            "like/like" if liked else "like/removelike", {"target": {"videoId": video_id}}
        )

    def like_playlist(self, playlist_id: str, liked: bool = True) -> None:
        self._api_post(
            "like/like" if liked else "like/removelike",
            {"target": {"playlistId": playlist_id.removeprefix("VL")}},
        )

    def subscribe_artist(self, channel_id: str, subscribed: bool = True) -> None:
        endpoint = "subscription/subscribe" if subscribed else "subscription/unsubscribe"
        self._api_post(endpoint, {"channelIds": [channel_id]})

    def create_playlist(
        self, title: str, privacy: str = "PRIVATE", video_ids: list[str] | None = None
    ) -> str:
        title = title.strip()
        if not title:
            raise ValueError(_("O nome da playlist não pode ficar vazio"))
        payload = self._api_post(
            "playlist/create",
            {"title": title, "privacyStatus": privacy, "videoIds": video_ids or None},
        )
        playlist_id = payload.get("playlistId")
        if not playlist_id:
            raise InnerTubeError(_("O YouTube criou a playlist sem retornar o identificador"))
        return str(playlist_id)

    def edit_playlist(self, playlist_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
        return self._api_post(
            "browse/edit_playlist",
            {"playlistId": playlist_id.removeprefix("VL"), "actions": actions},
        )

    def rename_playlist(self, playlist_id: str, title: str) -> None:
        self.edit_playlist(
            playlist_id, [{"action": "ACTION_SET_PLAYLIST_NAME", "playlistName": title.strip()}]
        )

    def delete_playlist(self, playlist_id: str) -> None:
        self._api_post("playlist/delete", {"playlistId": playlist_id.removeprefix("VL")})

    def add_to_playlist(self, playlist_id: str, video_id: str, at_start: bool = False) -> None:
        """Append the track, then move it to the top when ``at_start`` (playlist_position)."""
        payload = self.edit_playlist(
            playlist_id, [{"action": "ACTION_ADD_VIDEO", "addedVideoId": video_id}]
        )
        added = added_set_video_id(payload, video_id) if at_start else None
        if not added:
            return
        first = next(
            (
                track.set_video_id
                for track in self.browse(playlist_id, "playlists", all_pages=False)
                if track.set_video_id and track.set_video_id != added
            ),
            None,
        )
        if first:
            self.edit_playlist(playlist_id, [move_before_action(added, first)])

    def remove_from_playlist(self, playlist_id: str, video_id: str, set_video_id: str) -> None:
        if not set_video_id:
            raise ValueError(
                _("A faixa não contém playlistSetVideoId e não pode ser removida com segurança")
            )
        self.edit_playlist(
            playlist_id,
            [
                {
                    "action": "ACTION_REMOVE_VIDEO",
                    "removedVideoId": video_id,
                    "setVideoId": set_video_id,
                }
            ],
        )
