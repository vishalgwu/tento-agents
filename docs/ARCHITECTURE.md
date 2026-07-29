# ARCHITECTURE.md

**Project:** Resident OS
**Status:** v1.0 · Owner: Vishal · Last updated: 2026-07-25
**Related:** `PRD.md` (what) · this file (how) · `RULES.md` (invariants) · `PHASES.md` (when) · `DESIGN.md` (look) · `MEMORY.md` (log)

> Change this file **before** changing the code it describes. An architecture doc that trails the code is worse than no doc, because people trust it.

---

## 1. Principles that generate every decision here

**A1 — Reliability compounds multiplicatively.** `p^N`. Ten LLM steps at 95% each is 60% end to end. **Budget: ≤ 5 model calls on the critical path.** Replacing an LLM step with a deterministic one is more reliability per dollar, not less AI.

**A2 — Decompose by blast radius, not job title.** Split components only where at least one of these differs: permission (what irreversible thing can it do), context (what must it see), evaluability (can I write a test for its output alone). If all three match, it is one component.

**A3 — Read in parallel, write single-threaded.** Parallel subagents are safe when they read and return findings; dangerous when they write, because conflicting implicit decisions cannot be merged. Exactly one component holds side-effecting tools: the orchestrator.

**A4 — The model proposes, deterministic code disposes.** Every consequential outcome passes through code that can be unit-tested.

**A5 — Calibrated abstention is a feature.** "I am not sure, here is why, here is what I would need" is a first-class output with its own metrics.

---

## 2. System overview

```
┌────────────────────────────────────────────────────────────────────┐
│  CLIENTS                                                           │
│  Resident (mobile web)   Manager console   Owner dashboard         │
│  Tech (mobile web)       Vendor (signed link, no account)          │
└───────────────────────────┬────────────────────────────────────────┘
                            │ HTTPS · JWT · SSE
┌───────────────────────────▼────────────────────────────────────────┐
│  apps/web — Next.js 15 App Router                                  │
│  Server Components for reads · Route Handlers as BFF               │
│  (browser never holds a service key)                               │
└───────────────────────────┬────────────────────────────────────────┘
                            │ scoped service token
┌───────────────────────────▼────────────────────────────────────────┐
│  services/api — FastAPI                                            │
│  auth · tenancy · rate limit · idempotency · SSE fan-out           │
└──────┬──────────────────────┬───────────────────┬──────────────────┘
       │                      │                   │
┌──────▼─────────┐  ┌─────────▼────────┐  ┌───────▼──────────────────┐
│ services/brain │  │ services/worker  │  │ services/mcp             │
│ agents         │  │ judge, embeds,   │  │ read · act · admin       │
│ graph (LangGraph)│ │ notifications,   │  │                          │
│ context broker │  │ rollups          │  │                          │
│ retrieval      │  └─────────┬────────┘  └──────────────────────────┘
│ memory         │            │
│ guardrails     │            │
│ council, judge │            │
│ gateway policy │            │
└──────┬─────────┘            │
       │                      │
┌──────▼──────────────────────▼──────────────────────────────────────┐
│  DATA                                                              │
│  Supabase Postgres (pgvector, pg_trgm) · Upstash Redis · R2 media  │
└────────────────────────────────────────────────────────────────────┘
       │
┌──────▼─────────────────────────────────────────────────────────────┐
│  MODELS — LiteLLM (self-hosted)                                    │
│  Anthropic (primary) · Google (judge cross-check, fallback)        │
│  Ollama (local / offline / no-vendor mode)                         │
└────────────────────────────────────────────────────────────────────┘
       │
┌──────▼─────────────────────────────────────────────────────────────┐
│  OBSERVABILITY — OpenTelemetry → Langfuse + Arize Phoenix          │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data layer

### 3.1 Ontology

```
orgs
 └── properties           (jurisdiction, timezone)
      └── buildings
           └── units
                ├── tenancies ──── people ──── roles (scoped RBAC)
                ├── assets    (make, model, warranty_expires_on)
                └── tickets
                     ├── ticket_media
                     ├── work_orders ──── vendors ──── vendor_scores
                     └── agent_runs
                          ├── agent_steps
                          │    ├── llm_calls
                          │    └── retrievals
                          ├── guardrail_events
                          └── decisions ──── approvals
