# PHASES.md

**How one developer builds this end to end without stepping into their own bear traps.**
Owner: Vishal (solo) · Last updated: 2026-08-04

---

## 1. The solo-build contract

Solo work fails for three predictable reasons. Each has a mechanic that prevents it.

**Failure 1: interfaces drift as you learn.** You change a column, three files silently disagree, and next week's you loses an afternoon.
→ **Mechanic: Phase 0 freezes every interface before any feature code.** Schema, OpenAPI, SSE events, enums, design tokens, and error catalogue are authored on Day 1–3. After that they only change through the contract-change protocol (§5).

**Failure 2: yak-shaving eats the runway.** Solo builders reroute onto whatever is interesting today; two weeks in they have four half-done things and no shippable slice.
→ **Mechanic: strict phase gating.** Every phase has a DoD checklist and a cut list. If a phase is at risk, you cut from the cut list rather than slipping the gate. `main` is always deployable.

**Failure 3: duplicated definitions drift between backend and frontend.** Backend says `responsible_party`, frontend says `chargedTo`, and nobody notices for two weeks.
→ **Mechanic: shared types are generated, never written.** `packages/shared-types` is produced from the OpenAPI spec by a script. Hand-editing it is a rule violation. Even for a solo dev, generated types are the cheapest way to keep the API and the UI in sync while iterating.

---

## 2. Ownership map

You own everything. The map still exists because it defines the **directory contract** — which folder is authoritative for which concern — and that keeps the code from turning into a bowl of spaghetti when Claude Code refactors it three months from now.

| Path | Authoritative for |
|---|---|
| `services/brain/**` | Agents, prompts, retrieval, memory, guardrails, council, judge, gateway policy |
| `services/api/**` | Routers, deps, request/response schemas |
| `services/worker/**` | Judge, embeddings, rollups, reflection, notifications delivery |
| `services/mcp/**` | Three MCP servers (kb, ops, policy). The only write tools live here. |
| `knowledge/**` | Markdown KB (SOPs, policy, habitability, fair-housing) |
| `evals/**` | Datasets, suites, CI gate, published REPORT.md |
| `infra/migrations/**` | Postgres DDL, RLS |
| `infra/seed/**` | Synthetic data generator |
| `apps/web/**` | All four Next.js role shells |
| `packages/ui/**` | Shared component library |
| `packages/shared-types/**` | **Generated** from `docs/openapi.yaml` — never hand-edit |
| `infra/docker-compose*.yml` | Local dev orchestration |
| `.github/workflows/{ci,evals,deploy}.yml` | CI/CD |
| `docs/openapi.yaml` | API contract — change through §5 |
| `docs/PRD.md`, `ARCHITECTURE.md`, `RULES.md`, `PHASES.md`, `MEMORY.md`, `DESIGN.md` | Source-of-truth spec set; edit *before* the code they describe |

---

## 3. Phase 0 — Contract Freeze

**Duration: 3 days of focused work.**
This is the highest-leverage three days in the project. Everything downstream depends on doing it properly. It is boring, and you will want to skip it. Don't.

### Deliverables — eight frozen artifacts

**1. Schema DDL** (`infra/migrations/0001_init.sql`)
Every table, every column, every enum, RLS policies, indexes. Written completely, even for tables not used until Phase 8. Adding a table later is cheap; changing a column that the whole stack already uses is not.

**2. Enum vocabularies** (`docs/vocabularies.md`)
The exact string values, agreed once:
```
priority:          P0 | P1 | P2 | P3
ticket_status:     new | triaging | awaiting_approval | scheduled | in_progress |
                   awaiting_parts | resolved | closed | cancelled
responsible_party: owner | resident | third_party | undetermined
trade:             plumbing | hvac | electrical | appliance | general | pest |
                   locks | landscaping | cleaning
reject_reason:     wrong_priority | wrong_trade | wrong_party | policy_misread | other
decision_mode:     auto | approved | overridden | escalated
guardrail:         pii | injection | toxicity | protected_attribute | schema |
                   citation | policy | fair_housing | numeric_sanity | tool_auth |
                   idempotency | cost_breaker | output_pii
notification_tier: U0 | U1 | U2 | U3
role:              owner | manager | staff | tech | resident | vendor
```
Trivial-looking, and the single most common source of late-integration pain.

