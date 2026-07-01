"""Feature B: YouTube URL validation gate (pure, no yt-dlp import)."""
from __future__ import annotations

from saas.pipeline.ingest_url import is_youtube_url


def test_accepts_common_youtube_shapes():
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert is_youtube_url("https://youtube.com/shorts/abc123")
    assert is_youtube_url("http://m.youtube.com/watch?v=abc123")


def test_rejects_non_youtube():
    assert not is_youtube_url("")
    assert not is_youtube_url("https://example.com/watch?v=x")
    assert not is_youtube_url("not a url")
    assert not is_youtube_url("https://vimeo.com/12345")
