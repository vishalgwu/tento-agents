# MEMORY.md

**The project's long-term memory. Updated at the end of every phase, and any time a decision is made.**

---

## How to use this file

**If you are an AI coding agent:** read this file at the start of every session, immediately after `RULES.md`. It tells you what was already decided, what was already tried and failed, and what is currently in flight. Do not re-solve a solved problem. Do not re-open a closed decision without new information. If your plan contradicts something in the Decision Log, say so explicitly before you write code.

**If you are a human:** this is the only file that survives context loss — yours, your collaborator's, and every assistant's. The five minutes at the end of each phase spent updating it is the cheapest insurance in the project. It gets skipped when you are tired. Do not skip it.

**Update triggers:**

| Trigger | What to add | Who |
|---|---|---|
| Phase completes | Phase log entry + metrics snapshot + carry-forward items | Both, together |
| A decision is made | Decision Log row (+ an ADR file if expensive to reverse) | Whoever proposed it |
| Something tried fails | "Tried and rejected" entry — **this is the highest-value section in the file** | Whoever tried it |
| A contract changes | Contract Change Log row | The artifact owner |
| A metric moves materially | Metrics History row | Track A |
| Track ownership changes | Update §2 | Both |

**Never delete history from this file.** Mark things superseded; do not remove them. The record of what did not work is what stops you doing it again in November.

---

## 1. Current state

```
PHASE:            0 — Contract Freeze
STATUS:           Not started
STARTED:          —
TARGET:           —
LAST UPDATED:     2026-07-25
REPO TAG:         —
DEPLOYED:         no
DEMO URL:         —
EVAL REPORT:      not yet generated
```

**Right now the next action is:** run Phase 0 (`PHASES.md` §3) — three days, both developers, producing eight frozen artifacts. Nothing else starts until all eight are committed.

---

## 2. Track assignment

| Track | Owner | Paths |
|---|---|---|
| **A — Brain** | Vishal | `services/brain`, `services/api`, `services/worker`, `services/mcp`, `knowledge`, `evals`, `infra/migrations`, `infra/seed`, `.github/workflows/evals.yml` |
| **B — Surface** | *(collaborator)* | `apps/web`, `packages/ui`, `infra/docker-compose*.yml`, `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, `DESIGN.md` |

Split variant in use: **Brain / Surface** (see `PHASES.md` §2.2 for alternatives).
Changed on: — · Reason: —

---

## 3. Phase log

Copy this template for each phase. Fill it at the integration checkpoint, together, before starting the next phase.

```markdown
### Phase N — <name>
**Dates:** YYYY-MM-DD → YYYY-MM-DD · **Tag:** phase-N-complete · **Status:** complete | partial

**Shipped**
- Track A:
- Track B:

**Definition of done — verified on preview deploy**
- [ ] item
- [ ] item

**Cut from this phase (and where it went)**
-

**Metrics snapshot**
| metric | value | vs last phase |
|---|---|---|

**Decisions made** → see Decision Log rows #

**Tried and rejected** → see §5 entries

**Contract changes** → see §6 rows

**Integration checkpoint**
- Duration: __ minutes (target < 90; over 90 means a contract leaked — say where)
- Leaks found:

**Carried forward into Phase N+1**
-

