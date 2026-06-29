"""Generate styled ASS subtitle tracks from ASR segments, then burn them in."""
from __future__ import annotations

from . import ffmpeg

_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clippify,Arial,64,&H00FFFFFF,&H00000000,&H64000000,-1,1,4,2,2,60,60,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def build_ass(segments: list[dict], ass_path: str, clip_start: float) -> None:
    """segments: [{'start','end','text'}] in absolute source time."""
    lines = [_ASS_HEADER]
    for seg in segments:
        start = seg["start"] - clip_start
        end = seg["end"] - clip_start
        if end <= 0:
            continue
        text = str(seg["text"]).strip().replace("\n", " ").replace("{", "(").replace("}", ")")
        if not text:
            continue
        lines.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},Clippify,,0,0,0,,{text}"
        )
    with open(ass_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def burn(src: str, ass_path: str, dst: str) -> None:
    ffmpeg.burn_subtitles(src, ass_path, dst)
