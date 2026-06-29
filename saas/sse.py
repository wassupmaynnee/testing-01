"""SSE event bus over Redis pub/sub. Redis is broker/SSE ONLY (never SoR)."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import redis

from .config import get_settings

# FROZEN UI/SSE contract: pipeline stages 0 -> 6.
STEP_LABELS: list[str] = [
    "Queued",                                # 0
    "Probing media",                         # 1
    "Transcribing (ASR)",                    # 2
    "Scoring engagement",                    # 3
    "Selecting clip boundaries",             # 4
    "Rendering (cut · reframe · subtitles)", # 5
    "Complete",                              # 6
]

_redis = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def _channel(job_id: str) -> str:
    return f"clippify:sse:{job_id}"


def _state_key(job_id: str) -> str:
    return f"clippify:state:{job_id}"


def publish(job_id: str, stage: int, progress: float, status: str,
            message: str = "", **extra: Any) -> None:
    """Emit one SSE event and cache it so late subscribers see current state."""
    payload = {
        "stage": stage,
        "label": STEP_LABELS[stage] if 0 <= stage < len(STEP_LABELS) else "",
        "progress": round(progress, 4),
        "status": status,
        "message": message,
        **extra,
    }
    blob = json.dumps(payload)
    _redis.set(_state_key(job_id), blob, ex=3600)
    _redis.publish(_channel(job_id), blob)


def last_state(job_id: str) -> str | None:
    return _redis.get(_state_key(job_id))


def stream(job_id: str) -> Iterator[str]:
    """Yield text/event-stream frames for a job until it reaches stage 6/failed."""
    cached = last_state(job_id)
    if cached:
        yield f"data: {cached}\n\n"

    pubsub = _redis.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(_channel(job_id))
    try:
        while True:
            msg = pubsub.get_message(timeout=15.0)
            if msg is None:
                yield ": keep-alive\n\n"
                continue
            data = msg["data"]
            yield f"data: {data}\n\n"
            try:
                parsed = json.loads(data)
                if parsed.get("status") in ("completed", "failed"):
                    break
            except json.JSONDecodeError:
                pass
    finally:
        pubsub.close()


# --- queue helpers (Redis as broker) ---
JOB_QUEUE = "clippify:jobs"


def enqueue_job(job_id: str) -> None:
    _redis.rpush(JOB_QUEUE, job_id)


def dequeue_job(timeout: int = 5) -> str | None:
    item = _redis.blpop(JOB_QUEUE, timeout=timeout)
    return item[1] if item else None
