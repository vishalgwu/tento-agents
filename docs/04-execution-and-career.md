# 04 — Execution, Demo & Career Leverage

---

## 1. The 12-week roadmap

Assumption: you at roughly 25–30 focused hours/week on the AI spine, your friend at similar on the product surface. Everything is sized to be cut in half without collapsing.

### Weeks 1–2 — Foundation

**You:** repo + monorepo scaffolding, `CLAUDE.md` and the six context docs, docker-compose local stack, schema + migrations, RLS with cross-tenant tests, seed generator (1 property, 400 units, 1,200 historical tickets, 40 assets, 8 vendors), KB with 12 real SOP/policy documents with front matter, ingestion + chunking + embeddings, hybrid retrieval with RRF, retrieval eval harness (recall@k on 50 hand-written query→doc pairs).

**Friend:** Next.js shells for three roles, auth flows, design system, ticket submit + list + detail, SSE client scaffolding.

**Gate:** `docker compose up` gives a working local system. Hybrid search returns sane results and you have a number for recall@5.

> **Do the retrieval eval in week 1, before any agent exists.** Retrieval quality caps everything downstream; if recall@5 is 0.6 you will spend weeks blaming prompts for a retrieval problem. This ordering is itself a strong signal of experience.

### Weeks 3–4 — The vertical slice

**You:** Safety Sentinel (rules + Haiku), Intake Normalizer, Context Broker with the token budgeter and provenance envelope, Diagnostician, Dispatch Planner, Policy Auditor, Communicator. LangGraph wiring with Postgres checkpointing and `interrupt()` on the approval node. Input/output guardrails v1. `agent_runs`/`agent_steps`/`llm_calls`/`decisions` writing on every run. Deploy to Fly + Vercel.

**Friend:** approval queue UI with the reject-reason taxonomy, ticket timeline with streaming steps, owner dashboard v1, vendor signed-link page.

**🎯 Gate — WEEK 4 IS THE RECRUITER CHECKPOINT.** A live URL where a stranger submits a ticket, watches the reasoning stream, sees the decision with citations, approves it in the manager console, and reads the audit record. If week 4 slips, cut Council and the owner dashboard, not this.

### Weeks 5–6 — Measurement

**You:** label the 200-item golden set (block out two evenings; do not spread it out). Eval harness with DeepEval + Ragas. CI eval gate with tolerance bands. Red-team fair-housing parity suite. Judge (offline 100%, online 10%). Calibration fitting + reliability diagram. `GET /runs/{id}/replay`.

**Friend:** trace viewer, retrieval inspector, eval dashboard, cost dashboard.

**Gate:** `evals/REPORT.md` exists with real numbers, published in the repo. CI fails on a deliberately-broken prompt. You can name your worst metric and why.

### Weeks 7–8 — Council, memory, robustness

**You:** Council Mode with evidence-split members, deterministic reviewer, synthesis, triage scorer. **Measure council lift against solo on the golden set and publish the delta — including if it's negative.** Episodic memory + reflection with approval-gated promotion. Degradation ladder including rules-only mode. LiteLLM gateway + routing policy + budgets + caching. MCP servers.

**Friend:** council visualization, agent health dashboard, governance/audit tab with export, notification UI.

**Gate:** kill the Anthropic API key in staging and watch the system degrade gracefully instead of erroring. Record that as a demo clip.

### Weeks 9–10 — Product surface

**You:** notification policy engine (tiers, quiet hours, fatigue budgets, dedupe, escalation), amenity booking, vendor scorecards feeding dispatch, performance pass (cache hit rates, p95).

**Friend:** community surface (interest groups, profiles), marketplace CRUD with ratings, manager-vetted vendor directory, mobile polish.

**Gate:** the product is demoable to a builder without you narrating the AI parts.

### Week 11 — Hardening & the artifacts

Load test (200 concurrent tickets), security pass (cross-tenant suite, secret scan, dependency audit), full documentation pass, architecture diagrams as SVG, **a 3-minute Loom** and a **90-second silent screen-capture GIF for the README**, the eval report finalized, three ADRs written up as blog posts.

