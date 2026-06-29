"""FFmpeg wrappers. Binaries resolved by absolute path (frozen contract)."""
from __future__ import annotations

import json
import subprocess

from ..config import get_settings

# FROZEN render flags for the fast-cut pass.
CUT_FLAGS = ["-preset", "veryfast", "-crf", "23", "-async", "1"]


def _ffmpeg() -> str:
    return get_settings().ffmpeg_bin


def _ffprobe() -> str:
    return get_settings().ffprobe_bin


def _video_codec_args() -> list[str]:
    """nvenc on GPU hosts; libx264 fallback so the demo runs without a GPU."""
    if get_settings().video_codec.lower() == "nvenc":
        return ["-c:v", "h264_nvenc"]
    return ["-c:v", "libx264"]


def probe(path: str) -> dict:
    out = subprocess.run(
        [_ffprobe(), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, check=True,
    )
    info = json.loads(out.stdout)
    vstream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = float(info.get("format", {}).get("duration", 0.0) or 0.0)
    return {
        "duration": duration,
        "width": int(vstream.get("width", 0) or 0),
        "height": int(vstream.get("height", 0) or 0),
    }


def cut(src: str, dst: str, start: float, duration: float) -> None:
    """Single fast-cut pass with the frozen flags."""
    cmd = [
        _ffmpeg(), "-y", "-ss", f"{start:.3f}", "-i", src, "-t", f"{duration:.3f}",
        *_video_codec_args(), *CUT_FLAGS, "-c:a", "aac", dst,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def crop_to_vertical(src: str, dst: str, crop_w: int, crop_h: int, x: int, y: int) -> None:
    """Crop to a 9:16 window centered on the active speaker, then scale to 1080x1920."""
    vf = f"crop={crop_w}:{crop_h}:{x}:{y},scale=1080:1920:flags=lanczos"
    cmd = [
        _ffmpeg(), "-y", "-i", src, "-vf", vf,
        *_video_codec_args(), *CUT_FLAGS, "-c:a", "aac", dst,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def burn_subtitles(src: str, ass_path: str, dst: str) -> None:
    """Burn an ASS subtitle track into the video."""
    escaped = ass_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        _ffmpeg(), "-y", "-i", src, "-vf", f"ass='{escaped}'",
        *_video_codec_args(), *CUT_FLAGS, "-c:a", "copy", dst,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
