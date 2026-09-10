# Resident OS Technical Architecture

## Purpose

This is the canonical engineering source of truth for Resident OS. It replaces the former AI architecture, platform engineering, architecture diagram notes, coverage audit, rules, and memory templates. It defines the production baseline for a system built from an empty repository.

## Non-negotiable invariants

1. Only the orchestrator can invoke side-effecting tools.
2. No model sits between deterministic P0 detection and human paging.
3. A model never decides whether or when a notification is sent.
4. Every consequential decision passes deterministic validation before execution.
5. Every material generated claim has an evidence identifier or is marked unknown.
6. Every table is tenant-scoped with row-level security; every request sets tenant context.
7. Decisions, model calls, guardrail events, and audit records are append-only.
8. Protected attributes and health inferences are not stored, logged, or used as features.
9. Every mutating API request is idempotent.
10. The critical path contains at most five model calls; independent reads run in parallel.
11. A model may propose a durable memory write but cannot commit it without the defined approval policy.
12. No headline metric ships without a reproducible evaluation run and commit SHA.

## Production topology

```text
Resident, staff, vendor, and owner surfaces
        |
Next.js web application on Vercel
        |
FastAPI API and SSE gateway on Cloud Run
        |
Postgres + pgvector + object storage + Redis
        |
Ops Brain orchestration and background workers on Cloud Run
        |
Narrow internal MCP tools -> PMS, vendor, and notification integrations
```

Vercel hosts the web surface and CDN. Cloud Run hosts the stateless API, worker, orchestration, and provider transport where scaling and isolation matter. Supabase Postgres supplies authentication-compatible data storage, row-level security, and pgvector. Redis supports bounded queues, caching, and rate-limiting. Object storage holds media behind signed URLs. Cloud Run is the deployment baseline; do not maintain competing Fly, DigitalOcean, or self-hosting plans.

## Repository shape

Create code only when its phase calls for it.

```text
apps/web/                 Next.js role surfaces and BFF routes
services/api/             FastAPI, authentication, SSE, public API
services/brain/           typed agents, orchestration, guardrails, retrieval policy
services/worker/          async evaluation, embeddings, rollups, reflection, notifications
services/mcp/             narrow read/write tool servers
packages/ui/              shared visual primitives
packages/shared-types/    generated OpenAPI and SSE types
infra/                    migrations, local compose, seed, deployment configuration
knowledge/                versioned SOP, lease, SLA, policy, and vendor sources
evals/                    golden datasets, suites, CI gate, published reports
docs/                     the three canonical plans and final reference PDF
```

Python is 3.12 with typed public APIs, Ruff, and strict type checks in the brain. TypeScript is strict. API models are defined once in OpenAPI and generate client types; browser components never hand-type API-shaped payloads.

## Domain and data design

The core domain is organisation -> property -> building -> unit, connected to people, roles, tenancies, assets, vendors, tickets, work orders, and media. Every row has `org_id`; tenant scope is set in both API middleware and Postgres RLS.

The AI spine stores `agent_runs`, `agent_steps`, `llm_calls`, `retrievals`, `guardrail_events`, `decisions`, `approvals`, and immutable audit receipts. Knowledge stores documents, chunks, version/effective dates, jurisdiction, source authority, and embeddings. Evaluation stores datasets, runs, prompt versions, failure events, metric rollups, and a human label queue.

Facts use temporal supersession (`valid_to`) rather than destructive overwrite. Policy precedence is deterministic: statute, lease, internal SOP, then vendor contract. Decisions and audit events use database protections against updates and deletes.

## API and event contract

The API is versioned under `/v1`. Mutations require `Idempotency-Key`; reads use cursor pagination on `(created_at, id)`; long-running work returns a run identifier and streams step events over SSE. Errors use RFC 7807 problem details with stable types.

Initial resources are tickets, runs, decisions, approvals, vendors, knowledge search, operations health, and inbound vendor webhooks. Core events are `step.started`, `step.finished`, `retrieval.done`, `guardrail.hit`, `council.opened`, `council.member`, `decision.ready`, and `run.failed`. Schema and event contracts are frozen in phase 0, generated for TypeScript consumers, and changed only through a single complete migration.

## Agent workflow

The nine components are orchestrated by a durable LangGraph state machine but remain plain async functions with typed Pydantic input and output. LangGraph owns state transitions, checkpointing, and human interrupts; domain logic must remain framework-independent.

