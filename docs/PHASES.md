# PHASES.md

**How two developers build this in parallel without stepping on each other, and without a painful integration at the end.**
Owner: Vishal · Last updated: 2026-07-25

---

## 1. The parallelization contract

Parallel work fails for exactly three reasons. Each has a mechanic that prevents it.

**Failure 1: interfaces change mid-build.** One person builds against a shape that the other person alters, and both rework.
→ **Mechanic: Phase 0 freezes every interface before either person writes feature code.** Schema, OpenAPI, SSE events, enums, design tokens, and error catalogue are all authored jointly in the first three days. After that they only change through the contract-change protocol (§5).

**Failure 2: both people edit the same file.** Merge conflicts, lost work, and "who owns this" arguments.
→ **Mechanic: disjoint directory ownership.** Every path in the repo has exactly one owner. You may read anything; you may only edit inside your paths. There is no file that both people edit.

**Failure 3: duplicated definitions drift.** Backend model says `responsible_party`, frontend type says `chargedTo`, and nobody notices for two weeks.
→ **Mechanic: shared types are generated, never written.** `packages/shared-types` is produced from the OpenAPI spec by a script. Hand-editing it is a rule violation.

**Result:** at the end of every phase, the two tracks integrate in under an hour, because they were never actually apart — they were building against the same frozen contract the whole time.

---

## 2. Ownership map

| Path | Owner | Notes |
|---|---|---|
| `services/brain/**` | **A** | agents, prompts, retrieval, memory, guardrails, council, judge, gateway policy |
| `services/api/**` | **A** | routers, deps, schemas |
| `services/worker/**` | **A** | judge, embeddings, rollups |
| `services/mcp/**` | **A** | three MCP servers |
| `knowledge/**` | **A** | markdown KB |
| `evals/**` | **A** | datasets, suites, gate |
| `infra/migrations/**` | **A** | DDL |
| `infra/seed/**` | **A** | synthetic data generator |
| `apps/web/**` | **B** | all four shells |
| `packages/ui/**` | **B** | component library |
| `packages/shared-types/**` | *generated* | **nobody edits by hand** |
| `infra/docker-compose*.yml` | **B** | local dev orchestration |
| `.github/workflows/deploy.yml` | **B** | deployment pipeline |
| `.github/workflows/ci.yml` | **B** | lint/test pipeline |
| `.github/workflows/evals.yml` | **A** | eval gate |
| `docs/openapi.yaml` | **A authors, B reviews** | contract-change protocol applies |
| `DESIGN.md` | **B** | |
| `PRD.md`, `ARCHITECTURE.md`, `RULES.md`, `PHASES.md`, `MEMORY.md` | **both, at sync only** | never edited mid-phase by one person alone |

### 2.1 Track definitions

- **Track A — Brain.** Data, agents, retrieval, evaluation, backend. Recommended: Vishal (this is the portfolio-critical surface and the interview material).
- **Track B — Surface.** Design system, four UI shells, dashboards, local dev ergonomics, CI/CD, deployment.

### 2.2 If you want to split differently

The ownership map is the mechanic; who holds which track is negotiable. Three workable variants:

| Variant | A owns | B owns | Works when |
|---|---|---|---|
| **Brain / Surface** *(recommended)* | brain, api, evals, knowledge, migrations | web, ui, design, CI/CD, deploy | One person is stronger on AI/backend, the other on product/UI |
| **Agent / Data** | agents, prompts, council, judge, guardrails | schema, migrations, api routers, retrieval, seed | Both are backend people. Contract = the `TicketState` model plus the retrieval interface |
| **Vertical slices** | maintenance loop end to end (its API + its UI) | community surface end to end (its API + its UI) | Later phases only. Do **not** use this before Phase 6 — it duplicates infrastructure |

Whichever you pick, write it at the top of `MEMORY.md` and do not change it mid-phase.

---

## 3. Phase 0 — Contract Freeze

**Duration: 3 days. Both developers, working together, in the same room or the same call.**
This is the highest-leverage three days in the project. Everything downstream depends on doing it properly.

### Deliverables — eight frozen artifacts

**1. Schema DDL** (`infra/migrations/0001_init.sql`)
Every table, every column, every enum, RLS policies, indexes. Written completely, even for tables not used until Phase 8. Adding a table later is cheap; changing a column that both tracks already use is not.

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
Hand-written **before** any endpoint is implemented. Every path, every request and response schema, every error code. Track B builds against this from day one using a mock server; Track A implements to it.

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
Track B builds the streaming UI against a recorded fixture of these events before the brain exists.

**5. Agent contracts** (`services/brain/src/brain/contracts.py`)
`TicketFacts`, `ContextEnvelope`, `Claim`, `Diagnosis`, `DispatchPlan`, `AuditResult`, `MessageDraft`, `JudgeScores`, `TicketState`. Pydantic, strict.