**3. OpenAPI spec** (`docs/openapi.yaml`)
Hand-written **before** any endpoint is implemented. Every path, every request and response schema, every error code. The generated `packages/shared-types` and the API implementation both derive from this file.

**4. SSE event contract** (`docs/events.md`)
```
step.started    {run_id, seq, agent, node, at}
step.finished   {run_id, seq, status, latency_ms, summary}
retrieval.done  {run_id, seq, count, top_sources[{id,title,score}]}
council.opened  {run_id, members[]}
council.member  {run_id, member, priority, confidence}
token           {run_id, text}
decision.ready  {run_id, decision_id, priority, party, confidence, mode}
guardrail.hit   {run_id, guardrail, verdict, stage}
run.failed      {run_id, reason, degraded_mode?}
```
Freeze this before the streaming UI exists. Record a fixture stream so the UI can be built against replayed events while the brain is still stubbed.

**5. Agent contracts** (`services/brain/src/brain/contracts.py`)
`TicketFacts`, `ContextEnvelope`, `Claim`, `Diagnosis`, `DispatchPlan`, `AuditResult`, `MessageDraft`, `JudgeScores`, `TicketState`. Pydantic, strict.

**6. Design tokens + component inventory** (`docs/DESIGN.md` §3, `packages/ui/tokens.ts`)
Colors, type scale, spacing, radii, elevation, motion, plus the list of components each surface needs. The component library can then be built with zero backend.

**7. Seed data spec** (`docs/seed-spec.md`)
1 org, 2 properties, 6 buildings, 400 units, 320 tenancies, 40 assets, 8 vendors, 1,200 historical tickets with realistic distributions, 12 KB documents. Every development activity — UI, brain, evals — runs against the same seed, so a UI bug and a brain bug are never confused.

**8. Error catalogue** (`docs/errors.md`)
Stable `type` URIs, HTTP status, user-facing message, and whether it is retryable.

### Exit criteria

- [ ] All eight artifacts committed to `main`
- [ ] `docker compose up` starts Postgres with the schema applied and seed data loaded
- [ ] Mock API server serves the OpenAPI spec
- [ ] `packages/shared-types` generates cleanly from the spec
- [ ] You can, from memory, name every enum vocabulary and every SSE event

**Do not start Phase 1 until every box is checked.** A day of impatience here costs a week in Phase 5.

---

## 4. The phases

Each phase below lists: goal, deliverables, definition of done, and the cut list — the specific things you drop first if the phase is slipping. Durations assume roughly 25–30 focused hours per week.

---

### Phase 1 — Foundation
**Week 1–2 · Goal: a running system to build inside.**

Deliverables:
- Apply schema; write RLS policies; **cross-tenant test suite** covering every table
- Seed generator producing the full spec dataset
- FastAPI skeleton: auth dependency, tenancy dependency, rate limit, idempotency middleware, RFC 7807 error handler
- Health checks, structured logging, OTEL bootstrap
- Implement 3 read endpoints against the OpenAPI spec
- Next.js app scaffold, four route groups (`/app`, `/manage`, `/owner`, `/v/[token]`)
- Auth flows: magic link (resident), password + TOTP (staff), signed link (vendor)
- `packages/ui`: tokens, primitives (button, input, card, badge, lamp, table, sheet, toast) per `DESIGN.md`
- `docker-compose.dev.yml`; one-command local setup documented in README
- TanStack Query client, generated types wired, mock-server mode

**DoD:** A new machine runs `docker compose up && pnpm dev` and gets a logged-in manager view listing seeded tickets from a real database in under 10 minutes.
**Cut list:** owner and vendor shells (stub routes).

---