```

Knowledge and memory sit alongside: `kb_documents → kb_chunks`, `episodic_memory`, `reflections`. Notifications: `notifications`, `notification_budgets`. Evaluation: `eval_datasets → eval_items`, `eval_runs`.

Full DDL lives in `infra/migrations/`. The complete schema reference is in `docs/schema.md`; the load-bearing decisions are below.

### 3.2 Six schema decisions that matter

**1. `jurisdiction` is an explicit column on `properties`.** Habitability SLAs, notice periods, and source-of-income protections are state and city specific. Making it explicit means the KB filter, the SLA table, and the audit record agree, and a VA/MD/DC portfolio needs no special cases.

**2. Protected attributes have no columns.** There is nowhere in this schema to store race, ethnicity, religion, disability, familial status, national origin, immigration status, sexual orientation, or health condition. Not "we do not populate it" — the columns do not exist. A schema that cannot store a protected attribute cannot leak or infer from one. Legitimate accommodation needs live in a separate access-controlled `accommodations` table that is **never joined into any prompt-building query**.

**3. Facts supersede, they do not overwrite.** A conflicting fact sets `valid_to` on the old row and inserts a new one. This gives temporal validity (the property Zep sells as a graph feature) with two timestamp columns, and it is required for replay.

**4. `decisions` is the product.** Everything else supports it. It holds proposed, final, citations, confidence, mode (auto/approved/overridden/escalated), actor, and override reason. An auditor asking "why was unit 4B charged $180 on March 3" gets a complete chain.

**5. Append-only with a hash chain.** `decisions`, `llm_calls`, and `guardrail_events` reject UPDATE and DELETE via trigger. A nightly job computes `row_hash = sha256(prev_hash || row)`. This converts "we log things" into "we can prove what we logged."

**6. `org_id` on every row, RLS on every table.** RLS is the second line; the API scopes every query explicitly as the first. A single service-role query bypassing RLS is a cross-tenant breach, so CI asserts cross-tenant reads fail on every endpoint.

### 3.3 Indexing

```sql
create index on tickets (org_id, status, sla_due_at);
create index on tickets (unit_id, created_at desc);
create index on kb_chunks using hnsw (embedding halfvec_cosine_ops) with (m=16, ef_construction=64);
create index on kb_chunks using gin (ts);
create index on decisions (org_id, decided_at desc);
```

HNSW over IVFFlat: no training step, no per-query `nprobe` tuning, better query-time recall. `halfvec` halves index memory — watch it, because when the HNSW index stops fitting in RAM, Postgres silently falls back to slow scans and p95 collapses with no code change.

---

## 4. Retrieval layer

```
query
 ├─ expand (rules + acronym/synonym map; no LLM in v1)
 ├─ BM25 / tsvector (GIN)     ──┐
 ├─ dense pgvector (HNSW)     ──┤─▶ RRF fusion, k=60
 ├─ metadata filter (org, property, effective date, doc type, jurisdiction) — POST-fusion
 ├─ cross-encoder rerank (bge-reranker-v2-m3, CPU): top 30 → top 6
 ├─ parent-document expansion (chunk → containing section)
 ├─ extractive compression (sentence selection vs query)
 └─ envelope assembly with provenance IDs
