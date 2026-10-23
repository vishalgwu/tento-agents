# Run snapshot events

`GET /v1/runs/{run_id}/stream` is an authenticated, tenant-scoped SSE snapshot of persisted trace rows. It emits `timeline.ready`, `step.started`, `step.finished`, `guardrail.hit`, and `run.failed` as supported by stored events, then closes. Clients reconnect for another snapshot.

The stream never exposes prompts, raw resident text, model names, tokens, or provider exceptions. Stable event IDs support idempotent replacement. Saved ticket jobs have persisted run IDs and support this stream. The separate compatibility endpoint /v1/agent/run is non-persisted; its generated ID does not imply a saved stream.

See `services/api/src/api/routers/stream.py` and `docs/openapi.yaml` for exact payload contracts. Graph steps terminate without external intervention.
