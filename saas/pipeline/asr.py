"""Real ASR via faster-whisper, with a safe fallback so the app always boots."""
from __future__ import annotations

import logging

from ..config import get_settings
from ..observability import log_event

_model_cache = {}


def _get_model():
    settings = get_settings()
    key = (settings.asr_model, settings.asr_device)
    if key not in _model_cache:
        from faster_whisper import WhisperModel  # lazy heavy import
        _model_cache[key] = WhisperModel(
            settings.asr_model, device=settings.asr_device, compute_type="int8"
        )
    return _model_cache[key]


def transcribe(path: str) -> list[dict]:
    """Return [{'start','end','text'}] in absolute source seconds."""
    try:
        model = _get_model()
        segments, _info = model.transcribe(path, vad_filter=True)
        return [
            {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
            for s in segments
        ]
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash the worker
        log_event("ASR unavailable; continuing without captions", level=logging.WARNING, error=str(exc))
        return []