```

**Why hybrid is non-negotiable:** embeddings smear identifiers. `SOP-PLM-04`, `§7.3`, and `Rheem XE50M06ST45U1` are exactly what residents and techs cite, and dense search buries them. Hybrid + RRF typically moves recall@5 from around 0.62 to around 0.84 on identifier-heavy corpora.

**Why filtering is post-fusion:** pre-filtering a selective predicate collapses HNSW recall.

**Deliberately not used:** HyDE (one extra call, modest gain in a small controlled vocabulary), knowledge-graph RAG (our graph is relational), external vector DB (under ~10M vectors Postgres wins on latency, cost, and operational surface — we will have ~200k chunks).

### 4.1 Knowledge base as code

`knowledge/**/*.md` in git, with required front matter:

```yaml
id: SOP-PLM-04
version: 3
effective_from: 2025-01-01
effective_to: null
jurisdiction: [US-VA, US-MD]
authority: internal_sop        # statute | lease | internal_sop | vendor_contract
supersedes: SOP-PLM-03
```

`authority` drives conflict precedence in code: **statute > lease > internal SOP > vendor contract**. A PR editing a policy re-embeds only changed files (content hash) and **runs the eval suite**, so a policy change that breaks retrieval fails CI.

---

## 5. Agent layer

### 5.1 Components

| # | Component | LLM | Model tier | Writes | Primary metric |
|---|---|---|---|---|---|
| 0 | Orchestrator | No | — | **All writes** | workflow completion |
| 1 | Safety Sentinel | rules ∨ small | Haiku | No | **P0 recall** |
| 2 | Intake Normalizer | Yes | Haiku | No | field F1, schema-valid rate |
| 3 | Context Broker | No | — | No | recall@k, budget adherence |
| 4 | Diagnostician | Yes | Sonnet | No | groundedness |
| 5 | Policy Auditor | rules + small | Haiku | No | violation catch rate |
| 6 | Dispatch Planner | Yes | Sonnet | No (proposes) | first-time-fix |
| 7 | Communicator | Yes | Haiku | No | guardrail pass rate |
| 8 | Judge | Yes | Sonnet (other family) | No | agreement with human labels |

Council members are **modes of the Diagnostician**, not standing agents.

### 5.2 Why the splits exist

- **Safety separate from Intake:** identical permissions, wildly different loss functions. Safety needs recall ≈ 0.99 with tolerable false positives; Intake needs balanced field accuracy. One prompt cannot serve both, and they cannot be regression-tested together. *(Implementation note: they may share one model call for cost, but they keep two prompts, two schemas, two eval suites.)*
- **Context Broker is code, not an agent:** the biggest hallucination source is bad context, and letting a model choose its own context is how you lose control of it. Retrieval, ranking, compression, and budgeting are deterministic, testable, cacheable.
- **Diagnostician vs Dispatch Planner:** disjoint context (physical/SOP vs vendor/cost/schedule) and different ground truth. Merged, their failures cannot be attributed.
- **Policy Auditor is the adversary:** it sees the decision output and the policy, deliberately **not** the reasoning chain. A model that reviews its own reasoning agrees with itself far more than the reasoning deserves.
- **Communicator is boxed:** template-bound, no reasoning, and it never receives protected attributes — it cannot leak what it never saw.

### 5.3 Permissions are enforced server-side

```python
AGENT_TOOL_GRANTS = {
  "safety_sentinel": [], "intake": [], "diagnostician": [], "communicator": [], "judge": [],
  "context_broker":   ["kb.search", "history.search", "asset.get", "memory.read"],
  "policy_auditor":   ["policy.get"],
  "dispatch_planner": ["vendor.availability", "vendor.scorecard"],
  "orchestrator":     ["workorder.create", "workorder.update", "notify.send",
                       "vendor.dispatch", "memory.propose", "audit.write"],
}
```

A prompt saying "you may only read" is a suggestion. This map is a control.

### 5.4 The graph

```
INGEST(code) → INPUT GUARDRAILS(code) → SAFETY SENTINEL
   ├─ emergency → P0 PROTOCOL(code, no LLM) → page on-call
   └─ normal → INTAKE → CONTEXT BROKER(code) → TRIAGE ROUTER(code)
        ├─ solo    → DIAGNOSTICIAN
        └─ council → [POLICY ∥ HISTORY ∥ COST] → SYNTHESIS
      → DISPATCH PLANNER → POLICY AUDITOR → DECISION GATE(code)
        ├─ auto → EXECUTE
        ├─ approve → interrupt() → approval queue → EXECUTE
        └─ escalate → human queue
      → COMMUNICATOR → OUTPUT GUARDRAILS(code) → SEND + AUDIT
      → JUDGE (async)
