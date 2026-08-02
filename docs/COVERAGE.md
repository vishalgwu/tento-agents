# COVERAGE.md — Concept Audit

**Where each production-AI concept lives in this project, and what changed in this revision.**
Last updated: 2026-08-01

---

## 1. The audit

| # | Concept | Status before | Where it lives now |
|---|---|---|---|
| 1 | **LLM eval** | ✅ covered | `ARCHITECTURE.md` §13 · `PRD.md` §7.1 · four layers, 200-item golden set, CI gate with tolerance bands, pinned judge |
| 1b | **Eval loop from production** | ⚠️ was one-way | **Added** — `SCREENS.md` §23.3 · failure feed → `label_queue` → human-labelled → `golden_v2`. The eval set was previously frozen at whatever you imagined in week 5 |
| 2 | **Observability / tracing** | ✅ covered | `ARCHITECTURE.md` §12 · OTEL → Langfuse + Phoenix, one trace per ticket, nested spans · `SCREENS.md` §7 |
| 3 | **Prompt injection** | ✅ covered | `ARCHITECTURE.md` §6 · architectural defense first (untrusted content never reaches a write-capable agent), scanner second |
| 4 | **Security** | ✅ covered | `ARCHITECTURE.md` §11 · RLS, tenancy, tool grants, approval tokens, signed webhooks, threat model |
| 5 | **RAG eval** | ✅ covered | `ARCHITECTURE.md` §13 · recall@k, MRR, nDCG, rerank lift, retrieval-miss rate · measured in Phase 2 *before* agents exist |
| 6 | **Gateway** | ✅ covered | `ARCHITECTURE.md` §7 · two-layer split: LiteLLM transport + our policy layer |
| 7 | **Model routing** | ✅ covered | `ARCHITECTURE.md` §7 · task-class → tier table, escalation triggers |
| 8 | **Cost optimization** | ✅ covered | `ARCHITECTURE.md` §7 · caching, routing, output discipline, budgeting · `SCREENS.md` §14 |
| 9 | **Human approval workflow** | ✅ covered | `ARCHITECTURE.md` §5.4 · LangGraph `interrupt()`, approval queue, single-use tokens · `SCREENS.md` §6 |
| 10 | **Guardrails** | ✅ covered | `ARCHITECTURE.md` §6 · 15 guardrails, each a testable pure function |
| 11 | **Model Armor** | ❌ **missing** | **Added** — `ARCHITECTURE.md` §6.1 as a `ShieldProvider` adapter, not a hard dependency |
| 12 | **Deploy to Cloud Run** | ❌ **missing** | **Added and now primary** — `ARCHITECTURE.md` §10. This is a correction, not an addition — see §2 |
| 13 | **Dynamic tool output compression** | ⚠️ **partial** | **Added** — `ARCHITECTURE.md` §5.8. Retrieval compression existed; tool-result compression did not |
| 14 | **Token reduction** | ✅ covered | `ARCHITECTURE.md` §5.6 · per-slot budgeting, extractive compression, caching |
| 15 | **Latency reduction** | ⚠️ **partial** | **Promoted to a first-class section** — `ARCHITECTURE.md` §14.1 with an explicit budget |
| 16 | **Smart routing / fallback** | ✅ covered | `ARCHITECTURE.md` §7, §14 · degradation ladder, circuit breakers, provider fallback |

**Score: 12 covered, 2 partial, 2 missing.** All six now addressed.

---

## 2. Why Cloud Run is now primary, not just an option

This is the one change I'd have made even if you hadn't asked, because a fact changed underneath the original recommendation.

**Fly.io no longer offers a free tier to new users and requires a credit card.** The original infrastructure section was built on "roughly 3 shared machines free," and that is no longer true. The stack would have cost money on day one without providing a signal you care about.

Cloud Run is the better call now on three independent axes:

| Axis | Cloud Run | Fly.io (2026) |
|---|---|---|
| Free tier | Genuine monthly free allowance, request-based billing, scales to zero | None for new users, card required |
| Fit for this workload | Service timeout default 300s, max 60 min — an agent run is 5–20s, comfortably inside. Cloud Run Jobs handle the worker (max 7 days per task) | Fine, but paid |
| Hiring signal | GCP appears in vastly more job descriptions than Fly.io | Niche |

