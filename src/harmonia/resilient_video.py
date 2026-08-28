from __future__ import annotations

from .innertube import InnerTubeClient, InnerTubeError
from .models import LibraryItem
from .stream_extractor import InnerTubeStreamExtractor, StreamExtractionError
from .video import VideoStreamInfo, find_video_variant


def resolve_resilient_video_stream(
    client: InnerTubeClient,
    item: LibraryItem,
    *,
    max_height: int = 720,
    force: bool = False,
    allow_video_only: bool = False,
) -> VideoStreamInfo:
    video_id = find_video_variant(client, item, force=force)
    try:
        candidate = InnerTubeStreamExtractor(client).extract_video(
            video_id,
            max_height=max_height,
            progressive_only=not allow_video_only,
            force=force,
        )
    except StreamExtractionError as exc:
        raise InnerTubeError(str(exc)) from exc

    return VideoStreamInfo(
        url=candidate.url,
        video_id=video_id,
        duration_ms=candidate.duration_ms,
        client=candidate.client,
        mime_type=candidate.mime_type,
        bitrate=candidate.bitrate,
        itag=candidate.itag,
        width=candidate.width,
        height=candidate.height,
        fps=candidate.fps,
        muxed=candidate.muxed,
        content_length=candidate.content_length,
        expires_at=candidate.expires_at,
        request_headers=dict(candidate.headers),
    )
