"""Engagement scoring. The weighting matrix is a FROZEN contract."""
from __future__ import annotations

from dataclasses import dataclass

# FROZEN — do not retune. Must sum to 1.0.
W_HOOK = 0.35
W_PACE = 0.20
W_SENTIMENT = 0.25
W_FACE = 0.20

assert abs((W_HOOK + W_PACE + W_SENTIMENT + W_FACE) - 1.0) < 1e-9, "weights must sum to 1.0"


@dataclass(frozen=True)
class Signals:
    hook: float       # 0..1 strength of the opening line
    pace: float       # 0..1 words-per-second normalized
    sentiment: float  # 0..1 emotional intensity
    face: float       # 0..1 on-screen face presence


def engagement_score(s: Signals) -> float:
    """Engagement = 0.35*hook + 0.20*pace + 0.25*sentiment + 0.20*face."""
    return (
        W_HOOK * s.hook
        + W_PACE * s.pace
        + W_SENTIMENT * s.sentiment
        + W_FACE * s.face
    )
