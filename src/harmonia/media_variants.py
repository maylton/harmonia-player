from __future__ import annotations

from dataclasses import dataclass

from .models import StreamInfo
from .video import VideoStreamInfo

# YouTube's reported durations can differ slightly because of encoder padding,
# rounding and container metadata. Treat only a meaningful gap as a different
# timeline that cannot safely inherit the song's current position.
VIDEO_DURATION_TOLERANCE_MS = 2_500


@dataclass(frozen=True, slots=True)
class IndependentVideoPlayback:
    """A visual stream plus audio resolved from the same video ID."""

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
    """Return whether Song -> Video must switch to the video's own timeline.

    A queue item that is already a video is already using that media's audio,
    so selecting Video remains a visual-only operation. For normal songs we
    only declare a distinct timeline when both durations are known and differ
    by more than the small metadata/encoder tolerance above.
    """
    if item_kind == "videos":
        return False
    if not song_duration_ms or not video_duration_ms:
        return False
    return abs(int(video_duration_ms) - int(song_duration_ms)) > max(0, int(tolerance_ms))
