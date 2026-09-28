# Resident OS SSE Event Contract

`GET /v1/runs/{run_id}/stream` returns an authenticated, tenant-scoped
`text/event-stream` response. It is the public, safe projection of one run's
workflow trace; it never contains a prompt, model name, raw ticket text,
access instruction, token, or digest.

Requirements: QR-002, FR-701, SR-004, SR-006.

## Transport

Each event uses standard SSE framing. `id`, `event`, and `data` are each one
line and `data` is compact JSON encoded as UTF-8. A blank line ends the event.
The server sends `Cache-Control: no-cache` and `X-Accel-Buffering: no`.

The first event is always `timeline.ready`. It contains every normal workflow
stage as `pending`, including the P0 path, so a client can render the full hollow
timeline before any step result arrives. The server then replays the current
persisted `agent_steps` in sequence order, followed by the run's persisted
`guardrail_events`, and closes the response. This is deliberately a snapshot
stream, not a claim of a durable push broker: clients reconnect or poll while a
run is non-terminal. A future durable outbox may add live delivery without
changing these payloads.

The event identifier is stable for a single replay: `timeline:{run_id}` for
the initial event, `step:{run_id}:{sequence_number}` for persisted steps, and
`guardrail:{run_id}:{guardrail_event_id}` for persisted guardrail receipts.
Clients must treat a repeated identifier as an idempotent state replacement.

## Common fields

Every payload has `run_id` (UUID) and `occurred_at` (RFC 3339 timestamp).
`stage` is one of `safety`, `p0`, `intake`, `context`, `diagnosis`, `dispatch`,
`policy_audit`, or `decision`. A server component without an approved mapping
is emitted as `unknown` rather than exposing its internal name. `status` uses
the corresponding frozen database wire value. Unknown future fields must be
ignored.

## Event payloads

| Event | Required payload | Semantics |
| --- | --- | --- |
| `timeline.ready` | `run_id`, `occurred_at`, `run_status`, `steps` | First event. `steps` is an ordered array of `{sequence, stage, status}` whose status is always `pending`. |
| `step.started` | `run_id`, `occurred_at`, `sequence`, `stage`, `status` | A persisted step is running. |
| `step.finished` | `run_id`, `occurred_at`, `sequence`, `stage`, `status` | A persisted step has completed, been skipped, or is awaiting human approval. |
| `retrieval.done` | `run_id`, `occurred_at`, `sequence`, `document_count`, `citation_count` | Safe retrieval summary; source text and scores are not included. |
| `guardrail.hit` | `run_id`, `occurred_at`, `kind`, `outcome` | A deterministic guardrail receipt. It contains no inspected content. |
| `council.opened` | `run_id`, `occurred_at`, `member_count` | A future council trace opened. |
| `council.member` | `run_id`, `occurred_at`, `member`, `outcome` | A future council member finished. |
| `token` | `run_id`, `occurred_at`, `sequence`, `count` | Optional display-only generated-token progress. It must never carry generated text. |
| `decision.ready` | `run_id`, `occurred_at`, `decision_id`, `mode`, `status` | A safe decision availability signal, not approval or execution authority. |
| `run.failed` | `run_id`, `occurred_at`, `failure_code` | Terminal safe failure code only; no exception message or provider detail. |

`timeline.ready`, `step.started`, `step.finished`, `guardrail.hit`, and
`run.failed` are emitted by the current API implementation. The remaining names
are reserved, documented wire contract values for their audit-backed producers;
they are not synthetic client events.

## Example

```text
id: timeline:2d1e1e1d-9999-4000-8000-000000000001
event: timeline.ready
data: {"run_id":"2d1e1e1d-9999-4000-8000-000000000001","occurred_at":"2026-09-26T14:00:00Z","run_status":"running","steps":[{"sequence":1,"stage":"safety","status":"pending"},{"sequence":2,"stage":"p0","status":"pending"},{"sequence":3,"stage":"intake","status":"pending"},{"sequence":4,"stage":"context","status":"pending"},{"sequence":5,"stage":"diagnosis","status":"pending"},{"sequence":6,"stage":"dispatch","status":"pending"},{"sequence":7,"stage":"policy_audit","status":"pending"},{"sequence":8,"stage":"decision","status":"pending"}]}

id: step:2d1e1e1d-9999-4000-8000-000000000001:1
event: step.finished
data: {"run_id":"2d1e1e1d-9999-4000-8000-000000000001","occurred_at":"2026-09-26T14:00:01Z","sequence":1,"stage":"safety","status":"completed"}

```

## Change control

Event names and required fields are wire contracts. Additive changes require
updates to this document, `docs/openapi.yaml`, generated types, producers, and
consumer tests in the same change. Renaming or repurposing an existing event
is not compatible.