**6. Design tokens + component inventory** (`DESIGN.md` §3, `packages/ui/tokens.ts`)
Colors, type scale, spacing, radii, elevation, motion, plus the list of components each surface needs. Track B can build the entire component library with zero backend.

**7. Seed data spec** (`docs/seed-spec.md`)
1 org, 2 properties, 6 buildings, 400 units, 320 tenancies, 40 assets, 8 vendors, 1,200 historical tickets with realistic distributions, 12 KB documents. Both tracks develop against identical data, so a UI bug and a brain bug are never confused.

**8. Error catalogue** (`docs/errors.md`)
Stable `type` URIs, HTTP status, user-facing message, and whether it is retryable.

### Exit criteria

- [ ] All eight artifacts committed to `main`
- [ ] `docker compose up` starts Postgres with the schema applied and seed data loaded
- [ ] Mock API server serves the OpenAPI spec
- [ ] `packages/shared-types` generates cleanly from the spec
- [ ] Both developers can state, without looking, which paths they own

**Do not start Phase 1 until every box is checked.** A day of impatience here costs a week in Phase 5.

---

## 4. The phases

Each phase below lists: goal, the two parallel tracks, what they integrate on, and the definition of done. Durations assume roughly 25–30 focused hours per week per person.

---

### Phase 1 — Foundation
**Week 1–2 · Goal: both tracks have a running system to build inside.**

| Track A — Brain | Track B — Surface |
|---|---|
| Apply schema; write RLS policies; **cross-tenant test suite** covering every table | Next.js app scaffold, four route groups (`/app`, `/manage`, `/owner`, `/v/[token]`) |
| Seed generator producing the full spec dataset | Auth flows: magic link (resident), password + TOTP (staff), signed link (vendor) |
| FastAPI skeleton: auth dependency, tenancy dependency, rate limit, idempotency middleware, RFC 7807 error handler | `packages/ui`: tokens, primitives (button, input, card, badge, lamp, table, sheet, toast) per `DESIGN.md` |
| Health checks, structured logging, OTEL bootstrap | `docker-compose.dev.yml`; one-command local setup documented in README |
| Implement 3 read endpoints against the OpenAPI spec | TanStack Query client, generated types wired, mock-server mode |

**Integrate on:** Track B's app calls Track A's three real endpoints instead of the mock.
**DoD:** A new machine runs `docker compose up && pnpm dev` and gets a logged-in manager view listing seeded tickets from a real database in under 10 minutes.
**Cut if behind:** owner and vendor shells (stub routes).

---

### Phase 2 — Knowledge, retrieval, and the shells
**Week 2–3 · Goal: retrieval is measurably good before any agent exists.**

| Track A — Brain | Track B — Surface |
|---|---|
| Write 12 real KB documents with front matter (SOPs for plumbing/HVAC/electrical/appliance, lease template, community rules, VA + MD habitability SLA tables, emergency procedures, vendor procedures, resident FAQ) | Resident ticket submission: text, photo upload, voice capture, sub-1s acknowledgment UX |
| Ingestion: chunking per corpus type, embeddings, `content_sha256` change detection | Ticket list + detail for all three roles |
| Hybrid retrieval: tsvector + pgvector, RRF fusion, post-fusion metadata filter | Media upload to signed R2 URLs |
| Cross-encoder rerank, parent-document expansion, extractive compression | Empty states, loading states, error states for every screen |
| **Retrieval eval: 50 hand-written query→document pairs, recall@5 / MRR / nDCG reported** | Knowledge search UI (feeds the demo surface later) |

**Integrate on:** `GET /v1/knowledge/search` returning scored results into Track B's search UI.
**DoD:** recall@5 is a committed number in `docs/evals/REPORT.md`, with the dense-only baseline alongside it to show the hybrid lift.
**Cut if behind:** voice capture, knowledge search UI.

> **Why retrieval before agents:** retrieval quality caps everything downstream. If recall@5 is 0.6 you will spend three weeks blaming prompts for a retrieval problem. Doing this first is itself a signal of experience.

---

### Phase 3 — The agent loop
**Week 3–4 · Goal: end-to-end triage, live. 🎯 First demoable build.**

