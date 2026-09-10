# Resident OS Delivery Plan

## Purpose

This is the one build sequence for Resident OS, from an empty repository to production. It replaces the former phase plan, file-by-file steps, execution/career plan, rules, coverage audit, and memory template. Work should be performed in order; later phases do not justify speculative scaffolding.

## Operating rules

- Build the measurable Maintenance Loop before any community feature.
- Keep `main` deployable. A red main branch takes priority over new work.
- Change a contract in one change set: source schema, generated types, consumers, fixtures, tests, and docs move together.
- Record durable decisions in the pull request or issue that made them. Do not maintain a separate stale memory document.
- Use synthetic data only until written production data-governance approval exists.
- Never invent a metric, customer, benchmark, or demo outcome. Use `[TBD from eval run]` until measured.
- A feature is complete only when its observability, test, fallback, and documentation are complete.

## Phase sequence

| Phase | Weeks | Goal | Completion gate |
| --- | --- | --- | --- |
| 0. Contract freeze | Days 1-3 | Establish shared contracts and safety boundary | Typed domain vocabulary, API/event contract, initial schema, threat model, and test plan accepted together |
| 1. Foundation | Weeks 1-2 | Run a safe, tenant-isolated skeleton locally | One command starts the stack; seed, migrations, auth, RLS, idempotency, and ticket read/write smoke tests pass |
| 2. Knowledge and retrieval | Weeks 2-3 | Make evidence reliable before agents | Versioned knowledge corpus, hybrid retrieval, retrieval evaluation, and an evidence-viewing surface meet their targets |
| 3. Maintenance vertical slice | Weeks 3-4 | Demonstrate the end-to-end loop | Resident intake, deterministic safety path, typed decision proposal, approval queue, and trace work against seeded data |
| 4. Guardrails and approval integrity | Weeks 4-5 | Make unsafe outcomes hard to ship | Guardrails, policy audit, append-only audit, scoped execution, and fair-housing tests pass |
| 5. Evaluation checkpoint | Weeks 5-6 | Produce measured proof | Golden set, CI gate, public report, calibration, cost/latency, and ML operations console are reproducible |
| 6. Council and controlled memory | Weeks 7-8 | Improve difficult cases without losing control | Evidence-split council, dissent trace, memory approval lifecycle, and measured lift or deletion decision |
| 7. Gateway and observability | Weeks 8-9 | Operate safely under real failure | Model policy layer, budgets, fallbacks, traces, dashboards, alerting, and provider-failure drills |
| 8. Notifications and community | Weeks 9-11 | Add product breadth on the proven spine | Notification policy engine, templates, resident community primitives, and consent/access controls |
| 9. Hardening and launch | Weeks 11-12 | Release a stranger-safe product | Load/security/accessibility review, launch runbook, recorded demo, production deployment, and rollback exercise |

## Phase 0: contracts to create first

Create these artifacts before feature code:

1. A Python dependency manifest with pinned versions. `requirements.txt` is the
   current source of truth; add `pyproject.toml` only when Python package metadata
   or tool configuration requires it, and add web workspace manifests only when the
   web application begins.
2. `.env.example` with no secrets and clear environment ownership.
3. Domain vocabulary: priority, status, trade, responsible party, authority, guardrail, rejection reason, decision mode, notification tier, and failure kind.
4. OpenAPI and SSE event contracts for tickets, runs, decisions, approvals, and errors.
5. Initial Postgres migration covering domain, AI spine, knowledge, evaluation, and RLS foundations.
6. Typed Pydantic contracts for `TicketFacts`, `ContextEnvelope`, `Diagnosis`, `DispatchPlan`, `AuditResult`, `Decision`, `SafetyVerdict`, and `JudgeScores`.
7. A threat model for tenant isolation, prompt injection, PII, tool authority, vendor links, and audit integrity.
8. A test plan that maps the product requirements to unit, integration, evaluation, and release checks.

No route, worker, or component is created until it supports one of these accepted contracts.

## Build order inside the MVP

### Foundation

Create the monorepo layout, local Compose services, migration runner, deterministic synthetic seed, and continuous integration. Add API middleware in this order: request ID, authentication, tenant RLS context, rate limit, idempotency, routing, and error conversion. Test that an organisation-A principal cannot read or mutate organisation-B data on every public route.

### Evidence before generation

Write the initial human-reviewed corpus: plumbing, HVAC, electrical, appliance, emergency, lease, jurisdictional SLA, vendor, and resident communication sources. Add front matter with ID, version, effective date, authority, jurisdiction, and tags. Ship ingestion, chunking, lexical/vector retrieval, reranking measurement, and citation rendering before the diagnostician.

### Vertical slice

Implement ticket intake and acknowledgement; build P0 rules and paging fixtures; then add the typed intake normalizer, context broker, diagnostician, policy audit, dispatch proposal, decision gate, approval interrupt, and trace. Each new model task requires a schema, fixture test, cost/latency budget, failure path, and evaluation metric.

### Measurement before autonomy

Build the labelled golden set from hard cases: ambiguous priorities, life-safety near misses, chargeback disputes, recurring failures, multilingual reports, missing evidence, and justified abstentions. Add a deliberately broken prompt fixture to prove CI fails. Only add Council Mode when the baseline establishes a measured problem it can improve.

## Delivery controls

### Testing

| Layer | Required coverage |
| --- | --- |
| Unit | Domain models, policy precedence, guardrails, cost logic, notification state machine, and deterministic routing |
| Integration | Migrations, RLS, API contracts, idempotency, queues, storage, vendor links, and execution receipts |
| Evaluation | Golden set, retrieval recall, groundedness, priority, trade, chargeback, calibration, and abstention |
| Adversarial | Fair housing, ADA, protected-attribute leakage, prompt injection, harmful tool output, and cross-tenant access |
| Release | Accessibility, performance, dependency audit, secret scan, load test, rollback, and demo-mode transport block |

### Pull requests and releases

Every change states the requirement, security/evaluation impact, migration plan, rollback plan, and documentation change. A dependency addition explains its purpose, maintenance, licence, and what it replaces. Releases require a green CI run, a staging walkthrough, verified alerts/traces, and an explicit production rollback path.

## Production readiness checklist

- All MVP release-gate requirements in `PRODUCT.md` are demonstrably met.
- RLS and authorisation tests pass for every tenant-scoped route and background job.
- No real resident data or secret appears in source, fixtures, logs, screenshots, or demonstrations.
- P0 protocol, notification suppression in demo mode, and provider-failure degradation are tested end to end.
- Evaluation report, model/prompt versions, data version, and commit SHA are published together.
- Accessibility, mobile resident flow, manager keyboard flow, and signed vendor-link flows are validated.
- SLOs, alerts, dashboards, on-call ownership, incident template, backup/restore, and rollback have been rehearsed.

## What not to build early

Do not add payments, screening, rent collection, general lease advice, health profiling, marketplace payments, multi-PMS breadth, an agent framework abstraction, a custom model gateway, a dedicated vector database, or standalone dashboards that duplicate the operations console. Build the evidence-backed maintenance loop first, then extend only when measured outcomes justify it.