### Week 12 — Launch

Public repo, Show HN / r/AI_Agents / LinkedIn, DM 20 mid-market operators and 5 CMMS founders for feedback calls (not sales — *feedback*; you'll get replies), submit to YC if the batch timing works, and update every resume variant with real numbers.

---

## 2. GitHub milestones

| Milestone | Issues | Definition of done |
|---|---|---|
| `M1 · Foundation` | 14 | Local stack runs; schema + RLS + cross-tenant tests green; seed data |
| `M2 · Retrieval` | 9 | Hybrid + RRF + rerank + parent-doc; recall@5 measured and reported |
| `M3 · Agents` | 16 | 7 agents, typed contracts, fixture tests, LangGraph graph, checkpointing |
| `M4 · Guardrails` | 11 | 15 guardrails, each a tested pure function; injection corpus passes |
| `M5 · Slice live` | 7 | Deployed, three roles, streaming, approvals, audit record |
| `M6 · Evals` | 12 | Golden set, CI gate, red-team, calibration, REPORT.md |
| `M7 · Council` | 9 | Triage, members, reviewer, synthesis, **lift measured** |
| `M8 · Memory` | 7 | 4 stores, approval-gated promotion, decay, contradiction handling |
| `M9 · Gateway & MCP` | 8 | LiteLLM, routing, budgets, caching, 3 MCP servers |
| `M10 · Observability` | 10 | Langfuse + Phoenix + 8 dashboards on real data |
| `M11 · Notifications` | 8 | Tiers, quiet hours, fatigue, escalation, receipts |
| `M12 · Community` | 12 | Groups, profiles, marketplace, ratings, booking |
| `M13 · Launch` | 9 | Docs, diagrams, video, blog posts, public |

Use issue labels `area:brain|web|infra|evals|docs` and `risk:high|med|low`. A public board with real velocity is itself a hiring signal — it shows you plan and finish, which is rarer than it should be.

---

## 3. The 2-minute recruiter demo

The path a reviewer takes when they land on the repo. Design it deliberately; most people leave this to chance and lose the reader in the first ten seconds.

**0:00–0:15 — README hero.** One sentence, one architecture diagram, one animated GIF of the trace streaming, and four badges: `evals: passing`, `groundedness 0.94`, `P0 recall 0.99`, `cost/ticket $0.021`. Then three links: **Live demo · Eval report · Architecture**.

**0:15–0:45 — Live demo, resident view.** Pre-filled prompt button: *"Water under my kitchen sink and it smells bad."* They tap. Steps stream: `screening for safety → extracting → retrieving 6 policy sources → 3rd occurrence detected → council triggered → auditing against lease §7.3 → decision`. The decision card shows priority, party, vendor, cost, **confidence 0.79**, and citations they can click.

**0:45–1:15 — Manager view.** The approval queue, sorted by SLA risk. They open the trace: retrieval inspector showing BM25 vs vector vs RRF vs rerank; the council's three members disagreeing; the token budget bar; cost. This is the moment a technical reviewer decides you're serious.

**1:15–1:40 — The compliance flip.** A second pre-filled button: *"I use a housing voucher — is that a problem for this unit?"* The system routes it to a human with a fair-housing guardrail block and a logged event. Show the CI red-team suite passing beside it. **This is your closing argument** — it demonstrates judgment, not just capability, and almost nobody's portfolio does.

**1:40–2:00 — Eval report.** A table with real numbers including the ones you missed, the calibration curve, and the council-lift delta.

**Do not** make them sign up, do not gate the demo behind a form, and do not autoplay audio. Demo accounts pre-logged-in via three buttons on the landing page.

---

## 4. Investor narrative

**The 60-second version:**

> Apartment operators handle about 3.3 maintenance requests per unit per year, and every one of them is a human guessing at urgency, liability, and who to send. Getting it wrong costs a $150 truck roll on one side and a habitability violation on the other. Meanwhile the whole industry is bolting AI onto resident communication — and doing it in a domain where every automated reply is a fair-housing event, private testing organizations can probe your bot remotely at scale, and twelve state AGs are pursuing AI discrimination claims.
>
> We built the operations layer instead of the chat layer. Resident OS runs the maintenance loop end to end — triage, grounding, policy check, dispatch — and every decision ships with its evidence: the retrieved policy version, the citations, the guardrail verdicts, the confidence score, and who approved it. Inference costs about $73 per property per year; a 500-unit property is a $12,000-a-year account. We start with maintenance because it's the one apartment workflow where we get correct answers for free — every manager override is a labeled training example.
>
> The incumbents built conversation-first. Regulated verticals end up decision-first, with audit trails. We're building for that end state.

**Slide order:** Problem (with the numbers) → Why now (regulation + adoption + incumbent AI) → Insight (auditability is the moat) → Demo (live, 90 seconds, no slides) → How it works (one architecture slide) → Evidence (the eval report — *investors have never seen a seed deck with a calibration curve*) → Market (21.1M US apartment units in 5+ unit buildings, 45.2M renter households, $30B+ property-management software market) → GTM (mid-market wedge, land on maintenance, expand to comms and owner reporting) → Team → Ask.

**Questions you will be asked, and the honest answers:**

- *"Why won't Yardi/Entrata just build this?"* — They are building it, shallowly, locked to their own data. Operators with mixed portfolios get nothing, and a suite vendor has no incentive to build an audit layer that documents its own errors. Also, the buyer for governance is the compliance and legal function, which is not the buyer the PMS vendors sell to.
- *"Why won't EliseAI just add it?"* — They could. Their architecture is conversation-first, so retrofitting a decision record means re-instrumenting the core. That's a real but finite moat measured in quarters, which is why the wedge is a segment they don't serve well.
- *"What's your unfair advantage?"* — Right now: none that's durable. The compounding asset is the labeled decision corpus and the jurisdiction-mapped guardrail library, and neither exists until we have customers. *Say this.* Founders who claim a Day-1 moat in a category with a $2.2B incumbent get marked as naive.
- *"Have you talked to customers?"* — Have a real answer by week 12. Twenty feedback calls beats a perfect deck.

---

## 5. Technical interview talking points

Twelve questions you will get, with the answer that lands.

**1. "Walk me through the architecture."**
Start with the constraint, not the components: *"Reliability compounds — ten LLM steps at 95% each is 60% end to end. So I budgeted five model calls on the critical path and made everything else deterministic. Three LLM calls in the normal path, five when the council fires on the 10% of tickets that are high blast radius."* Then the graph. Leading with the constraint tells them you've operated something.

**2. "Why multi-agent instead of one big prompt?"**
*"Mostly I'm not. There are three LLM calls in the common path. I split where there's a real boundary: different permissions, different context, different ground truth. The safety screen and the diagnosis have completely different loss functions — one needs 0.99 recall with a tolerable false-positive rate, the other needs balanced accuracy — and you can't tune one prompt for both or regression-test them together. Where I do parallelize, the subagents only read. There's exactly one writer."*

**3. "Cognition says don't build multi-agents. Anthropic published the opposite. Who's right?"**
*"Both, in their domain. The variable isn't agent count, it's read versus write. Anthropic's research system parallelizes reads and merges findings, which composes cleanly. Cognition's counterexample is a build task where subagents lost the implicit framing decision and produced an incoherent whole. So my council members read and return findings; the orchestrator holds every side-effecting tool. And Anthropic's multi-agent system used about 15× the tokens of a chat interaction — that's a real budget, which is why council fires on a scored 10% rather than by default."*

**4. "How do you prevent hallucination?"**
Lead with the deterministic answer, not the model answer: *"Every context item enters with an ID. The model must cite an ID for every factual claim. Then code — not a judge — verifies that every cited ID exists, that any sentence containing a number or a policy reference carries one, and that cited figures appear verbatim in the referenced chunk. Failures get one targeted regeneration and then a human. LLM judging exists too, but it's asynchronous and sampled, because for the base case the deterministic check already told me the answer for free."*

**5. "Why Postgres instead of a vector database?"**
*"Under about 10 million vectors, pgvector with HNSW is faster end to end and one less system. I'll have maybe 200,000 chunks. More importantly, I need metadata filtering, transactional consistency with my domain tables, and RLS-based tenant isolation on the same rows — that's all free in Postgres and awkward outside it. And I need lexical search anyway, because embeddings smear identifiers: 'SOP-PLM-04' ranks 47th in vector search. Hybrid with RRF took recall@5 from roughly 0.62 to 0.84 on my set."*

**6. "How do you evaluate this?"**
*"Four layers: unit tests per agent and per guardrail, component-level retrieval metrics, an end-to-end golden set of 200 hand-labeled tickets, and an adversarial suite. The eval gate blocks merges with tolerance bands rather than exact thresholds and a pinned judge model, because LLM nondeterminism makes exact-threshold gates flaky and a flaky gate gets ignored. The golden set is deliberately skewed toward ambiguous and near-miss cases — uniform sampling wastes labeling effort on tickets any system handles."*

**7. "How do you know your judge is right?"**
*"I don't fully. Published agreement between LLM judges and human raters sits around 85–92%, so the judge is a regression detector, not ground truth — the human-labeled set is the anchor. I also design around the known biases: judging with a different model family than generation to avoid self-preference, normalizing for length, randomizing pairwise order, and pinning the judge version so a judge upgrade is treated as a dataset migration rather than a silent invalidation of my whole time series."*

**8. "What's your biggest architectural risk?"**
*"Correlated errors in Council Mode. Three samples of the same model over the same context aren't independent — they agree confidently and wrongly, which manufactures confidence exactly where the system is weakest. That's why my council members are split by evidence rather than by persona: one sees policy, one sees history, one sees cost and asset data. Then disagreement carries information about the world. And I measure council lift over solo directly. If it isn't positive on the golden set, I cut it — the architecture doesn't get to survive on aesthetics."*

**9. "How do you handle prompt injection?"**
*"Architecturally first. Untrusted content — vendor SMS replies, OCR'd documents, image captions, resident text — can never reach an agent that holds write tools, because only the orchestrator has them and it doesn't take instructions from context. The scanner and the trust-labeled delimiters are the second line. Most implementations scan the chat box and forget that a vendor's SMS reply enters the same context window."*

**10. "How does this cost stay reasonable?"**
*"Blended $0.023 per ticket, about $73 per property per year. Four levers in order: prompt caching on the static prefix at roughly 90% off cached input, model routing with a 5× spread between Haiku and Sonnet, output-length discipline since output costs 5× input on every current tier, and context budgeting per slot. The interesting one is that splitting the council by evidence made each member cheaper than one large-context solo call, so the council premium is smaller than the call count suggests."*

**11. "What would you do differently with a team of five?"**
*"Three things I consciously skipped: a real durable workflow engine like Temporal instead of leaning on LangGraph checkpoints for multi-day suspension; a proper feature store for the routing and vendor-scoring signals; and fine-tuning a small model for intake extraction, which is high-volume, narrow, and probably 10× cheaper than Haiku at scale — but that needs labeled volume I don't have yet."*

**12. "What's the weakest part?"**
Have a real answer ready. *"No real customers, so my golden set is synthetic-but-realistic rather than drawn from production distribution — my accuracy numbers are honest for that set and unproven against real resident language. Second: my calibration is fit on 200 items, which is thin; the reliability diagram has wide error bars in the tails, and I'd want 1,000 before I trusted the auto-execution threshold."*

Answering #12 well is worth more than answering #1 well. Every strong engineer has a list; only weak ones don't.

---

## 6. Resume material

Written in your voice: no arrows, no tilde signs, figures spelled out, GitHub link inline. **Every bracket is a placeholder to be filled from your actual eval report — do not ship a number you cannot reproduce on demand.** Your prior repos were audited as well-scaffolded with implementation lagging structure; this project only helps you if the code behind these lines is real, which is why the eval report is the load-bearing artifact.

**Project block:**

> **Resident OS — AI Operations Layer for Apartment Communities** · github.com/[user]/resident-os
> Production-deployed multi-agent system that triages, diagnoses, and dispatches apartment maintenance requests with grounded citations and an auditable decision record.
> - Designed a 7-agent LangGraph workflow with durable Postgres checkpointing and human-in-the-loop approval gates, holding the critical path to 3 model calls to keep compounding step reliability above [XX] percent measured end to end.
> - Built a hybrid retrieval pipeline (pgvector HNSW plus Postgres full-text, fused with reciprocal rank fusion, then cross-encoder reranked), improving recall at 5 from [0.XX] to [0.XX] over dense-only retrieval on a hand-labeled query set.
> - Implemented a citation-verification guardrail that requires every factual claim to reference a provenance ID, raising measured groundedness to [0.XX] and reducing unsupported claims by [XX] percent.
> - Designed Council Mode, an evidence-partitioned ensemble that routes [XX] percent of high-blast-radius tickets to three specialists with disjoint context, improving priority macro F1 from [0.XX] to [0.XX] over single-agent reasoning.
> - Built a continuous evaluation harness (DeepEval, Ragas, Promptfoo) over a 200-item human-labeled golden set, gating every merge with tolerance bands and a pinned judge model; includes an adversarial fair-housing parity suite that blocks deploys on any violation.
> - Reduced blended inference cost to [$0.0XX] per ticket through prompt caching, tiered model routing, and per-slot context budgeting, tracked live on a cost dashboard.
> - Deployed on Google Cloud Run, Vercel, and Supabase with GitHub Actions CI, full OpenTelemetry tracing to Langfuse and Arize Phoenix, and a graceful degradation path to rules-only operation during model provider outages.
> - Cut per-run tool payloads from approximately [X,XXX] to [XXX] tokens through deterministic schema projection, ranked truncation with explicit coverage markers, and structured folding, reducing blended cost per ticket by [XX] percent.
> - Held p50 decision latency to [X.X] seconds against an explicit per-stage budget using parallel independent reads, an in-process warm cross-encoder, prompt caching for time-to-first-token, and speculative prefetch of dispatch inputs.
> - Layered Google Cloud Model Armor behind a pluggable shield interface for prompt-injection, jailbreak, and malicious-URL screening, with pessimistic verdict combination and a 250 millisecond timeout that degrades to local classifiers rather than failing the request.

**Skill-line additions:** LangGraph, LiteLLM, MCP, Langfuse, Arize Phoenix, DeepEval, Ragas, Promptfoo, pgvector, Presidio, LLM-as-judge, evaluation harness design, prompt versioning, agent observability.

**Which variant gets what** (from your five role-specific resumes):

| Variant | Lead with |
|---|---|
| **GenAI / AI Engineer** | Council Mode, citation verification, eval harness, cost per ticket |
| **ML Engineer** | Calibration and reliability diagram, classifier metrics, retrieval evaluation, judge-bias controls |
| **Forward Deployed Engineer** | End-to-end shipped product, three user surfaces, degradation ladder, deployed on free-tier infra, integration story |
| **Data Scientist** | Golden-set design and labeling methodology, macro F1, calibration error, A/B-able prompt versions |
| **Data Analyst** | Owner dashboard, cost analytics, SLA and override-reason analysis |

**Positioning line for cover notes and LinkedIn:**
> "I build LLM systems that can be measured. My latest is a multi-agent apartment-operations platform where every decision ships with its citations, its confidence, and its audit record, and every merge is gated by an evaluation suite over a human-labeled golden set."

That sentence separates you from the very large population of candidates whose portfolio is a RAG chatbot.

**Three blog posts to write in week 11** — these are worth more than a fourth feature, because they are what a hiring manager actually reads:
1. *"Council Mode manufactured confidence until I split the evidence"* — the correlated-error finding, with your measured lift numbers, positive or negative.
2. *"Your fair-housing guardrail is a system prompt, and that's not a control"* — the CI parity suite, with the probe methodology.
3. *"I evaluated Mem0, Zep, and LangMem and then wrote 200 lines of SQL"* — the memory decision, honestly argued.

---

## 7. Risks and mitigations

| # | Risk | Likelihood | Impact | Mitigation | Trigger to act |
|---|---|---|---|---|---|
| 1 | **Scope creep back toward 16 modules** | **High** | Fatal | Written scope contract in `docs/03-phases.md`; every new module needs an ADR arguing what it replaces | Any week where no eval number moved |
| 2 | **Structure outruns implementation** (your audited failure mode: scaffolded repos, stub files) | **High** | Fatal to credibility | No directory is created before the code that fills it; CI fails on empty modules; a stranger must be able to run one command and get a working system | Any file over 3 days old with a `pass` body |
| 3 | Council shows no measurable lift | Medium | Medium | Measure it; publish it; cut it if flat. A negative result honestly reported is a *stronger* interview artifact than a feature that quietly doesn't work | Week 8 measurement |
| 4 | LLM-judge drift silently invalidates metrics | Medium | High | Pin judge model + version + seed; record in `eval_runs`; re-baseline as a migration | Judge version bump |
| 5 | Fair-housing exposure in the *demo itself* | Low | **Severe** | Synthetic data only, never real resident text; demo mode blocks all outbound channels; the compliance demo shows a *block*, never a generated response about a protected class | Before any public link |
| 6 | Supabase free tier pauses during a recruiter visit | **High** | High | Pay the $25 before week 4; add an uptime check with alerting | Immediately |
| 7 | Cost blowout from a runaway agent loop | Medium | Medium | Per-org daily budget in the gateway, hard step cap of 12 nodes, circuit breaker, spend alert at 50% | Week 3 |
| 8 | Two developers plus two AI assistants produce four architectures | **High** | High | `CLAUDE.md` invariants, ADRs, generated shared types, weekly 30-minute architecture sync, one owner per package | First merge conflict in `brain/` |
| 9 | Friend's availability drops | Medium | Medium | AI spine must be demoable without the polished UI; keep a minimal server-rendered fallback console | Two missed weeks |
| 10 | Model provider outage during a demo | Medium | High | Rules-only mode; local Ollama fallback; record a backup demo video | Week 8 |
| 11 | Job offer lands mid-build | **Desirable** | Medium | Weeks 1 through 6 are the career-critical block; everything after is optional. Sequence accordingly | Any offer |
| 12 | Real regulatory exposure if you ever onboard a real property | Low now, high later | Severe | Do not process real resident data before you have a DPA, an insurance conversation, and counsel. Feedback calls, not pilots | First operator says yes |
| 13 | Building a screening or fraud model | Low | Severe | Explicitly out of scope. FCRA adverse action plus disparate impact is not a solo-founder problem | If tempted |
| 14 | Claiming numbers you cannot reproduce | Low | **Career-severe** | Every resume figure traces to a committed eval run and a git SHA. Publish the bad ones too | Every resume edit |
| 15 | Visa/sponsorship constraints narrowing the funnel | Known | High | Prioritize employers with established sponsorship history; the project raises your ceiling but doesn't change eligibility — target accordingly | Ongoing |

---

## 8. The honest closing note

You wrote that your job depends on this. So here is the thing I would want said to me.

**The blueprint is not the asset. Week 4 is the asset.**

A 40-page architecture document written with an AI is, in July 2026, close to worthless as a hiring signal — everyone has one. What is rare, and what will actually move your outcome, is a deployed URL where a stranger watches a system reason, sees the citations, sees the confidence, sees it refuse to answer something it shouldn't, and then reads an eval report with a number you missed and an explanation of why.

That is achievable in four weeks. The other eight weeks make it a company. The first four make it a job.

So if you read one instruction out of everything here: **cut anything that competes with shipping the vertical slice by week 4.** The community app, the marketplace, the wellness agent, the sixteen modules — all of them are real, all of them can wait, and none of them are what gets you the interview.

Then, in the interview, the sentence that will land harder than any architecture diagram is the one about council lift: *"I measured whether my most sophisticated component actually helped, and I was prepared to delete it."*

Most candidates cannot say that about anything they've built.