### Phase 2 — Knowledge, retrieval, and the shells
**Week 2–3 · Goal: retrieval is measurably good before any agent exists.**

Deliverables:
- Write 12 real KB documents with front matter (SOPs for plumbing/HVAC/electrical/appliance, lease template, community rules, VA + MD habitability SLA tables, emergency procedures, vendor procedures, resident FAQ)
- Ingestion: chunking per corpus type, embeddings, `content_sha256` change detection
- Hybrid retrieval: tsvector + pgvector, RRF fusion, post-fusion metadata filter
- Cross-encoder rerank, parent-document expansion, extractive compression
- **Retrieval eval: 50 hand-written query→document pairs, recall@5 / MRR / nDCG reported**
- Resident ticket submission: text, photo upload, voice capture, sub-1s acknowledgment UX
- Ticket list + detail for all three roles
- Media upload to signed R2 URLs
- Empty states, loading states, error states for every screen

**DoD:** `recall@5` is a committed number in `docs/evals/REPORT.md`, with the dense-only baseline alongside to show the hybrid lift.
**Cut list:** voice capture, knowledge search UI.

> **Why retrieval before agents:** retrieval quality caps everything downstream. If recall@5 is 0.6 you will spend three weeks blaming prompts for a retrieval problem. Doing this first is itself a signal of experience.

---

### Phase 3 — The agent loop
**Week 3–4 · Goal: end-to-end triage, live. 🎯 First demoable build.**

Deliverables:
- Safety Sentinel (rules + small model, OR logic), P0 protocol path with no LLM
- Intake Normalizer with strict schema + repair retry
- Context Broker: envelope assembly, provenance IDs, per-slot token budgeting
- Diagnostician + Dispatch Planner
- LangGraph wiring, Postgres checkpointing, `interrupt()` on approval
- `agent_runs`, `agent_steps`, `llm_calls`, `retrievals`, `decisions` writing on every run
- **Rules-only degradation mode** · tool `projection` + token ceilings on every tool
- Streaming ticket view consuming the SSE contract — step timeline, live status
- Decision card: priority lamp, party, vendor, estimate, confidence meter, evidence rail
- Citation chips: click a claim, highlight its source
- Approval queue sorted by SLA risk, keyboard navigation
- Approve / edit / reassign / reject with the reason taxonomy
- Vendor accept/decline page at `/v/[token]`
- Deploy to Vercel + **Cloud Run**; `min-instances=1` on api only; secrets in Secret Manager

**DoD:** a stranger with the URL submits a ticket, watches reasoning stream, sees a decision with citations, approves it in the manager console, and the audit record exists.
**Cut list:** vendor page, Dispatch Planner (return trade only, no vendor selection).

---

### Phase 4 — Guardrails and approval integrity
**Week 4–5 · Goal: the system cannot do something it should not.**

Deliverables:
- All 15 guardrails, each a separately testable pure function, behind `ShieldProvider` with `LocalShield` as the only implementation
- Policy Auditor (rules + model), source-precedence resolver
- Citation verifier + numeric grounding + targeted regeneration
- Approval tokens: single-use, action-scoped, TTL
- Server-side tool grant enforcement
- Injection corpus + PII test suite
- Guardrail surfacing in the UI: what was blocked, why, what the human must do
- Governance tab v1: decisions by mode, override reasons, guardrail events
- Manager override flow with reason capture and confirmation
- Owner dashboard v1: cost per unit, SLA compliance, recurring-failure units
- Accessibility pass: axe in CI, keyboard traversal of the queue, focus management
- Both themes complete and switching cleanly

**DoD:** the injection corpus passes; a decision that violates lease policy cannot execute; no protected attribute reaches any prompt.
**Cut list:** owner dashboard.

---

### Phase 5 — Evaluation 🎯 **RECRUITER CHECKPOINT**
**Week 5–6 · Goal: the system is measurable, publicly.**