**Surprises worth remembering**
-
```

---

### Phase 0 — Contract Freeze
**Dates:** — · **Status:** not started

**Eight artifacts to freeze**
- [ ] `infra/migrations/0001_init.sql` — complete schema, all tables including Phase-8 ones, RLS, indexes
- [ ] `docs/vocabularies.md` — every enum's exact string values
- [ ] `docs/openapi.yaml` — hand-written before any endpoint exists
- [ ] `docs/events.md` — SSE event names and payloads
- [ ] `services/brain/src/brain/contracts.py` — Pydantic agent contracts
- [ ] `packages/ui/tokens.ts` + `DESIGN.md` §3 — design tokens and component inventory
- [ ] `docs/seed-spec.md` — synthetic dataset specification
- [ ] `docs/errors.md` — stable error catalogue

**Exit gate**
- [ ] `docker compose up` yields Postgres with schema + seed loaded
- [ ] Mock server serves the OpenAPI spec
- [ ] `packages/shared-types` generates cleanly
- [ ] Both developers can state their owned paths from memory

---

## 4. Decision log

Every decision that would be annoying to reverse. Expensive ones also get `docs/adr/NNNN-*.md`.

| # | Date | Decision | Why | Alternatives rejected | ADR | Status |
|---|---|---|---|---|---|---|
| D001 | 2026-07-25 | LangGraph as orchestrator | Durable Postgres checkpointing, `interrupt()` maps directly onto the approval queue, explicit conditional edges | CrewAI (weaker mid-run recovery), AutoGen (maintenance mode) | 0001 | active |
| D002 | 2026-07-25 | Agents are plain async functions; LangGraph nodes are thin wrappers | Framework independence — dropping LangGraph costs ~200 lines, not the product | Native framework abstractions throughout | — | active |
| D003 | 2026-07-25 | Postgres + pgvector, no dedicated vector DB | Under ~10M vectors it is faster end to end, cheaper, and one fewer system; we expect ~200k chunks | Pinecone, Qdrant, Weaviate | 0002 | active |
| D004 | 2026-07-25 | Hybrid retrieval (tsvector + pgvector, RRF, cross-encoder rerank) | Embeddings smear identifiers; `SOP-PLM-04` and `§7.3` are exactly what users cite | Dense-only | — | active |
| D005 | 2026-07-25 | No knowledge-graph RAG | Our graph is relational with clean foreign keys; a SQL join is exact and free | Neo4j, Graphiti | — | active |
| D006 | 2026-07-25 | Build the 4-store memory service; keep a `MemoryProvider` interface | Our durable facts are structured and legally consequential; `valid_from`/`valid_to` gives temporal validity | Mem0 (fuzzy extraction over already-structured facts), Zep (heavy ingest, retrieval lag, CE retired), LangMem (p95 latency unusable interactively) | 0003 | active |
| D007 | 2026-07-25 | Council members split by **evidence**, not persona | Same-model samples over the same context produce correlated errors — they agree confidently and wrongly | Three-persona ensemble as originally specified | 0004 | active |
| D008 | 2026-07-25 | Council fires on a deterministic score, target 8–12% of tickets | Council costs ~3× solo; blanket use is unjustifiable | Council on all high-risk categories | — | active |
| D009 | 2026-07-25 | Read-parallel, write-single-threaded — only the orchestrator holds write tools | Conflicting implicit decisions cannot be merged; reads compose, writes do not | Peer-to-peer agent writes | 0005 | active |
| D010 | 2026-07-25 | ≤ 5 LLM calls on the critical path | `p^N` compounding: 10 steps at 95% is 60% end to end | Longer chains with more specialisation | — | active |
| D011 | 2026-07-25 | LiteLLM self-hosted for transport; policy layer is our code | Transport is commodity; routing/budget/cache policy is the product | OpenRouter (fee + latency), Portkey (cost), build our own (6 wasted weeks) | — | active |
| D012 | 2026-07-25 | Provenance envelope + deterministic citation verifier | Catches most confabulation for near-zero cost, no judge required for the base case | LLM-judge-only groundedness checking | 0006 | active |
| D013 | 2026-07-25 | No protected-attribute columns exist anywhere in the schema | A schema that cannot store one cannot leak or infer from one | Store-and-restrict-access | 0007 | active |
| D014 | 2026-07-25 | Memory writes are proposals requiring human approval or N-fold confirmation | Memory poisoning: an agent that writes freely will write something wrong, retrieve it as fact, and reinforce it | Free agent memory writes | — | active |
| D015 | 2026-07-25 | MVP scope = maintenance loop only; 13 of 16 modules deferred | Maintenance is the only apartment workflow with abundant free ground truth — every manager override is a label | Broad shallow coverage | 0008 | active |
| D016 | 2026-07-25 | No tenant screening or fraud-scoring model, at any phase | FCRA adverse action + disparate impact is not a solo-founder problem | Build it later | — | active |
| D017 | 2026-07-25 | Fair-housing parity suite is a hard-fail CI gate | Compliance is not a system prompt; testing organisations probe live bots at scale | Manual review | 0009 | active |
| D018 | 2026-07-25 | Eval gate uses tolerance bands and a pinned judge, not exact thresholds | Nondeterminism makes exact gates flaky, and a flaky gate gets ignored | Exact thresholds | — | active |
| D019 | 2026-07-25 | Design language: architectural drawing + building signalling; blue = machine, brass = human | Encodes the product thesis (who decided this) in the colour system itself | Generic SaaS dashboard palette | — | active |
| D020 | 2026-07-25 | Phase 0 freezes eight contracts before any feature code | The only reliable way two people build in parallel without rework | Design as you go | — | active |
| D021 | 2026-08-01 | **Cloud Run replaces Fly.io as the primary deploy target** | Fly removed its free tier for new accounts, invalidating the original basis. Cloud Run has a real free allowance, a 60-min service ceiling that comfortably covers a 5–20s run, Jobs for the worker, and is a far stronger hiring keyword | Fly.io (now paid), Render (free tier spins down), Railway ($1 credit) | 0010 | active — **supersedes the Fly.io choice in D003-era infra notes** |
| D022 | 2026-08-01 | `min-instances=1` on the API service only; everything else scales to zero | Cold start hits the exact request a recruiter makes. Warming one service is a few dollars; warming all of them is not worth it. Also required to keep the cross-encoder resident | Warm everything, warm nothing | — | active |
| D023 | 2026-08-01 | Model Armor as a `ShieldProvider` adapter, never the boundary | Real value on injection and malicious URLs (vendors send links, residents upload PDFs), with a free tier. But safety that depends on a third-party classifier has a single point of failure — the architectural rule that untrusted content cannot reach a write-capable agent is the actual control | Model Armor as primary defense; Bedrock Guardrails; local-only | 0011 | active |
| D024 | 2026-08-01 | Remote shield gets a 250ms budget, then proceeds on the local verdict | A security-service outage must not take down maintenance intake. Logged as `shield_degraded` | Fail closed on shield timeout | — | active |
| D025 | 2026-08-01 | Deterministic tool output compression — projection, ranked truncation with a marker, folding, reference handles | Tool payloads were the largest unmanaged context consumer (~4,800 → ~900 tokens on a dispatch run). Truncation markers are mandatory: silent truncation makes the model confidently wrong about coverage | LLM summarization of tool results (rejected — same rule as policy text) | 0012 | active |
| D027 | 2026-08-01 | **ML Ops console absorbs screens 13–16 rather than sitting beside them** | Debugging reads across agent health, cost, evals, and gateway simultaneously. Four routes with four time ranges hides the correlation that is usually the answer | Four standalone dashboards (the earlier plan); tabs within one route | 0013 | active — **supersedes the standalone framing of screens 13–16** |
| D028 | 2026-08-01 | Failure events are typed, triageable, and promotable to `label_queue` — but never auto-added to an eval dataset | Closes the loop from production failure to CI gate. The human-authored expected answer is what keeps the eval set from grading the model against its own behaviour | Auto-promote failures; no promotion path at all | 0014 | active |
| D029 | 2026-08-01 | The agent change narrative is rule-generated, not LLM-generated | "Prompt unchanged, retrieval flat, KB changed yesterday" is a join. An LLM writing it would occasionally invent a cause, which is the worst possible failure in a debugging tool | LLM-written summaries | — | active |
| D030 | 2026-08-01 | All console panels read `metric_rollups`; raw event tables are never queried by a dashboard | Observability that slows down as the system degrades is worse than none | Live aggregation over `llm_calls` | — | active |
| D031 | 2026-08-01 | Alert only on online-vs-offline metric delta; display the other three drift signals | Alerting on all four produces noise, noise gets muted, and a muted alert is worse than no alert | Alert on all drift signals | — | active |
| D026 | 2026-08-01 | Latency gets an explicit per-stage budget; speculative reads allowed, speculative generation rejected | "Make it faster" is not a plan. Prefetching dispatch inputs on the predicted trade saves ~400ms for a wasted query; running dispatch generation on a guess burns a model call and adds a failure mode | Speculative generation; no budget at all | — | active |

---

## 5. Tried and rejected

The most valuable section in this file. Record anything attempted that did not work, so nobody — human or assistant — retries it in six weeks.

```markdown
### <thing tried>
**When:** Phase N · **By:** A|B
**What we expected:**
**What happened:**
**Why it failed:**
**Would we revisit?** yes, if <condition> | no
```

*(No entries yet — the project has not started. Expect the first ones in Phase 2, usually about chunking.)*

---

## 6. Contract change log

| # | Date | Artifact | Change | Broke | Both ack'd | Phase |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |

If this table has more than ~6 rows by Phase 5, Phase 0 was rushed. Note that observation here when it happens.

---

## 7. Metrics history

One row per eval run that changes a headline number. Always record the git SHA — an unreproducible metric is not a metric.

| Date | SHA | Phase | P0 recall | Priority F1 | Trade acc | Chargeback acc | Groundedness | Escalation prec | ECE | Council lift | $/ticket | p95 (s) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — | — | — | — | — | — | baseline pending |

**Retrieval sub-table** (Phase 2 onward):

| Date | SHA | recall@5 dense-only | recall@5 hybrid | recall@5 + rerank | MRR | nDCG@10 |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |

---

## 8. Open questions

| # | Question | Owner | Blocking | Needed by | Status |
|---|---|---|---|---|---|
| Q1 | Ship the community surface for the builder pitch, or stay maintenance-only for the hiring pitch? | Vishal | no | Phase 6 | open |
| Q2 | Which jurisdictions get encoded SLA tables at launch? (VA/MD/DC proposed) | Vishal | Phase 2 KB | Phase 2 | open |
| Q3 | Disclose "AI-assisted" on every resident message, or once at onboarding? | Vishal | no | Phase 4 | open |
| Q4 | Real PMS read-adapter in Phase 7, or standalone through v1? | Both | no | Phase 7 | open |
| Q5 | Marketplace: listings only, or resident-to-resident payments? (listings only proposed) | Track B | no | Phase 8 | open |
| Q6 | Does Council actually earn its place? | Vishal | no | Phase 6 | **open — decided by measurement, not opinion** |

---

## 9. Known issues and debt

| # | Issue | Severity | Introduced | Plan |
|---|---|---|---|---|
| — | — | — | — | — |

---

## 10. Glossary

Shared vocabulary. If two people use different words for the same thing, add it here rather than arguing in a PR.

| Term | Meaning |
|---|---|
| **Run** | One execution of the maintenance workflow for one ticket |
| **Envelope** | The assembled context with provenance IDs handed to a model |
| **Citation ID** | `[C1]`, `[F1]` — a handle into the envelope that every factual claim must carry |
| **Council** | The evidence-partitioned ensemble that fires on high-blast-radius tickets |
| **Lift** | Council's measured improvement over solo on the golden set. If ≤ 0, Council is deleted |
| **Blast radius** | How irreversible and how expensive a decision's consequences are |
| **Golden set** | 200 human-labelled tickets; the anchor for all quality claims |
| **Abstention** | The system declining to decide, with reasons. A first-class output, not an error |
| **Rules-only mode** | Full degradation: keyword safety screen + category-default SLA + acknowledgment, no model calls |
| **Approval token** | Single-use, action-scoped credential the decision gate issues so a write can execute |
| **Reflection** | A distilled durable lesson, proposed by an agent and promoted only after human approval |
| **Machine blue / human brass** | The colour semantic showing who made each decision |
| **Title block** | The drawing-derived page header carrying property, unit, ticket, revision, and decider |
| **ShieldProvider** | The interface behind PII, injection, toxicity, and output-leak screening. `LocalShield` always runs; managed providers augment it |
| **Pessimistic combine** | When multiple shields return verdicts, any block is a block |
| **Projection** | The field subset a tool returns into a prompt, declared on the tool itself |
| **Truncation marker** | The mandatory in-prompt note saying what was cut and why. Silent truncation is an invariant violation |
| **Speculative read** | Prefetching data on a prediction. Allowed. Distinct from speculative generation, which is not |
| **Rollup** | A pre-computed hourly metric bucket. Every ops panel reads these; none query raw events |
| **Failure signature** | A stable hash grouping identical failures, used for counting and 7-day dismissal |
| **Label queue** | Production failures and inspected outputs awaiting a human-written expected answer before entering an eval dataset |
| **Change narrative** | The rule-generated sentence in the agent scorecard saying what moved and what did not |

---

## 11. Standing reminders

Things that are true regardless of phase, and that get forgotten under deadline pressure.

1. **Week-4 demoable and Phase-5 recruiter checkpoint are the career-critical deliverables.** Everything after makes it a company. If something must be cut, cut from Phase 6+.
2. **No number ships that cannot be reproduced from a committed eval run and a SHA.** This applies to the README, the blog posts, and every resume.
3. **Publish the metrics we miss.** An eval report with three red numbers and honest explanations is more credible than five green ones.
4. **Structure without implementation is worse than no structure.** No directory before the code that fills it.
5. **`DEMO_MODE` before every public link.** A demo that texts a real number is a career-limiting bug.
6. **Pay for Supabase Pro before any demo you care about.** The free tier pauses after 7 idle days.
7. **Measure whether each sophisticated component earns its place, and be willing to delete it.** That willingness is the strongest thing you can demonstrate about this project.
8. **Eleven integrations is eleven things that can break during a demo.** Model Armor, the gateway polish, and the latency pass land in Phase 7 — *after* the recruiter checkpoint. Front-loading integrations produces a beautifully instrumented system with nothing to instrument.
9. **For every tool and service in the stack, have a measured answer to "what did it buy you?"** Not "did you use it." If there is no number, drop it.
