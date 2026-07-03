"""Background worker. Consumes the Redis job queue and runs the pipeline.

Runs as a daemon thread inside the API process so `docker compose up` boots the
whole walking skeleton with one command. Redis is used purely as the broker.
"""
from __future__ import annotations

import threading

import logging

from .observability import log_event
from .pipeline.orchestrator import SinglePassStrategy
from .sse import dequeue_job

_started = False
_lock = threading.Lock()


def _loop() -> None:
    strategy = SinglePassStrategy()
    log_event("worker started; waiting for jobs")
    while True:
        try:
            job_id = dequeue_job(timeout=5)
            if job_id:
                log_event("worker picked up job", job_id=job_id)
                strategy.run(job_id)
        except Exception as exc:  # noqa: BLE001 — keep the worker alive
            log_event("worker loop error", level=logging.ERROR, error=str(exc))


def start_worker() -> None:
    global _started
    with _lock:
        if _started:
            return
        thread = threading.Thread(target=_loop, name="clippify-worker", daemon=True)
        thread.start()
        _started = True