Deliverables:
- **Label the 200-item golden set** (two focused evenings, done before further prompt tuning)
- Eval harness: DeepEval + Ragas + custom metrics
- CI eval gate with tolerance bands, pinned judge, seeded sample
- Red-team fair-housing parity suite (paired probes, hard fail) · `failure_events` + `metric_rollups` + `label_queue` tables, hourly rollup job
- Judge: offline 100%, online 10% sample
- Confidence calibration (isotonic fit), reliability diagram
- `GET /runs/{id}/replay`
- **Publish `docs/evals/REPORT.md` with real numbers, including misses**
- Trace viewer: full run replay, nested step tree, expandable prompts with hashes
- Retrieval inspector: BM25 list, vector list, RRF merge, rerank delta, which chunks entered the window
- Eval dashboard: metric history by commit, pass/fail, **calibration curve**
- **ML Ops console shell** (`/ops`, admin-only) with panels A (verdict), B (agent scorecard), C (failure feed) — cost and eval panels mount **inside** it, not as separate routes
- Landing page with three demo-account buttons and the 90-second story
- README hero: diagram, GIF of the streaming trace, badges

**DoD:** every item in `PRD.md` §9 release criteria is true. **This is the build you put in front of recruiters.**
**Cut list:** nothing. If you are behind, cut from Phase 6 instead.

---

### Phase 6 — Council, memory, and the visualizations
**Week 7–8 · Goal: the depth that carries the technical interview.**

Deliverables:
- Triage router (deterministic council score)
- Council members with disjoint evidence + deterministic reviewer + synthesis
- **Measure council lift vs solo and publish the delta, positive or negative**
- Episodic memory + reflection with approval-gated promotion
- Decay, contradiction handling, supersession
- Full degradation ladder tested by killing keys in staging · `prompt_versions` registry + rollback-by-config-flip
- Council view: three members side by side, agreement matrix, dissent, synthesis
- Context budget visualization: stacked bar of the 8k envelope per run
- Agent health dashboard: success rate, p50/p95, schema repair rate, escalation rate per agent
- Memory review UI: proposed reflections, approve/reject with evidence links
- Mobile polish pass on resident and tech surfaces
- Ops panels D (model registry), E (prompt registry), F (eval history with online/offline calibration overlay)

**DoD:** council lift is a published number. If it is not positive, Council is deleted and that deletion is written up in `MEMORY.md` — **this is a success, not a failure.**
**Cut list:** memory review UI (approve via API), context budget visualization.

---

### Phase 7 — Gateway, MCP, observability
**Week 8–9 · Goal: production posture.**

Deliverables:
- LiteLLM deployment, provider fallback, virtual keys · **Model Armor adapter** behind `ShieldProvider`, 250ms budget, pessimistic combine
- Policy layer: routing table, context budget selection, cache decisions, per-org budgets, circuit breaker
- Caching: prompt prefix, policy block, embeddings, retrieval, tool results · **latency pass against the §14.1 budget**: parallel reads, warm reranker, speculative dispatch prefetch
- Three MCP servers (read / act / admin)
- Langfuse + Phoenix self-hosted, OTEL wiring, alert rules · drift signals wired to rollups
- Gateway dashboard: routing distribution, fallback rate, budget consumption, shield verdicts by provider
- Observability links from every trace into Langfuse/Phoenix
- Conversation replay for multi-turn tickets
- Performance pass: p95 render, bundle size, image optimization
- Ops panels G (drift) and H (output inspector); console complete

**DoD:** killing the primary provider in staging produces a clean fallback with `model_substituted` recorded and forced human approval. Disabling Model Armor produces `shield_degraded` and the request still completes on the local verdict. p50 meets the latency budget.
**Cut list:** admin MCP server, conversation replay.

---

### Phase 8 — Notifications and the community surface
**Week 9–11 · Goal: it becomes a product a builder would buy.**

