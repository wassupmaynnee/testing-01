"""Guards for the remaining frozen contracts: engagement weights, the SSE stage
labels, and the {ok, data | error} response envelope."""
from __future__ import annotations

import json

from saas import scoring
from saas.responses import deferred, err, ok
from saas.scoring import Signals, engagement_score
from saas.sse import STEP_LABELS


# --------------------------- engagement weights ------------------------------
def test_weights_are_frozen():
    assert scoring.W_HOOK == 0.35
    assert scoring.W_PACE == 0.20
    assert scoring.W_SENTIMENT == 0.25
    assert scoring.W_FACE == 0.20
    assert abs((scoring.W_HOOK + scoring.W_PACE + scoring.W_SENTIMENT + scoring.W_FACE) - 1.0) < 1e-9


def test_engagement_formula():
    assert engagement_score(Signals(1.0, 1.0, 1.0, 1.0)) == 1.0
    assert engagement_score(Signals(0.0, 0.0, 0.0, 0.0)) == 0.0
    # 0.35*1 + 0.20*0.5 + 0.25*0 + 0.20*1 = 0.65
    assert abs(engagement_score(Signals(1.0, 0.5, 0.0, 1.0)) - 0.65) < 1e-9


# ------------------------------- SSE labels ----------------------------------
def test_sse_stage_labels_frozen():
    assert STEP_LABELS == [
        "Queued",
        "Probing media",
        "Transcribing (ASR)",
        "Scoring engagement",
        "Selecting clip boundaries",
        "Rendering (cut · reframe · subtitles)",
        "Complete",
    ]
    assert len(STEP_LABELS) == 7  # stages 0..6


# ------------------------------- envelope ------------------------------------
def _body(resp):
    return json.loads(bytes(resp.body))


def test_ok_envelope():
    resp = ok({"job_id": "abc"})
    assert resp.status_code == 200
    assert _body(resp) == {"ok": True, "data": {"job_id": "abc"}}


def test_err_envelope():
    resp = err("bad_tier", "nope", status_code=400)
    body = _body(resp)
    assert resp.status_code == 400
    assert body["ok"] is False
    assert body["error"]["code"] == "bad_tier"
    assert body["error"]["message"] == "nope"


def test_deferred_envelope():
    resp = deferred("Feature X", "module.py:fn")
    body = _body(resp)
    assert resp.status_code == 501
    assert body["ok"] is False
    assert body["error"]["code"] == "deferred"
    assert body["error"]["feature"] == "Feature X"