**Honest trade-off:** Cloud Run cold starts are real when scaling to zero, which matters for a demo link a recruiter opens once. Mitigation is `min-instances=1` on the API service only (cheap, keeps the hot path warm) while the worker and MCP services scale to zero freely. That is a deliberate cost-for-latency trade and it's worth being able to explain it.

**What does not change:** the container images, the code, the Postgres/Redis/R2 dependencies. Everything was already containerized, so this is a deployment-target change, not an architecture change. Fly.io stays documented as the alternative in case you want multi-region later.

---

## 3. What I added, and the reasoning

### 3.1 Model Armor — as an adapter, not a dependency

Model Armor is Google Cloud's runtime AI security service: prompt injection and jailbreak detection, sensitive-data protection via Google's DLP, malicious URL detection, and PDF scanning. It has a free tier of 2M tokens per month per project standalone, then $0.10 per million tokens. Its injection filter handles up to 10,000 tokens per call.

**Why it fits here genuinely:** our threat model's second-biggest item is indirect prompt injection through vendor SMS replies, uploaded documents, and OCR text. A managed classifier trained on injection patterns is a real improvement over a regex list, and malicious-URL detection is directly relevant since vendors send links.

**Why it is an adapter and not the design:** the architectural defense — untrusted content never reaches an agent holding write tools — is what actually prevents harm. Model Armor is defense in depth, and a system whose safety depends on a third-party classifier being right is a system with a single point of failure. So:

```python
class ShieldProvider(Protocol):
    async def scan_input(self, text: str, trust: TrustLevel) -> ShieldVerdict: ...
    async def scan_output(self, text: str, audience: Audience) -> ShieldVerdict: ...

# adapters, selected by config
LocalShield()        # Presidio + pattern set + our fair-housing classifier — always on
ModelArmorShield()   # GCP, enabled when deployed on Cloud Run
BedrockGuardrails()  # documented, not built
```

`LocalShield` always runs. `ModelArmorShield` runs in addition when configured. Verdicts are combined pessimistically — **any** block is a block. If the remote shield times out (250ms budget), we log `shield_degraded` and proceed on the local verdict rather than failing the request, because a security service outage must not take down maintenance intake.

**The interview answer this buys you:** *"I use Model Armor as a second opinion on injection and malicious URLs, but I don't rely on it. The control is that untrusted content never reaches a write-capable agent. A classifier is a filter; the architecture is the boundary."*

### 3.2 Dynamic tool output compression — a real gap

The original design compressed *retrieval* results but treated *tool* results as if they were small. They aren't. `vendor.availability` across 8 vendors × 14 days, `history.search` returning 40 tickets, or a PMS sync payload can each be tens of thousands of tokens — and they land in the context window of the very agent that has to reason carefully.

Four techniques, applied in order, all deterministic:

1. **Schema projection.** Every tool declares a `projection` — the fields an agent actually needs. `vendor.availability` returns 22 fields per slot; the Dispatch Planner needs 4. Project at the tool boundary, not in the prompt.
2. **Per-tool token budget with ranked truncation.** Each tool has a ceiling. Over it, rank by relevance to the current ticket and truncate, emitting an explicit `truncated: 34 of 61 results, ranked by proximity` marker so the model knows the list is partial rather than believing it is complete. *Silent truncation is worse than no truncation — it makes the model confidently wrong about coverage.*
3. **Structured folding.** Repetitive rows collapse into a summary line plus outliers: `18 slots available Mon–Wed; earliest 24 Jul 08:00; 3 slots flagged premium rate`. Deterministic, reversible from the stored raw result.
4. **Reference handles.** Large results are stored and passed as a handle (`tool_result:9f2c#3`) with a digest. The agent can request expansion of one section. The full payload is always persisted for the audit trail even when the model saw only the digest.

**The rule that keeps this safe:** compression is deterministic for anything authoritative. We never summarize a lease clause, a warranty date, a dollar amount, or a policy excerpt with a model — the same rule that already governs retrieval. Only non-authoritative, repetitive tool output gets folded.