Deliverables:
- Notification policy engine: tiers, eligibility, quiet hours, dedupe, fatigue budgets, preemption, retry, escalation chain
- Template renderer with slot validation; guardrails on output before send
- Community + marketplace + booking endpoints
- Vendor scorecards feeding dispatch ranking
- Amenity conflict detection
- Notification center, per-tier preferences, quiet-hours settings
- Community: interest groups, threaded posts, moderation and reporting tools
- Rich resident profiles with per-field visibility controls
- Marketplace: listings, categories, photos, resident-to-resident messaging
- Manager-vetted service directory with ratings; amenity booking calendar

**DoD:** the community surface is demoable without narrating the AI, and every user-generated surface has moderation before it is public.
**Cut list:** marketplace messaging, amenity booking.

---

### Phase 9 — Hardening and launch
**Week 11–12 · Goal: it survives contact with strangers.**

Deliverables:
- Load test: 200 concurrent tickets, fix what breaks
- Security pass: cross-tenant suite, secret scan, dependency audit, rate-limit verification
- Final eval run; `REPORT.md` frozen with the launch git SHA
- Three blog posts drafted (council lift, fair-housing CI, memory decision)
- Wellness agent **designed** in `PRD.md` §8.1, not built
- Full responsive and accessibility audit
- Landing page final, demo script, three pre-filled demo prompts
- 3-minute Loom + 90-second silent GIF for the README
- Architecture diagrams exported as SVG
- Public launch: Show HN, LinkedIn, communities

**DoD:** public repo, working demo, published eval report, and 20 outreach messages sent to mid-market operators and CMMS founders asking for feedback rather than selling.

---

## 5. Contract-change protocol

Contracts frozen in Phase 0 **will** need to change. That is fine — the protocol just makes it visible to future-you.

1. Open an issue labeled `contract-change` describing the change and everything it breaks.
2. Make the change in a single PR that also regenerates `packages/shared-types`.
3. Update every downstream consumer in the **same** PR. Never leave a contract half-migrated overnight.
4. Log it in `MEMORY.md` under the current phase.

**Additive changes** (a new optional field, a new endpoint, a new enum value that nothing switches on exhaustively) do not need the protocol. Note them in `MEMORY.md` and move on.

---

## 6. Integration and hygiene protocol

- **Integration checkpoint at the end of each phase:** one 60-minute session walking the DoD list item by item on a preview deploy. Not a demo — a checklist.
- **`main` is always deployable.** If CI is red on `main`, that is the only thing you work on.
- **No side-quests during a phase.** If you discover work that belongs in a later phase, write it into `MEMORY.md` under "carried forward" and keep going. This is the single most common way solo builds die.

---

## 7. Phase completion ritual

At the end of every phase:

1. Walk the DoD checklist on a preview deploy.
2. Run the full eval suite; record the numbers.
3. **Update `MEMORY.md`:** phase status, metrics snapshot, decisions made, things tried that did not work, open items carried forward, contract changes.
4. Tag the repo: `git tag phase-N-complete`.
5. Decide the cut list for the next phase **before** starting it.

Step 3 is the one that gets skipped when you are tired. Do not skip it. It is the only thing that keeps you and Claude Code building the same system three weeks from now.

---

## 8. Schedule at a glance

| Phase | Weeks | Checkpoint |
|---|---|---|
| 0 · Contract Freeze | 1 (3 days) | Eight artifacts frozen |
| 1 · Foundation | 1–2 | One-command local system |
| 2 · Knowledge & Retrieval | 2–3 | recall@5 published |
| 3 · Agent Loop | 3–4 | 🎯 **First demoable build** |
| 4 · Guardrails | 4–5 | Nothing unsafe can execute |
| 5 · Evaluation | 5–6 | 🎯 **RECRUITER CHECKPOINT** |
| 6 · Council & Memory | 7–8 | Council lift published |
| 7 · Gateway & Observability | 8–9 | Clean provider failover |
| 8 · Notifications & Community | 9–11 | Builder-demoable product |
| 9 · Hardening & Launch | 11–12 | Public |

**If a job offer arrives during Phases 6–9, the project has already done its job.** Phases 0–5 are the career-critical block; everything after makes it a company.
