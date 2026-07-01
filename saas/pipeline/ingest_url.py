"""
YouTube ingestion — the sanctioned downloader named at pipeline/base.py.

yt-dlp is imported lazily so a non-YouTube job never loads it. The source video
is downloaded into the uploads dir keyed by job id, then handed to the existing
pipeline exactly like an uploaded file (no other spine changes).
"""
from __future__ import annotations

import re
from pathlib import Path

from ..config import get_settings

# Accept the common YouTube URL shapes; reject everything else up front so an
# invalid URL fails cleanly instead of inside the downloader.
_YOUTUBE_RE = re.compile(
    r"^(https?://)?(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/|live/|embed/)|youtu\.be/)[\w\-]+",
    re.IGNORECASE,
)


def is_youtube_url(url: str) -> bool:
    return bool(_YOUTUBE_RE.match((url or "").strip()))


def download(url: str, job_id: str) -> str:
    """Download a YouTube video to the uploads dir and return the local path.

    Raises ValueError for an invalid URL, RuntimeError if the download fails.
    """
    if not is_youtube_url(url):
        raise ValueError("Not a valid YouTube URL.")

    settings = get_settings()
    settings.ensure_dirs()
    out_tmpl = str(settings.uploads_dir / f"{job_id}.%(ext)s")

    import yt_dlp  # noqa: PLC0415  (lazy: only on the YouTube ingest path)

    ydl_opts = {
        # Prefer a single progressive mp4 so no remux/merge is needed downstream.
        "format": "best[ext=mp4]/mp4/best",
        "outtmpl": out_tmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

    p = Path(path)
    if not p.exists():
        # yt-dlp may have chosen a different container; fall back to the newest
        # file it wrote for this job id.
        matches = sorted(settings.uploads_dir.glob(f"{job_id}.*"), key=lambda f: f.stat().st_mtime)
        if not matches:
            raise RuntimeError("YouTube download produced no file.")
        p = matches[-1]
    return str(p)
