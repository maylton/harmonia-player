from __future__ import annotations

from dataclasses import dataclass

from .models import StreamInfo
from .video import VideoStreamInfo

# Ignore small duration differences caused by container metadata and encoder padding.
VIDEO_DURATION_TOLERANCE_MS = 2_500


@dataclass(frozen=True, slots=True)
class IndependentVideoPlayback:
    """Video and audio streams resolved from the same video ID."""

    video: VideoStreamInfo
    audio: StreamInfo

    @property
    def duration_ms(self) -> int | None:
        return self.audio.duration_ms or self.video.duration_ms


def is_independent_video_variant(
    *,
    item_kind: str,
    song_duration_ms: int | None,
    video_duration_ms: int | None,
    tolerance_ms: int = VIDEO_DURATION_TOLERANCE_MS,
) -> bool:
    """Return whether switching to video requires a separate timeline."""
    if item_kind == "videos":
        return False
    if not song_duration_ms or not video_duration_ms:
        return False
    return abs(int(video_duration_ms) - int(song_duration_ms)) > max(0, int(tolerance_ms))