| Track A — Brain | Track B — Surface |
|---|---|
| Safety Sentinel (rules + small model, OR logic), P0 protocol path with no LLM | Streaming ticket view consuming the SSE contract — step timeline, live status |
| Intake Normalizer with strict schema + repair retry | Decision card: priority lamp, party, vendor, estimate, confidence meter, evidence rail |
| Context Broker: envelope assembly, provenance IDs, per-slot token budgeting | Citation chips: click a claim, highlight its source |
| Diagnostician + Dispatch Planner | Approval queue sorted by SLA risk, keyboard navigation |
| LangGraph wiring, Postgres checkpointing, `interrupt()` on approval | Approve / edit / reassign / reject with the reason taxonomy |
| `agent_runs`, `agent_steps`, `llm_calls`, `retrievals`, `decisions` writing on every run | Vendor accept/decline page at `/v/[token]` |
| **Rules-only degradation mode** | Deploy to Vercel + Fly; environment and secret setup |

**Integrate on:** the whole loop. A ticket submitted in the UI produces a streamed decision from the brain.
**DoD:** a stranger with the URL submits a ticket, watches reasoning stream, sees a decision with citations, approves it in the manager console, and the audit record exists.
**Cut if behind:** vendor page, Dispatch Planner (return trade only, no vendor selection).

---

### Phase 4 — Guardrails and approval integrity
**Week 4–5 · Goal: the system cannot do something it should not.**

| Track A — Brain | Track B — Surface |
|---|---|
| All 15 guardrails, each a separately testable pure function | Guardrail surfacing in the UI: what was blocked, why, what the human must do |
| Policy Auditor (rules + model), source-precedence resolver | Governance tab v1: decisions by mode, override reasons, guardrail events |
| Citation verifier + numeric grounding + targeted regeneration | Manager override flow with reason capture and confirmation |
| Approval tokens: single-use, action-scoped, TTL | Owner dashboard v1: cost per unit, SLA compliance, recurring-failure units |
| Server-side tool grant enforcement | Accessibility pass: axe in CI, keyboard traversal of the queue, focus management |
| Injection corpus + PII test suite | Both themes complete and switching cleanly |

**Integrate on:** a deliberately non-compliant decision is blocked by the brain and rendered correctly by the surface.
**DoD:** the injection corpus passes; a decision that violates lease policy cannot execute; no protected attribute reaches any prompt.
**Cut if behind:** owner dashboard.

---

### Phase 5 — Evaluation 🎯 **RECRUITER CHECKPOINT**
**Week 5–6 · Goal: the system is measurable, publicly.**

| Track A — Brain | Track B — Surface |
|---|---|
| **Label the 200-item golden set** (two focused evenings, done before further prompt tuning) | Trace viewer: full run replay, nested step tree, expandable prompts with hashes |
| Eval harness: DeepEval + Ragas + custom metrics | Retrieval inspector: BM25 list, vector list, RRF merge, rerank delta, which chunks entered the window |
| CI eval gate with tolerance bands, pinned judge, seeded sample | Eval dashboard: metric history by commit, pass/fail, **calibration curve** |
| Red-team fair-housing parity suite (paired probes, hard fail) | Cost dashboard: $/ticket, by agent, by model, cache hit rate |
| Judge: offline 100%, online 10% sample | Landing page with three demo-account buttons and the 90-second story |
| Confidence calibration (isotonic fit), reliability diagram | README hero: diagram, GIF of the streaming trace, badges |
| `GET /runs/{id}/replay` | |
| **Publish `docs/evals/REPORT.md` with real numbers, including misses** | |

**Integrate on:** the eval dashboard reads real `eval_runs` rows; the trace viewer replays a real run.
**DoD:** every item in `PRD.md` §9 release criteria is true. **This is the build you put in front of recruiters.**
**Cut if behind:** nothing. If you are behind, cut from Phase 6 instead.

---

### Phase 6 — Council, memory, and the visualizations
**Week 7–8 · Goal: the depth that carries the technical interview.**

| Track A — Brain | Track B — Surface |
|---|---|
| Triage router (deterministic council score) | Council view: three members side by side, agreement matrix, dissent, synthesis |
| Council members with disjoint evidence + deterministic reviewer + synthesis | Context budget visualization: stacked bar of the 8k envelope per run |
| **Measure council lift vs solo and publish the delta, positive or negative** | Agent health dashboard: success rate, p50/p95, schema repair rate, escalation rate per agent |
| Episodic memory + reflection with approval-gated promotion | Memory review UI: proposed reflections, approve/reject with evidence links |
| Decay, contradiction handling, supersession | Mobile polish pass on resident and tech surfaces |
| Full degradation ladder tested by killing keys in staging | |

**Integrate on:** a council run renders correctly in the council view including a genuine disagreement case from the golden set.
**DoD:** council lift is a published number. If it is not positive, Council is deleted and that deletion is written up in `MEMORY.md` — **this is a success, not a failure.**
**Cut if behind:** memory review UI (approve via API), context budget visualization.

---

### Phase 7 — Gateway, MCP, observability
**Week 8–9 · Goal: production posture.**