```

Critical path: **3 LLM calls solo, 5 with council.** Two paths contain no model at all: the P0 protocol and the decision gate.

### 5.5 Council Mode

Council members differ by **evidence**, not persona, because three samples of the same model over the same context produce correlated errors — they agree confidently and wrongly, manufacturing confidence exactly where the system is weakest.

| Member | Sees | Blind to |
|---|---|---|
| Policy | SOPs, lease, statutory SLA, community rules | unit history, cost |
| History | this unit's + asset's + similar-symptom tickets, resolutions, reopens | SOPs, cost |
| Cost/Asset | asset record, warranty, vendor scorecards, parts, cost distribution | SOPs, narrative history |

**Trigger:** deterministic score ≥ 0.50 (cost, irreversibility, legal sensitivity, low intake confidence, reopen count, novelty, priority). Target fire rate 8–12%.

**Reviewer is deterministic:** every claim has a resolvable citation ID; no numeric appears that is not in a retrieved chunk or structured field; schema valid; priority within category range; ≥2-level disagreement or party disagreement forces human.

**Confidence is blended and calibrated:**
`0.30 retrieval_support + 0.25 member_agreement + 0.20 self_report + 0.15 historical_accuracy + 0.10 schema_cleanliness`, then mapped through an isotonic fit on golden-set deciles. Reliability diagram published.

**We measure council lift over solo and cut Council if it is not positive.**

### 5.6 Context engineering

8,000-token envelope for the Diagnostician:

| Slot | Budget | Overflow |
|---|---|---|
| System + schema (static, **prompt-cached**) | 1,000 | never truncated |
| Policy / SOP excerpts | 1,600 | drop lowest RRF; **never summarize policy text** |
| Unit / asset structured facts | 700 | compact key-value, never JSON dumps |
| Similar resolved cases (k=3) | 1,300 | k→2→1 |
| Conversation summary | 500 | rolling, regenerated every 6 turns |
| Current ticket + captions | 600 | never truncated |
| Output reserve | 2,300 | hard reserve |

**The provenance envelope** is the highest-leverage anti-hallucination technique here. Every item enters with an ID (`[C1]`, `[F1]`). The model must cite an ID for every factual claim or move it to `unknowns`. A deterministic verifier then checks that cited IDs exist, that any sentence with a number/date/dollar/policy reference carries one, and that cited figures appear verbatim in the referenced chunk. One targeted regeneration, then a human.

Context is filtered by the **ticket's timestamp**, not `now()`. This is what makes replay legally meaningful.

### 5.7 Memory

| Store | Backing | TTL | Write policy |
|---|---|---|---|
| Working | LangGraph checkpoint (Postgres) | run + 30d | automatic |
| Entity (structured) | Postgres tables | permanent, versioned | authoritative only, with source |
| Episodic | pgvector | 3y, decayed | on ticket close |
| Semantic | KB in git | effective-dated | via PR |
| Reflection | Postgres + pgvector | 1y, re-validated | **proposed → human-approved → promoted** |

**Memory writes are proposals.** An agent that writes freely to its own memory will eventually write something wrong, retrieve it as fact, and reinforce it. Approval-gated promotion is cheap insurance against memory poisoning.

Retrieval ranking: `relevance × recency_decay(180d) × scope_weight(unit 1.0 > building 0.8 > property 0.6 > org 0.3) × confirmation_count^0.3 × (0 if contradicted)`.

**Mem0 / Zep / LangMem evaluated and not adopted for v1.** Those products solve fuzzy recall across open-ended conversation. Our durable facts are structured, authoritative, and legally consequential — a warranty date must be exactly right, and a summarizer that mangles it is a defect. A `MemoryProvider` interface keeps a Mem0 adapter one flag away if resident-facing conversational memory becomes a major surface.

---

## 6. Guardrails

| Stage | Guardrails |
|---|---|
| API edge | auth/tenant scope · rate + size limits |
| Pre-LLM | PII detect + redact (Presidio + regex) · injection scan on **all** untrusted text · toxicity · protected-attribute scrub |
| Post-LLM | schema validation · citation verification · numeric/unit sanity |
| Post-decision | policy compliance (rules + Policy Auditor) — never overrideable by a model |
| Pre-send | fair-housing / ADA screen · output PII leak check |
| Pre-tool | server-side grant map · single-use approval token |
| Gateway | per-org cost circuit breaker |
| Pre-write | idempotency key |

**Injection defense is architectural first.** Vendor SMS replies, OCR'd documents, and image captions all enter the same context window as resident text. Untrusted content never reaches an agent holding write tools, because only the orchestrator has them and it does not take instructions from context. The scanner is the second line.

**Fair housing is a CI job, not a prompt.** The red-team suite contains paired probes identical except for a protected-class signal (voucher holder, wheelchair access, service animal, family with children, non-English name) and asserts response **parity**: same latency class, same information completeness, same tone. This is exactly the test a fair-housing testing organization would run against us.

---

## 7. Model gateway

Two layers, deliberately separated:

**Policy layer (our code, ~400 lines):** model routing by task class, context budget selection, retrieval strategy, cache decision, per-org cost budget and circuit breaker, prompt version pinning, A/B assignment, guardrail ordering. This is the product.

**Transport layer (LiteLLM, self-hosted):** provider abstraction, fallback, retries, virtual keys, spend logging, OTEL export. This is commodity — buy it, do not build it.

| Tier | Model | Used for |
|---|---|---|
| Small | Claude Haiku 4.5 (~$1/$5 per M) | safety, intake, comms, policy audit |
| Mid | Claude Sonnet 5 (~$3/$15, intro $2/$10 through Aug 31 2026) | diagnosis, dispatch, council, judge |
| Large | Claude Opus 4.8 (~$5/$25) | escalated review only, <1% of calls |
| Local | Llama/Qwen via Ollama | offline dev, no-vendor mode, outage fallback |

Cost levers in order: prompt caching (~90% off cached input) > model routing (5× spread) > batch API (50%, non-interactive) > output-length discipline (output is 5× input) > context trimming.

**Blended cost: ~$0.023/ticket. ~$73 per 500-unit property per year.**

Judge runs on a different model family than generation where possible, to avoid self-preference bias.

---

## 8. API layer

FastAPI, `/api/v1`, OpenAPI-generated, RFC 7807 errors.

```
POST   /v1/tickets                       idempotency-key required
GET    /v1/tickets/{id}/stream           SSE: step events, token stream
GET    /v1/approvals?assignee=me
POST   /v1/approvals/{id}/approve|reject|reassign
GET    /v1/runs/{id}                     full trace
GET    /v1/runs/{id}/replay              re-execute against pinned versions, diff
GET    /v1/decisions/export              signed audit bundle
GET    /v1/knowledge/search?q=           hybrid search with scores
GET    /v1/metrics/agents|cost
POST   /v1/webhooks/vendor|pms           untrusted → quarantine
```

Conventions: idempotency keys on every mutating endpoint (agentic systems retry; without them, retries become duplicate real-world actions) · SSE not WebSockets (one-directional, proxy-friendly, trivially reconnectable) · cursor pagination on `(created_at, id)` · everything long-running returns `202` with a run id.

---

## 9. Frontend architecture

**Next.js 15 App Router · TypeScript · Tailwind · shadcn/ui · TanStack Query · Zustand for UI state only.**

- Server Components for reads; Route Handlers act as a BFF holding the session, so the browser never sees a service key.
- SSE feeds an event reducer. **Render the steps, not just the answer** — watching "retrieving policy… 6 sources… council triggered… auditing…" is the most persuasive eight seconds in the product.
- Optimistic approve/reject with rollback.
- Types are **generated** from OpenAPI into `packages/shared-types`. Never hand-written.

**Four shells:** `/app` (resident, mobile-first) · `/manage` (manager, dense, keyboard-first) · `/owner` (read-only reporting) · `/v/[token]` (vendor, no auth).

**Demo surfaces** (all read from real seeded data — never mock numbers): trace viewer · retrieval inspector · council view · context budget · cost dashboard · agent health · eval dashboard · governance/audit.

---

## 10. Infrastructure and deployment

```
Vercel (Next.js, edge CDN)
   │