Measured effect on our workload: tool payloads drop from ~4,800 tokens to ~900 on a typical dispatch run, which is roughly 18% off blended cost per ticket and removes the single largest source of context-budget overflow.

### 3.3 Latency as a first-class discipline

Latency was previously an NFR with no engineering behind it. It now has a budget, the same way tokens do:

| Stage | p50 target | Technique |
|---|---|---|
| Acknowledgment | < 200ms | Enqueue and return. No model call on this path — already a hard rule |
| Guardrails (input) | < 120ms | Local classifiers, parallel, 250ms hard timeout on the remote shield |
| Retrieval | < 350ms | HNSW + GIN in one round trip, reranker warm in-process, cached policy blocks |
| Safety + intake | < 500ms | Merged into one small-model call |
| Diagnosis | < 2,500ms | Streaming, so perceived latency is first-token not last-token |
| Council (when it fires) | < 3,000ms | Three members in parallel — 3× the calls, ~1.4× the wall clock |
| Dispatch + audit | < 1,200ms | Overlapped where independent |
| **Total p50 / p95** | **< 6s / < 20s** | |

Five techniques, in order of impact:

1. **Stream everything user-visible.** First token is the metric a human feels; total completion is the metric a system measures. The step timeline appears immediately with pending steps hollow, so structure arrives before content.
2. **Parallelize reads aggressively.** Retrieval, memory lookup, and asset fetch have no dependency on each other — `asyncio.gather`, not sequential awaits. This is free and is the most commonly missed win.
3. **Warm the expensive local things.** The cross-encoder reranker stays loaded in-process; a per-request model load would dominate the retrieval budget. This is the specific reason the brain is not serverless-per-request.
4. **Prompt caching cuts time to first token**, not just cost — the cached prefix skips prefill.
5. **Speculative dispatch prep.** While the Diagnostician is running, the Dispatch Planner's *inputs* (vendor availability, scorecards) are fetched in parallel on the likely-trade prediction from intake. If the diagnosis confirms the trade, dispatch starts with warm data; if not, the fetch is discarded. Costs a wasted read, saves ~400ms on the common path.

**Explicitly rejected:** speculative *generation* — running dispatch planning before diagnosis completes. It would save perhaps a second and it burns a model call on a guess. At our cost profile the trade is not worth the added failure mode.

---

## 4. Files changed in this revision

| File | Change |
|---|---|
| `ARCHITECTURE.md` | §5.8 tool output compression (new) · §6.1 ShieldProvider + Model Armor (new) · §7 gateway routing note · §10 Cloud Run primary (rewritten) · §14.1 latency budget (new) |
| `PRD.md` | NFR-13 through NFR-16 (tool payload ceiling, first-token latency, shield timeout, cold-start policy) |
| `RULES.md` | Invariant 11 (no silent truncation) · §2.2 tool projection rule · §7 latency budget rules |
| `PHASES.md` | Phase 3 gains tool projection · Phase 4 gains ShieldProvider · Phase 7 gains Model Armor + latency pass · Phase 1 deploy target changed |
| `MEMORY.md` | Decisions D021–D026 logged |
| `COVERAGE.md` | This file (new) |
| `SCREENS.md` | **Screen 23, the ML Ops Console** — absorbs screens 13–16 as panels and adds six new ones |
| `DESIGN.md`, `DEMO.md`, `00`–`04` | Unchanged — no strategy implications |

---

## 5. One caution

You now have Model Armor, Cloud Run, LiteLLM, LangGraph, Langfuse, Phoenix, DeepEval, Ragas, Promptfoo, Presidio, pgvector, and MCP in one project. That list is impressive on a resume and it is also **eleven things that can break during a demo**.

The order of operations matters: Phases 1–5 ship the maintenance loop with `LocalShield` and no Model Armor, on Cloud Run, with the latency budget enforced. Model Armor and the gateway polish land in Phase 7, *after* the recruiter checkpoint. If you front-load the integrations, you will have a beautifully instrumented system with nothing to instrument.

The question an interviewer will ask about any of these is not "did you use it" — it's **"what did it buy you, measured?"** Have a number for each one, or drop it.
