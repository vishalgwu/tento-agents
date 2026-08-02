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

### 5.8 Dynamic tool output compression

Retrieval results are compressed (§5.6). **Tool results need the same treatment and are easy to forget**, because they look small in a unit test and are enormous in production. `vendor.availability` across 8 vendors × 14 days, `history.search` returning 40 tickets, or a PMS sync payload each run to tens of thousands of tokens — and they land in the context of the agent that most needs to reason carefully.

Four techniques, applied in order at the tool boundary, all deterministic:

**1. Schema projection.** Every tool declares the fields its callers actually need.

```python
@tool(projection=["vendor_id", "slot_start", "slot_end", "rate_tier"])
async def vendor_availability(trade: str, window: DateRange) -> list[Slot]: ...
```

The raw record has 22 fields; the Dispatch Planner needs 4. Project where the data leaves the tool, never in the prompt template.

**2. Per-tool token budget with ranked truncation.** Each tool has a ceiling. Over it, rank by relevance to the current ticket, truncate, and **emit an explicit marker**:

```
[tool: vendor.availability] truncated — showing 18 of 61 slots, ranked by
proximity to the requested window. Ask for expansion if none fit.
```

Silent truncation is worse than no truncation: it makes the model confidently wrong about coverage. The marker is non-negotiable.

**3. Structured folding.** Repetitive rows collapse to a summary plus outliers — `18 slots available Mon–Wed; earliest 24 Jul 08:00; 3 flagged premium rate` — computed in code, reversible from the stored raw result.

**4. Reference handles.** Large results are persisted and passed as `tool_result:9f2c#3` with a digest. The agent can request expansion of one section. **The full payload is always stored for the audit trail even when the model saw only the digest** — the audit record must reflect what was available, not just what was shown.

**The safety rule:** compression is deterministic for anything authoritative. Never fold a lease clause, warranty date, dollar amount, or policy excerpt through a model — the same rule that governs retrieval in §5.6. Only non-authoritative, repetitive output gets folded.

Measured on our workload: typical dispatch-run tool payload drops from ~4,800 to ~900 tokens. That is roughly 18% off blended cost per ticket and it removes the largest single cause of context-budget overflow.

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

### 6.1 ShieldProvider — pluggable managed screening

Guardrails 3, 4, 5, and 15 (PII, injection, toxicity, output leak) run behind an interface so a managed classifier can augment the local implementation without becoming a dependency.

```python
class ShieldProvider(Protocol):
    async def scan_input(self, text: str, trust: TrustLevel) -> ShieldVerdict: ...
    async def scan_output(self, text: str, audience: Audience) -> ShieldVerdict: ...

LocalShield()        # Presidio + pattern set + our fair-housing classifier — ALWAYS on
ModelArmorShield()   # Google Cloud, enabled when deployed on Cloud Run
BedrockGuardrails()  # documented, not built
```

**Model Armor** (Google Cloud) provides injection and jailbreak detection, sensitive-data protection via Google's DLP, malicious-URL detection, and PDF scanning. Free tier of 2M tokens per month per project standalone, then ~$0.10 per million; the injection filter accepts up to 10,000 tokens per call. It fits our threat model directly: vendors send links, residents upload documents, and OCR text enters the same context as chat.

**Composition rules — these are the part that matters:**

- `LocalShield` always runs. The system's safety must never depend on a third-party service being reachable.
- Verdicts combine **pessimistically**: any block is a block.
- The remote shield gets a **250ms budget**. On timeout, log `shield_degraded`, proceed on the local verdict, and continue. A security-service outage must not take down maintenance intake — the architectural boundary (untrusted content never reaches a write-capable agent) is still holding.
- Every remote verdict is written to `guardrail_events` with the provider name, so an audit can distinguish "local caught it" from "Model Armor caught it."

**Why an adapter rather than the design:** a classifier is a filter; the architecture is the boundary. If our safety story were "Model Armor screens the input," a false negative would be a breach. Because untrusted content structurally cannot reach an agent holding write tools, a false negative is a logged miss.

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
GET    /v1/ops/health                   verdict + quadrants (admin only)
GET    /v1/ops/agents?window=           scorecard, degradation-ranked
GET    /v1/ops/failures?kind=&status=   typed failure feed
POST   /v1/ops/failures/{id}/triage     {why, fix}
POST   /v1/ops/label-queue              promote a failure or output for labelling
GET    /v1/ops/models                   live registry: cost, latency, quality
GET    /v1/ops/prompts                  versions, hashes, traffic split
POST   /v1/ops/prompts/{key}/rollback   config flip, no redeploy
GET    /v1/ops/drift?signal=            online-vs-offline, judge, embedding, retrieval
GET    /v1/ops/outputs?filter=          output inspector
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

**Primary target: Google Cloud Run.** Everything is containerized, so the deployment target is a configuration choice, not an architecture choice.