1. **Orchestrator:** the only component with write-tool credentials; owns state transitions and execution.
2. **Safety Sentinel:** deterministic rules plus a small-model second opinion; either signal triggers escalation.
3. **Intake Normalizer:** turns text, photos, and voice-derived facts into a validated `TicketFacts` record.
4. **Context Broker:** retrieves and budgets evidence without semantic compression of policy text.
5. **Diagnostician:** proposes grounded cause and action with cited claims.
6. **Policy Auditor:** evaluates the proposal against statute, lease, SOP, and operational policy.
7. **Dispatch Planner:** proposes vendor, time, parts, cost, and responsible party; it does not execute.
8. **Communicator:** renders approved resident and vendor copy within templates.
9. **Judge:** scores runs asynchronously; it is not on the critical path.

Deterministic code handles triage routing, confidence calibration, decision gating, idempotency, audit persistence, and execution. The system chooses solo or Council Mode using a deterministic complexity and blast-radius score. Council members receive distinct evidence sets: policy/SOP, unit/asset history, and cost/warranty/vendor facts. Their dissent is preserved; synthesis cannot erase it. High-blast-radius or low-confidence outcomes require human approval or abstain.

## Retrieval, context, and memory

Knowledge is versioned Markdown with typed front matter. Retrieval combines lexical search and pgvector, reciprocal-rank fusion, metadata filtering, optional cross-encoder reranking, parent expansion, and bounded extractive compression. Measure recall before adding agents; retain a reranker only if it produces a measured lift.

The provenance envelope contains bracketed citations with source ID, version, effective date, jurisdiction, authority, and source span. The context broker preserves cited text and places unsupported material in an explicit unknowns section.

There are four memory stores: working checkpoint state, authoritative entity facts in Postgres, episodic retrieval records, and versioned semantic knowledge. Reflection is a controlled lifecycle job, not a fifth authoritative store. Any durable promotion requires human approval or the defined independent-confirmation policy. Never semantically cache a final decision across tickets.

## Guardrails and security

Guardrails run at API ingress, before model input, after model output, before decision, before sending, at tool invocation, and in the gateway. They cover tenant authorisation, rate and size limits, PII detection/redaction, prompt injection, abuse, protected-attribute handling, schema validation, citation verification, numeric sanity, policy compliance, fair housing/ADA, output PII, grant scope, idempotency, cost, and latency.

All untrusted content—resident and vendor messages, uploaded material, OCR, images, search results, database rows, and tool output—is data, never instruction. Security testing includes cross-tenant tests, secret scanning, dependency auditing, media validation, webhook signature verification, and rate-limit verification.

## Notifications and execution

Notification eligibility, urgency tier, quiet hours, channel selection, deduplication, fatigue budget, retry, receipt, and escalation are deterministic state machines. Templates receive only data permitted for their audience. Demo mode blocks outbound transport at the adapter boundary and records a suppressed delivery receipt.

MCP servers expose narrow contracts. Read services expose knowledge, citations, asset state, and policy. The operations service exposes a deliberately small write set such as work-order creation and approved notifications. Write tokens are single-use, scoped, and released only after the orchestrated approval transition.

## Evaluation, reliability, and operations

Tests exist at four levels: pure component/guardrail tests, retrieval and metric tests, labelled end-to-end golden-set tests, and adversarial fair-housing/prompt-injection tests. Golden labels are created by humans before prompt tuning. The judge uses a pinned independent model family and version. CI uses tolerance bands; flaky checks are fixed rather than ignored.

The operations console correlates health, per-agent degradation, typed failures, model/prompt versions, evaluation history, calibration, cost, and drift. Production failures may enter a human label queue, never the golden set directly.

The degradation ladder is: full capability, no council, no model, rules-only, then queue-and-acknowledge. A timeout, citation failure, schema failure, provider failure, or budget breach follows a logged, tested fallback. The service must still acknowledge a ticket safely when external providers are unavailable.

## Deployment and launch baseline

Use development, staging, and production environments with isolated secrets and data. The API maintains a warm minimum instance; workers scale with queue depth; web deploys independently. Deployment requires migration planning, preview validation, a full test/evaluation run, observability checks, and rollback confirmation.

Required alerts are P0-recall regression, groundedness below tolerance, escalation-rate jump, cost anomaly, failed execution receipt, and any fair-housing block that reaches a user. OpenTelemetry traces connect the user request, parallel reads, model calls, guardrails, approval, and execution receipt.