| Track A — Brain | Track B — Surface |
|---|---|
| LiteLLM deployment, provider fallback, virtual keys | Gateway dashboard: routing distribution, fallback rate, budget consumption |
| Policy layer: routing table, context budget selection, cache decisions, per-org budgets, circuit breaker | Observability links from every trace into Langfuse/Phoenix |
| Caching: prompt prefix, policy block, embeddings, retrieval, tool results | Conversation replay for multi-turn tickets |
| Three MCP servers (read / act / admin) | Performance pass: p95 render, bundle size, image optimization |
| Langfuse + Phoenix self-hosted, OTEL wiring, alert rules | Canary deploy workflow with auto-rollback |

**Integrate on:** a trace in the UI links to the same trace in Langfuse; cost dashboard matches gateway spend logs.
**DoD:** killing the primary provider in staging produces a clean fallback with `model_substituted` recorded and forced human approval.
**Cut if behind:** admin MCP server, conversation replay.

---

### Phase 8 — Notifications and the community surface
**Week 9–11 · Goal: it becomes a product a builder would buy.**

| Track A — Brain | Track B — Surface |
|---|---|
| Notification policy engine: tiers, eligibility, quiet hours, dedupe, fatigue budgets, preemption, retry, escalation chain | Notification center, per-tier preferences, quiet-hours settings |
| Template renderer with slot validation; guardrails on output before send | Community: interest groups, threaded posts, moderation and reporting tools |
| Community + marketplace + booking endpoints | Rich resident profiles with per-field visibility controls |
| Vendor scorecards feeding dispatch ranking | Marketplace: listings, categories, photos, resident-to-resident messaging |
| Amenity conflict detection | Manager-vetted service directory with ratings; amenity booking calendar |

**Integrate on:** a P1 ticket produces a U1 notification that respects quiet hours and appears in the notification center; a fatigue-exhausted U3 is dropped and visible as suppressed.
**DoD:** the community surface is demoable without narrating the AI, and every user-generated surface has moderation before it is public.
**Cut if behind:** marketplace messaging, amenity booking.

---

### Phase 9 — Hardening and launch
**Week 11–12 · Goal: it survives contact with strangers.**

| Track A — Brain | Track B — Surface |
|---|---|
| Load test: 200 concurrent tickets, fix what breaks | Full responsive and accessibility audit |
| Security pass: cross-tenant suite, secret scan, dependency audit, rate-limit verification | Landing page final, demo script, three pre-filled demo prompts |
| Final eval run; `REPORT.md` frozen with the launch git SHA | 3-minute Loom + 90-second silent GIF for the README |
| Three blog posts drafted (council lift, fair-housing CI, memory decision) | Architecture diagrams exported as SVG |
| Wellness agent **designed** in `PRD.md` §8.1, not built | Public launch: Show HN, LinkedIn, communities |

**DoD:** public repo, working demo, published eval report, and 20 outreach messages sent to mid-market operators and CMMS founders asking for feedback rather than selling.

---

## 5. Contract-change protocol

Contracts frozen in Phase 0 **will** need to change. That is fine — the protocol just makes it visible.

1. Open an issue labeled `contract-change` describing the change and everything it breaks.
2. Both developers acknowledge in the issue. **No work starts until both have.**
3. The owner of the artifact makes the change in a single PR that also regenerates `packages/shared-types`.
4. Both tracks update their side in the **same** PR or in two PRs merged the same day. Never leave a contract half-migrated overnight.
5. Log it in `MEMORY.md` under the current phase.

**Additive changes** (a new optional field, a new endpoint, a new enum value that nothing switches on exhaustively) do not need the protocol. Announce them in the daily standup and move on.

---

## 6. Conflict and integration protocol

- **Never edit outside your paths.** If you are blocked on the other track, build against a fixture and open a `contract-change` issue.
- **Integration checkpoint at the end of each phase:** one 60-minute session, both present, walking the DoD list item by item on a preview deploy. Not a demo — a checklist.
- **If integration takes more than 90 minutes, the contract leaked.** Find where, fix the contract, and record it in `MEMORY.md`. That is the whole feedback loop.
- **`main` is always deployable.** If CI is red on `main`, that is the only thing anyone works on.

---

## 7. Phase completion ritual

At the end of every phase, both developers, together, in one sitting:

1. Walk the DoD checklist on a preview deploy.
2. Run the full eval suite; record the numbers.
3. **Update `MEMORY.md`:** phase status, metrics snapshot, decisions made, things tried that did not work, open items carried forward, contract changes.
4. Tag the repo: `git tag phase-N-complete`.
5. Decide the cut list for the next phase **before** starting it.

Step 3 is the one that gets skipped when you are tired. Do not skip it. It is the only thing that keeps two humans and two AI assistants building the same system three weeks from now.

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