Fly.io private network
   ├── api      2 × shared-cpu-1x/256MB
   ├── worker   1 × 512MB
   ├── litellm  1 × 256MB
   ├── mcp      1 × 256MB
   └── langfuse + phoenix  1 × 1GB
   │
Supabase Postgres (pgvector) · Upstash Redis · Cloudflare R2
```

| Component | Free limit | Breaks at | Escape |
|---|---|---|---|
| Vercel Hobby | 100GB bandwidth | ~50k demo visits | Pro $20 |
| Fly.io | ~3 shared machines | ~30 rps | ~$5/machine |
| Supabase Free | 500MB, **pauses after 7 idle days** | ~150k tickets or one quiet week | **Pro $25 — pay this before any demo** |
| Upstash | 10k cmd/day | ~1k tickets/day | cents |
| R2 | 10GB + free egress | thousands of photos | $0.015/GB |
| GH Actions | 2,000 min/mo | evals are minute-hungry | PR subset, nightly full |

**Realistic total: $0–25/month.**

**Environments:** `local` (docker-compose: postgres+pgvector, redis, litellm, langfuse, ollama — full stack offline, one command) → `preview` (per-PR Vercel + staging API + seeded DB branch) → `production`.

**`DEMO_MODE=true`** seeds a synthetic property, **blocks all outbound channels absolutely**, and pins temperature and seeds so the demo behaves identically at 9am and midnight.

**CI/CD:** lint → types → unit → integration (ephemeral Postgres) → **eval gate** (blocks merge; tolerance bands, pinned judge, seeded sample) → preview deploy → canary 10% → full → nightly full eval with auto-rollback of the prompt-version pointer on breach.

**Migrations are expand/contract:** add nullable → backfill → switch reads → drop later. Never a blocking ALTER on a hot table.

---

## 11. Security

| Layer | Control |
|---|---|
| AuthN | Supabase Auth. Residents: magic link + optional passkey. Staff: password + mandatory TOTP. Vendors: **no account**, HMAC-signed single-use TTL links. |
| AuthZ | RBAC (`owner/manager/staff/tech/resident/vendor`) × scope (`org/property/building/unit`), in an API dependency **and** RLS. |
| Tenancy | `org_id` everywhere; JWT claim; RLS; CI cross-tenant tests per endpoint. |
| Secrets | Fly/Vercel env only. `gitleaks` in pre-commit and CI. |
| PII | Redacted before prompt assembly. Media in a private bucket, signed URLs 5 min. Audio deleted post-transcription. |
| Transport | HTTPS, HSTS, strict CSP, HMAC-signed webhooks with timestamp + replay window. |
| Audit | Append-only + nightly hash chain. |
| Providers | Zero-retention settings where offered; `docs/DATA_FLOW.md` documents everything leaving the boundary; Ollama path for orgs refusing third-party inference. |

**Top three threats:** cross-tenant leakage (most likely — a single unscoped query) · indirect prompt injection via vendor/document content (mitigated architecturally) · discriminatory output at scale (mitigated by output guardrails + CI parity suite + immutable message log).

---

## 12. Observability

**OpenTelemetry → Langfuse (traces, prompt versions, cost) + Arize Phoenix (retrieval and embedding drift).** OTEL-first so no vendor is load-bearing.

One trace per ticket, spans nested: input guardrails → safety/intake → context broker (retrieval, memory, budget) → council (3 parallel members + synthesis) → dispatch → policy audit → decision gate → communicator → output guardrails → judge (async).

**Alerts that matter:** P0 recall drop on the shadow set · groundedness 24h rolling below threshold · escalation rate ±50% WoW (a *drop* means overconfidence) · cost/ticket > 2× baseline · any fair-housing block reaching a human · queue depth p95 · provider fallback rate.

---

## 13. Evaluation

| Layer | Tool | Runs | Gates |
|---|---|---|---|
| Unit (agents, guardrails as pure functions) | pytest | every commit | yes |
| Component (recall@k, MRR, nDCG, classifier metrics) | Ragas + custom | every commit | yes |
| End-to-end (200-item golden set) | DeepEval + custom | every PR + nightly | **yes** |
| Adversarial (fair housing, injection, PII, jailbreak) | Promptfoo | every PR | **hard fail** |

**Golden set composition** — deliberately skewed toward hard cases: 40 routine · 35 ambiguous priority · 30 chargeback-disputable · 20 life-safety true positives · 20 life-safety near-misses · 20 recurring/reopened · 15 multilingual/voice · 10 adversarial · 10 missing-information (correct answer = ask).

**Gate with tolerance bands, not exact thresholds**, plus a pinned judge model and a stable seeded sample — otherwise nondeterminism makes CI flaky and a flaky gate gets ignored.

**Judge caveats:** LLM-judge agreement with humans sits around 85–92%. The judge is a regression detector; the human-labeled set is the anchor. Pin the judge version; a judge upgrade is a dataset migration with a full re-baseline.

---

## 14. Reliability and degradation

Timeouts on every external call · exponential backoff with jitter, max 2 retries · circuit breaker per provider (open after 5 failures/30s, half-open after 60s) · bulkheads so council fan-out cannot starve intake · hard step cap of 12 nodes.

**Degradation ladder:** full → no-council → no-LLM-diagnosis → **rules-only** (keyword safety screen + category-default SLA + acknowledgment) → queue-and-acknowledge. The building keeps running when a model provider does not. Rules-only mode is ~150 lines and ships in Phase 3.

---

## 15. Scaling path

| Scale | Breaks first | Fix |
|---|---|---|
| 1k units | Supabase free storage, CI minutes | Supabase Pro; PR-subset evals |
| 10k | Postgres connections from async workers; embedding backlog | Supavisor transaction pooling; Batch API embeddings; read replica for dashboards |
| 100k | HNSW index memory; single-node write throughput | Partition `kb_chunks`/`episodic_memory` by `org_id`; binary quantization; real broker; ClickHouse for `llm_calls` rollups |
| 1M | Single write node; cross-region latency; eval cost | Shard by `org_id` (clean — no cross-org joins exist by design); regional API + inference; Temporal for multi-day suspension; 1% online judge sampling |

**What never changes at scale:** agent contracts, guardrail functions, eval harness, decision record. That is the payoff for decomposing by blast radius.

---

## 16. Rejected alternatives (so we do not relitigate)

| Rejected | Why |
|---|---|
| CrewAI as primary orchestrator | Faster to demo, weaker mid-run recovery. Used for one offline report workflow so the comparison is empirical. |
| AutoGen | Maintenance mode; Microsoft points to Agent Framework. Starting fresh here is a liability. |
| Building our own gateway | Six weeks of proxy code that is not our differentiator. |
| Pinecone / Qdrant / Weaviate | Under ~10M vectors Postgres wins on latency, cost, and one fewer system. |
| Neo4j / graph RAG | Our graph is relational with clean foreign keys. |
| Mem0 / Zep / LangMem for v1 | Our durable facts are structured and authoritative; `valid_from`/`valid_to` gives us temporal validity. |
| Node/TypeScript backend | The AI ecosystem we need is Python-first; Pydantic doubling as agent contract, HTTP schema, and generated TS types is a real win. |
| Serverless for the brain | Runs are 5–20s with parallel fan-out; we want a warm reranker and pooled connections. |
| WebSockets | SSE is sufficient, simpler, and proxy-friendly. |
