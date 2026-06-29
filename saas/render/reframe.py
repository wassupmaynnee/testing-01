"""YuNet-driven active-speaker tracking + 9:16 vertical reframe."""
from __future__ import annotations

import urllib.request
from pathlib import Path

from ..config import get_settings
from . import ffmpeg

_YUNET_NAME = "face_detection_yunet_2023mar.onnx"


def ensure_yunet_model() -> Path:
    """Download the bundled YuNet ONNX on first use; cache under /models."""
    settings = get_settings()
    settings.ensure_dirs()
    dest = settings.models_dir / _YUNET_NAME
    if not dest.exists():
        urllib.request.urlretrieve(settings.yunet_model_url, dest)  # noqa: S310
    return dest


def _detector(width: int, height: int):
    import cv2  # lazy: heavy native dep
    model = str(ensure_yunet_model())
    return cv2.FaceDetectorYN.create(model, "", (width, height), 0.6, 0.3, 5000)


def _largest_face_center_x(detector, frame) -> float | None:
    _, faces = detector.detect(frame)
    if faces is None or len(faces) == 0:
        return None
    # face row: [x, y, w, h, ...landmarks..., score]; pick widest.
    best = max(faces, key=lambda f: f[2])
    return float(best[0] + best[2] / 2.0)


def face_presence(src: str, start: float, end: float, samples: int = 8) -> float:
    """Fraction of sampled frames containing a face (the 'face' scoring signal)."""
    import cv2
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        return 0.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    det = _detector(w, h)
    hits = 0
    span = max(end - start, 0.1)
    try:
        for i in range(samples):
            t = start + span * (i / max(samples - 1, 1))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                continue
            if _largest_face_center_x(det, frame) is not None:
                hits += 1
    finally:
        cap.release()
    return hits / samples


def _average_face_x(src: str, samples: int = 16) -> tuple[float, int, int]:
    """Smoothed horizontal speaker center across the clip; falls back to center."""
    import cv2
    cap = cv2.VideoCapture(src)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    det = _detector(w, h)
    xs: list[float] = []
    try:
        for i in range(samples):
            pos = int(frames * (i / max(samples - 1, 1))) if frames else 0
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, frame = cap.read()
            if not ok:
                continue
            cx = _largest_face_center_x(det, frame)
            if cx is not None:
                xs.append(cx)
    finally:
        cap.release()
    center = sum(xs) / len(xs) if xs else w / 2.0
    return center, w, h


def reframe_vertical(src: str, dst: str) -> None:
    """Crop a 9:16 window centered on the speaker and scale to 1080x1920 (audio kept)."""
    cx, w, h = _average_face_x(src)
    crop_w = min(w, int(round(h * 9 / 16)))
    crop_h = h
    x = int(round(cx - crop_w / 2))
    x = max(0, min(x, w - crop_w))
    ffmpeg.crop_to_vertical(src, dst, crop_w, crop_h, x, 0)
