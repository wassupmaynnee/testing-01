"""Frozen engagement-weight assertions — the scoring formula must never drift."""
from __future__ import annotations

from saas.scoring import W_FACE, W_HOOK, W_PACE, W_SENTIMENT, Signals, engagement_score


def test_frozen_weights_exact():
    assert (W_HOOK, W_PACE, W_SENTIMENT, W_FACE) == (0.35, 0.20, 0.25, 0.20)
    assert abs((W_HOOK + W_PACE + W_SENTIMENT + W_FACE) - 1.0) < 1e-9


def test_known_value_all_ones():
    assert engagement_score(Signals(1.0, 1.0, 1.0, 1.0)) == 1.0


def test_known_value_all_zero():
    assert engagement_score(Signals(0.0, 0.0, 0.0, 0.0)) == 0.0


def test_known_value_mixed():
    # 0.35*1 + 0.20*0 + 0.25*0.5 + 0.20*1 = 0.675
    s = Signals(hook=1.0, pace=0.0, sentiment=0.5, face=1.0)
    assert abs(engagement_score(s) - 0.675) < 1e-9


def test_hook_weighted_heaviest():
    # a point of hook must move the score more than a point of any other signal
    base = Signals(0.0, 0.0, 0.0, 0.0)
    hook = engagement_score(Signals(1.0, 0, 0, 0))
    pace = engagement_score(Signals(0, 1.0, 0, 0))
    sent = engagement_score(Signals(0, 0, 1.0, 0))
    face = engagement_score(Signals(0, 0, 0, 1.0))
    assert hook > sent > pace  # 0.35 > 0.25 > 0.20
    assert hook > face and engagement_score(base) == 0.0