```
Vercel (Next.js, edge CDN)
   │
Google Cloud Run (one project, internal ingress between services)
   ├── api       min-instances=1, max=10, 2 vCPU / 1GB, timeout 300s
   ├── worker    Cloud Run Job, scheduled + queue-triggered, scale to zero
   ├── litellm   min-instances=0, max=5
   ├── mcp       min-instances=0, internal ingress only
   └── langfuse + phoenix   min-instances=0
   │
Supabase Postgres (pgvector) · Upstash Redis · Cloudflare R2 · Model Armor
```

**Why Cloud Run, and why this changed.** The earlier revision of this document specified Fly.io on the basis of a free tier that no longer exists — Fly now requires a card and offers no free allowance to new users. Cloud Run wins on three independent axes:

| | Cloud Run | Fly.io (2026) |
|---|---|---|
| Free tier | Genuine monthly request-based allowance, scales to zero | None for new accounts |
| Workload fit | Service timeout 300s default / 60 min max — an agent run is 5–20s. Cloud Run Jobs cover the worker (max 7 days/task) | Fine, but paid |
| Hiring signal | GCP appears in far more job descriptions | Niche |

**The cold-start trade, stated explicitly.** Scaling to zero costs 1–3 seconds on the first request, which is exactly the request a recruiter makes when they open the demo link. So: `min-instances=1` on the **API service only** — the hot path stays warm — while worker, MCP, and observability scale to zero freely. That is a deliberate few-dollars-for-latency trade, and being able to explain which service got the warm instance and why is a better answer than either extreme.

The reranker model stays loaded in-process on the API service. This is the specific reason the brain is not serverless-per-request: a per-request model load would dominate the retrieval latency budget.

**Fly.io remains documented as the alternative** if multi-region placement becomes a requirement.

| Component | Free limit | Breaks at | Escape |
|---|---|---|---|
| Vercel Hobby | 100GB bandwidth | ~50k demo visits | Pro $20 |
| Cloud Run | monthly request + CPU allowance | sustained traffic | pay-per-use, cents at this scale |
| Cloud Run `min-instances=1` | not free | always | ~$5–8/mo — worth it, see above |
| Supabase Free | 500MB, **pauses after 7 idle days** | ~150k tickets or one quiet week | **Pro $25 — pay this before any demo** |
| Upstash | 10k cmd/day | ~1k tickets/day | cents |
| R2 | 10GB + free egress | thousands of photos | $0.015/GB |
| Model Armor | 2M tokens/mo/project | ~40k scans/mo | ~$0.10/M tokens |
| GH Actions | 2,000 min/mo | evals are minute-hungry | PR subset, nightly full |

**Realistic total: $30–40/month** — the honest number now that Fly's free tier is gone. Supabase Pro and one warm Cloud Run instance are the two lines worth paying for, and both buy demo reliability.

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

### 14.1 Latency budget

Latency gets a budget the same way tokens do, because "make it faster" is not an engineering plan.

| Stage | p50 target | How |
|---|---|---|
| Acknowledgment | < 200ms | Enqueue and return. No model call on this path — hard rule (FR-102) |
| Input guardrails | < 120ms | Local classifiers in parallel; remote shield capped at 250ms |
| Retrieval | < 350ms | HNSW + GIN in one round trip; reranker warm in-process; policy blocks cached |
| Safety + intake | < 500ms | Merged into one small-model call |
| Diagnosis | < 2,500ms | Streamed — perceived latency is first-token, not last-token |
| Council (10% of runs) | < 3,000ms | Three members in parallel: 3× calls, ~1.4× wall clock |
| Dispatch + audit | < 1,200ms | Overlapped where independent |
| **Total** | **p50 < 6s · p95 < 20s** | |

**Five techniques, in impact order:**

1. **Stream everything user-visible.** First token is what a human feels. The step timeline renders immediately with pending steps hollow, so structure arrives before content.
2. **Parallelize reads.** Retrieval, memory lookup, and asset fetch are independent — `asyncio.gather`, not sequential awaits. Free, and the most commonly missed win.
3. **Keep expensive local things warm.** The cross-encoder stays in-process; this drives the Cloud Run `min-instances` decision in §10.
4. **Prompt caching cuts time-to-first-token**, not just cost — a cached prefix skips prefill.
5. **Speculative dispatch prep.** While the Diagnostician runs, fetch the Dispatch Planner's *inputs* (vendor availability, scorecards) in parallel against intake's predicted trade. Confirmed → dispatch starts warm; wrong → discard the read. Costs a wasted query, saves ~400ms on the common path.

**Rejected: speculative generation.** Running dispatch planning before diagnosis completes would save roughly a second and burns a model call on a guess. At this cost profile the added failure mode is not worth it.

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
| Model Armor as the primary injection defense | A classifier is a filter, not a boundary. It augments `LocalShield`; it never replaces the architectural rule that untrusted content cannot reach a write-capable agent. |
| Speculative generation (dispatch before diagnosis) | Saves ~1s, burns a model call on a guess, adds a failure mode. Speculative *reads* only. |
| LLM-based tool output summarization | Same rule as policy text — deterministic projection and folding only, because tool results carry authoritative figures. |
| Serverless-per-request for the brain | The cross-encoder must stay warm; per-request model loading would dominate the retrieval latency budget. |
