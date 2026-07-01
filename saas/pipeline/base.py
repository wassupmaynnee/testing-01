"""Pipeline seams. Deferred features are typed interfaces, not inline stubs."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import IngestKind, Job


class DeferredFeature(NotImplementedError):
    """Raised at a seam whose implementation is deferred to a later pass."""


class IngestSource(ABC):
    """Resolve a Job's source to a local media file path."""

    @abstractmethod
    def prepare(self, job: Job) -> str:
        ...


class UploadSource(IngestSource):
    """LIVE: direct MP4 upload. source_ref is already a local path."""

    def prepare(self, job: Job) -> str:
        return job.source_ref


class YouTubeSource(IngestSource):
    """LIVE: download the YouTube URL via the sanctioned yt-dlp downloader."""

    def prepare(self, job: Job) -> str:
        from .ingest_url import download  # lazy: keeps yt-dlp off non-YT paths
        return download(job.source_ref, job.id)


class TwitchSource(IngestSource):
    """DEFERRED: implement at pipeline/ingest_url.py in a later pass."""

    def prepare(self, job: Job) -> str:
        raise DeferredFeature("Twitch ingest deferred; implement at pipeline/ingest_url.py")


def get_ingest_source(kind: IngestKind) -> IngestSource:
    return {
        IngestKind.upload: UploadSource,
        IngestKind.youtube: YouTubeSource,
        IngestKind.twitch: TwitchSource,
    }[kind]()


class PipelineStrategy(ABC):
    """A strategy that turns one Job into one or more rendered clips."""

    @abstractmethod
    def run(self, job_id: str) -> None:
        ...


class MapReduceStrategy(PipelineStrategy):
    """
    DEFERRED: chunked map-reduce for 1-3 hr sources with block-parallel ASR and
    deterministic checkpoint/resume. Implement at pipeline/mapreduce.py.
    """

    def run(self, job_id: str) -> None:
        raise DeferredFeature(
            "Long-video map-reduce deferred; implement at pipeline/mapreduce.py"
        )
