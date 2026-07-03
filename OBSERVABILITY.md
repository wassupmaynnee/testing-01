# Observability

Everything below is self-hosted / OSS — no paid SaaS. Signals are emitted by
`saas/observability.py` (middleware + metrics + logging) and the pipeline hooks.

## Signals & where they live

| Signal | Where | How |
|---|---|---|
| Structured access logs | stdout (JSON) | `RequestContextMiddleware` logs `method, path, status, latency_ms, user_id, request_id` per request. Ship stdout to Loki/CloudWatch/etc. |
| Request tracing | `X-Request-Id` response header | Generated per request (or honored from an inbound `X-Request-Id`), attached to every log line and Sentry event. |
| App/pipeline logs | stdout (JSON) | `log_event(msg, level, **fields)` — replaced every bare `print()`. |
| Errors | Sentry / GlitchTip | Set `SENTRY_DSN`. `before_send=scrub_event` strips cookies, auth headers, request bodies, and redacts emails — no PII leaves the process. |
| Metrics | `GET /metrics` (Prometheus) | Per-route request rate/latency/error-rate (instrumentator) + business counters below. |
| Liveness | `GET /health` | Static 200 while the process is up. |
| Readiness | `GET /ready` | Checks Postgres + Redis (+ R2 when configured); 503 with a per-dependency `checks` map when any is down. Wire Caddy/your LB to gate traffic on this. |
| Frontend telemetry | Sentry (browser) | `web/runtime.js` reports JS errors, failed API envelopes, SSE stream errors, and video playback errors with the same DSN. No third-party PII analytics. |

## Custom metrics (Prometheus names)

- `clippify_clip_jobs_total{outcome="completed|failed"}`
- `clippify_clips_rendered_total`
- `clippify_stage_seconds{stage="0..6"}` — histogram; a stuck ffmpeg/Whisper stage shows as a growing bucket / missing observation.
- `clippify_webhooks_total{result="processed|duplicate|rejected"}`
- `clippify_credit_txns_total{kind="stripe_grant"}`
- plus `http_request_duration_seconds` / `http_requests_total` per handler + status class.

## Request-id trace example

```
$ curl -s -D- http://localhost:8011/api/auth/me | grep -i x-request-id
X-Request-Id: 9f2a1c3b4d5e6f70

# same id appears on the access log line and any Sentry event:
{"ts":"2026-07-03T...","level":"INFO","logger":"clippify","msg":"request",
 "request_id":"9f2a1c3b4d5e6f70","method":"GET","path":"/api/auth/me",
 "status":401,"latency_ms":1.2,"user_id":"-"}
```

Give a user's `X-Request-Id` to support → grep logs / search Sentry by that id → full trace.

## Alert thresholds (what to watch)

| Alert | Threshold | Source |
|---|---|---|
| Elevated error rate | 5xx rate **> 2%** over 5 min | `http_requests_total{status="5xx"}` |
| Latency regression | route **p95 > 1s** (non-render) over 10 min | `http_request_duration_seconds` |
| Stuck pipeline stage | any `clippify_stage_seconds` bucket **> 120s** | per-stage histogram |
| Webhook failures | `clippify_webhooks_total{result="rejected"}` **> 0** | webhook counter |
| Dependency down | `/ready` returns **503** | readiness probe |
| Job failure spike | `clip_jobs_total{outcome="failed"}` rising | job outcome counter |

## Prod config notes

- Logging is INFO in production, DEBUG elsewhere (`APP_ENV`).
- Instrumentator excludes `/metrics`, `/health`, `/ready` from its own metrics; access log skips `/metrics` and `/static/*`.
- Keep `SENTRY_TRACES_SAMPLE_RATE` low (default 0.1) under load.
