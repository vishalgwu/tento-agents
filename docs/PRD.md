# PRD.md — Product Requirements

**Project:** Resident OS — AI Operations Layer for Apartment Communities
**Status:** Draft v1.0 · Owner: Vishal · Last updated: 2026-07-25
**Related docs:** `ARCHITECTURE.md` · `RULES.md` · `PHASES.md` · `DESIGN.md` · `MEMORY.md`

> This file is the single source of truth for **what** we are building and **why**. If code contradicts this file, one of them is wrong — resolve it here first, then change the code. Any scope change requires an edit to this file in the same PR.

---

## 1. Vision

**Property management software records what happened. Nobody built the layer that decides what to do next.**

Resident OS is that layer. It sits on top of the existing system of record (Yardi, Entrata, AppFolio, Buildium) and runs the workflows those systems only log — starting with the maintenance loop. Every decision it makes is grounded in retrieved policy, checked by deterministic guardrails, scored for confidence, and written to an immutable audit record.

**Positioning sentence:**
> Resident OS runs apartment operations end to end, and every decision it makes comes with its receipts.

**Three-year arc:**

| Year | Mode | What changes |
|---|---|---|
| 1 | **Decide** | AI proposes, human approves. Value = fewer misroutes, faster P0 response, an audit record that did not previously exist. |
| 2 | **Act** | Auto-execution unlocked per decision class once measured accuracy clears an operator-set threshold. Autonomy is a dial with an evidentiary gate, not a switch. |
| 3 | **Orchestrate** | Cross-workflow coordination: maintenance history informs renewal risk informs turn cost informs capital planning. |

---

## 2. The problem (with numbers)

- A US apartment portfolio generates roughly **3.3 maintenance requests per unit per year** at roughly **$200 per request** — about **$660 per unit per year** in ongoing maintenance spend.
- Triage is still a human reading free text and guessing at four things: urgency, trade, who pays, and what the tech will need on arrival.
- Wrong in one direction: a licensed plumber on a $150 truck roll for a garbage disposal reset.
- Wrong in the other direction: a no-heat call sitting three days in January, which in CA/NY/TX/IL is a habitability statute with rent abatement attached, not a customer-service issue.
- Meanwhile the industry is deploying AI into a domain with strict liability: HUD's 2024 guidance places AI screening and advertising inside the Fair Housing Act; private fair-housing organizations handle the large majority of discrimination complaints and can now probe a live leasing bot remotely and at scale; ADA digital-accessibility filings surged toward ~5,000 in 2025; twelve state AGs are pursuing AI discrimination claims; Colorado's AI Act reaches "consequential decisions" including tenant screening.

**Our insight:** in a regulated vertical, the durable product is not the smartest model — it is the **defensible decision record**.

---

## 3. Users and personas

| Persona | Role | Frequency | Primary device | Core job |
|---|---|---|---|---|
| **Priya** — Resident | `resident` | 3–5×/year, plus community use | Mobile | "Get my problem fixed and tell me what's happening" |
| **Marcus** — Property Manager | `manager` | All day, every day | Desktop, keyboard-first | "Clear my queue without making an expensive mistake" |
| **Sam** — Maintenance Tech | `tech` | All day | Mobile, often gloved, often offline | "Tell me where to go and what to bring" |
| **Ravi** — Vendor | `vendor` | Per job | Mobile, no app installed | "Accept or decline in two taps" |
| **Dana** — Asset Owner | `owner` | Monthly | Desktop | "Is my asset being run well, and can I prove it" |
| **Ops Admin** — You | `admin` | Daily during build | Desktop | "Why did the system do that" |

### Jobs to be done

- Resident: *When something breaks, I want to report it in under 30 seconds and know it's handled, so I don't have to chase anyone.*
- Manager: *When a ticket arrives, I want the right decision pre-made with its reasoning visible, so I can approve in 5 seconds or correct it in 20.*
- Tech: *When I'm dispatched, I want the unit, the access notes, the likely cause, and the parts, so I fix it on the first visit.*
- Owner: *When I review the month, I want cost, SLA compliance, and proof the AI behaved, so I can defend the asset.*

---

## 4. Scope

### 4.1 In scope — MVP (Phases 0–5)

The **Maintenance Loop**, end to end, plus the three surfaces that consume it.

### 4.2 In scope — Post-MVP (Phases 6–9)

Notification platform, community surface, marketplace, amenity booking, vendor directory.

### 4.3 Explicitly out of scope

| Item | Reason |
|---|---|
| Payments / rent collection | PCI, KYC, state trust-accounting law. Integrate Stripe later; never hold funds. |
| Tenant screening / application fraud detection | FCRA adverse action + disparate impact. **Do not build without counsel.** |
| Move-in/move-out damage vision | Output is a deposit deduction — a dispute-generating financial decision. |
| Package intelligence | Solved by hardware vendors. No differentiation. |
| Energy optimization | Requires IoT/BMS integration we do not have. |
| Complaint resolution between neighbors | Defamation + discrimination risk, no ground truth. |
| Voice channel | Telephony + state recording-consent law. Phase 8+ at the earliest. |
| Knowledge-graph RAG / Neo4j | Our "graph" is relational with clean foreign keys. A SQL join is exact and free. |
| Wellness / events agent | Designed (§8), built in Phase 9. |

---

## 5. Functional requirements

Requirement IDs are stable. Reference them in issues, tests, and commit messages.

### 5.1 Intake

| ID | Requirement | Priority |
|---|---|---|
| FR-101 | Resident can submit a ticket with free text, up to 5 photos, and optional voice note | P0 |
| FR-102 | Submission acknowledged with a ticket number in **under 1 second**, independent of any model call | P0 |
| FR-103 | Duplicate submissions within 60s with identical content are deduplicated via idempotency key | P0 |
| FR-104 | Photos are captioned by a vision model; caption cached and reused | P1 |
| FR-105 | Voice notes transcribed; audio deleted after transcription, transcript retained | P2 |
| FR-106 | Staff can create a ticket on a resident's behalf, attributed correctly | P1 |
| FR-107 | Resident can add follow-up messages to an open ticket | P1 |

### 5.2 Safety screening

| ID | Requirement | Priority |
|---|---|---|
| FR-201 | Every ticket passes a deterministic life-safety keyword/pattern screen before any other processing | P0 |
| FR-202 | A small model provides a second opinion; **either** signal triggers the P0 path (OR, never AND) | P0 |
| FR-203 | P0 path contains **no LLM call between detection and paging a human** | P0 |
| FR-204 | P0 events page on-call via push + SMS + voice simultaneously, ignoring quiet hours | P0 |
| FR-205 | Target: P0 recall ≥ 0.99 on the golden set; precision ≥ 0.70 is acceptable | P0 |
| FR-206 | Every P0 detection and every P0 near-miss is logged for eval review | P0 |

### 5.3 Triage and diagnosis

| ID | Requirement | Priority |
|---|---|---|
| FR-301 | Extract structured facts: category, subcategory, symptom, asset, access permission, pets, preferred window | P0 |
| FR-302 | Retrieve evidence: SOPs, lease clauses, unit history, asset record, warranty status | P0 |
| FR-303 | Produce a diagnosis where **every factual claim carries a citation ID** resolvable in the evidence envelope | P0 |
| FR-304 | Assign priority P0–P3 with an SLA deadline derived from category + property jurisdiction | P0 |
| FR-305 | Assign responsible party (owner / resident / third party / undetermined) with lease citation | P0 |
| FR-306 | Emit `unknowns[]` for anything material the evidence does not support | P0 |
| FR-307 | Emit a calibrated confidence score, not a raw self-report | P1 |
| FR-308 | Route to Council Mode when the deterministic triage score ≥ 0.50 | P1 |
| FR-309 | Council members have **disjoint evidence** (policy / history / cost) and return the same schema | P1 |
| FR-310 | Council disagreement of ≥ 2 priority levels, or any disagreement on responsible party, forces human review | P1 |

### 5.4 Dispatch

| ID | Requirement | Priority |
|---|---|---|
| FR-401 | Propose trade, in-house vs vendor, specific vendor, time window, parts, cost estimate | P0 |
| FR-402 | Vendor ranking uses accept rate, response time, first-time-fix rate, cost variance, and service area | P1 |
| FR-403 | Never propose a vendor with expired insurance or outside their service area | P0 |
| FR-404 | Vendor receives a signed, single-use, TTL-limited link — **no account required** | P1 |
| FR-405 | Vendor decline reasons are captured and feed the scorecard | P2 |

### 5.5 Policy and guardrails

| ID | Requirement | Priority |
|---|---|---|
| FR-501 | Every decision is audited against lease, SOP, and statutory SLA before it can execute | P0 |
| FR-502 | Source precedence on conflict: **statute > lease > internal SOP > vendor contract** | P0 |
| FR-503 | Policy Auditor operates on the decision output, not the reasoning chain | P0 |
| FR-504 | All resident-facing text passes a fair-housing / ADA screen before send | P0 |
| FR-505 | PII is detected and redacted before any prompt is assembled | P0 |
| FR-506 | Prompt-injection scanning applies to **all** untrusted text, including vendor replies, OCR output, and image captions | P0 |
| FR-507 | Guardrail verdicts are never overrideable by a model, only by an authorized human with a logged reason | P0 |
| FR-508 | A guardrail block on resident-facing text results in human routing, never a silent rewrite | P0 |

### 5.6 Approval and execution

| ID | Requirement | Priority |
|---|---|---|
| FR-601 | Decisions land in an approval queue sorted by **SLA risk**, not arrival time | P0 |
| FR-602 | Approve / Approve-and-edit / Reassign / Reject are available on one screen without scrolling | P0 |
| FR-603 | Reject requires a reason from a fixed taxonomy: wrong priority, wrong trade, wrong party, policy misread, other | P0 |
| FR-604 | Every approval and every override is written to `decisions` with actor and timestamp | P0 |
| FR-605 | Execution requires a single-use, action-scoped approval token | P0 |
| FR-606 | All side-effecting actions are idempotent on (ticket, action, params-hash) | P0 |
| FR-607 | Auto-execution is available per decision class only when an org enables it and 30-day measured accuracy exceeds the org's threshold | P2 |

### 5.7 Audit and transparency

| ID | Requirement | Priority |
|---|---|---|
| FR-701 | Every run stores: steps, prompt version + hash, model + version, retrieved chunks with scores, guardrail verdicts, tokens, cost, latency | P0 |
| FR-702 | A trace viewer renders the full run for any ticket, readable by a non-engineer | P0 |
| FR-703 | `GET /runs/{id}/replay` re-executes a past decision against **pinned** prompt, model, and KB versions and diffs the result | P1 |
| FR-704 | `decisions`, `llm_calls`, and `guardrail_events` are append-only with a nightly hash chain | P1 |
| FR-705 | Owner can export a signed audit bundle (JSON + PDF) for a date range | P2 |
| FR-706 | Context is filtered by the ticket's timestamp, not `now()`, so replay uses the policy in force at decision time | P1 |

### 5.8 Notifications

| ID | Requirement | Priority |
|---|---|---|
| FR-801 | Four urgency tiers U0–U3 with distinct quiet-hour, channel, retry, and escalation policies | P1 |
| FR-802 | An LLM may render copy inside an approved template; it may **never** decide whether or when to send | P0 |
| FR-803 | Per-recipient per-tier fatigue budget; exhausted budget **drops and logs**, never queues | P1 |
| FR-804 | Higher tiers preempt scheduled lower tiers within a 30-minute window | P2 |
| FR-805 | U0 escalates through an on-call chain if unacknowledged within 10 minutes | P1 |
| FR-806 | `DEMO_MODE` blocks all outbound channels absolutely | P0 |

### 5.9 ML operations console

| ID | Requirement | Priority |
|---|---|---|
| FR-1001 | A single `admin`-only console surfaces model, agent, prompt, output, eval, failure, and drift state under one global time range | P1 |
| FR-1002 | Per-agent scorecard ranked by degradation, with a **rule-generated** change narrative — never model-generated | P1 |
| FR-1003 | Typed failure feed grouped by taxonomy, each event triageable with a written `why` and `fix` that persist | P1 |
| FR-1004 | A production failure or inspected output can be promoted to `label_queue`; it enters an eval dataset **only after a human writes the expected answer** | P0 |
| FR-1005 | Model registry showing what is live, run counts, cost per run, latency, and quality per model | P2 |
| FR-1006 | Prompt registry with version, content hash, traffic split, per-version quality, and one-click rollback by config flip | P1 |
| FR-1007 | Drift panel comparing online against offline metrics; only the online/offline delta raises an alert | P1 |
| FR-1008 | Output inspector with filters for low confidence, human override, judge flag, council disagreement, guardrail fire, regeneration | P1 |
| FR-1009 | No console panel queries a raw event table; all read pre-computed hourly rollups | P1 |

### 5.10 Community surface (Phase 8)

| ID | Requirement | Priority |
|---|---|---|
| FR-901 | Interest-based groups with join/leave and threaded posts | P1 |
| FR-902 | Rich resident profiles with explicit per-field visibility controls | P1 |
| FR-903 | Marketplace listings with photos, categories, and resident-to-resident messaging | P1 |
| FR-904 | Manager-vetted service/vendor directory with ratings and review moderation | P1 |
| FR-905 | Amenity booking with conflict detection and cancellation policy | P2 |
| FR-906 | Every user-generated surface has report/moderation tooling before it ships publicly | P0 |

---

## 6. Non-functional requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | Ticket acknowledgment latency | 99.9% < 1s |
| NFR-02 | Triage decision available | 99% < 30s; p50 < 6s |
| NFR-03 | P0 detection to human paged | 99.9% < 60s |
| NFR-04 | Workflow completion without unhandled error | ≥ 99.5% |
| NFR-05 | Cross-tenant data exposure | **Zero.** Tested in CI on every endpoint |
| NFR-06 | Blended inference cost per ticket | < $0.05 |
| NFR-07 | LLM calls on the critical path | ≤ 5 |
| NFR-08 | Accessibility | WCAG 2.2 AA on all three surfaces |
| NFR-09 | Mobile support | Resident + tech surfaces usable at 360px width |
| NFR-10 | Graceful degradation | System accepts tickets and acknowledges residents with **zero** model providers available |
| NFR-11 | Data retention | Tickets 7y, media 2y, raw prompts 90d then digest-only, audit 7y |
| NFR-12 | Time to local dev environment | One command, under 10 minutes, offline-capable |
| NFR-13 | Tool payload ceiling into any prompt | ≤ 1,200 tokens per tool result, with an explicit truncation marker when trimmed — never silent |
| NFR-14 | Time to first streamed token | p50 < 1.5s — perceived latency, measured separately from completion |
| NFR-15 | Remote shield timeout | 250ms, then proceed on the local verdict and log `shield_degraded` |
| NFR-16 | Demo cold start | API service stays warm (`min-instances=1`); all other services may scale to zero |
| NFR-17 | Ops console load | Full console renders in < 2s at p95; panels read rollups, never raw events |
| NFR-18 | Rollup freshness | Hourly buckets, ≤ 10 min lag behind live |
| NFR-19 | Console access | `admin` role only; `manager`/`owner`/`resident` tokens receive 403, asserted in CI |

---

## 7. Success metrics

### 7.1 Model / system quality (published in `docs/evals/REPORT.md`)

| Metric | Target | Gate |
|---|---|---|
| P0 recall | ≥ 0.99 | Hard, no regression tolerance |
| Priority macro-F1 (P1–P3) | ≥ 0.85 | 0.02 tolerance |
| Trade routing accuracy | ≥ 0.90 | 0.03 tolerance |
| Chargeback accuracy | ≥ 0.92 with abstention | 0.03 tolerance |
| Groundedness | ≥ 0.95 | 0.02 tolerance |
| Fair-housing violations reaching a user | **0** | Hard fail |
| Escalation precision | ≥ 0.60 | 0.05 tolerance |
| Calibration error (ECE) | ≤ 0.08 | Report only |
| Council lift over solo (priority F1) | > 0 | **If ≤ 0, Council is cut** |
| Blended cost/ticket | < $0.05 | Hard |
| p95 decision latency | < 20s | Hard |

### 7.2 Product metrics (once real usage exists)

Human override rate and its reason distribution · reopen rate · first-time-fix rate · SLA compliance by category · time-to-decision · resident CSAT (2-question post-close) · manager queue clear time.

### 7.3 Project metrics (the ones that matter before customers)

Week-4 live demo shipped · public eval report with real numbers including misses · trace replay working · zero fabricated metrics anywhere in the repo or in any resume.

---

## 8. Designed but deferred

### 8.1 Health & Community Wellness Agent (Phase 9)

A resident engagement and retention system: interest graph → candidate generation → feasibility filter (amenity, weather, staff capacity) → slot optimizer → LLM planner for run-of-show and copy → notification engine → attendance capture → reflection.

**Hard constraints, enforced in the schema rather than in policy prose:**
- **No health data is stored.** Participation in an event is storable; anything inferential about a resident's health is not. The columns do not exist.
- Health-adjacent events (donation drives, screening camps) are opt-in only, with aggregate-count analytics only.
- Every targeting rule passes the same fair-housing guardrail as leasing copy. Familial status, disability, and religion are protected classes; an activity recommender that quietly stops inviting someone is digital steering with a friendly UI.

### 8.2 Autonomy dial (Phase 9+)

Per decision class, per org: `disabled | propose | auto_under_threshold | auto`. Unlocking `auto` requires 30-day measured accuracy above the org's configured bar **and** a reversibility check on the action.

---

## 9. Release criteria

**Phase 5 (MVP / recruiter checkpoint) ships when all are true:**

1. A stranger with the demo link can submit a ticket, watch the reasoning stream, see citations, approve in the manager console, and read the audit record — without any assistance.
2. `docs/evals/REPORT.md` contains real numbers from a committed eval run, with the git SHA, and includes at least one metric we did not hit plus why.
3. CI fails on a deliberately-broken prompt, and the failure message is readable.
4. The red-team fair-housing suite passes with zero violations.
5. Cross-tenant tests pass for every endpoint.
6. Killing all model API keys degrades to rules-only mode rather than erroring.
7. `DEMO_MODE` demonstrably blocks all outbound channels.
8. Nothing in the repo, README, or any resume claims a number that cannot be reproduced from a committed run.

---

## 10. Open product questions

Track these here; move to `MEMORY.md` decision log when resolved.

| # | Question | Owner | Needed by |
|---|---|---|---|
| Q1 | Do we ship the community surface for the builder pitch, or stay maintenance-only for the hiring pitch? | Vishal | Phase 6 |
| Q2 | Which jurisdictions do we encode SLA tables for at launch? (VA/MD/DC proposed) | Vishal | Phase 2 |
| Q3 | Does the resident surface disclose "AI-assisted" on every message, or once at onboarding? Some states are moving toward mandatory chatbot disclosure | Vishal | Phase 4 |
| Q4 | Do we integrate a real PMS read-adapter in Phase 7, or stay standalone through v1? | Both | Phase 7 |
| Q5 | Marketplace: do we allow resident-to-resident payments at all, or listings only? (Listings only proposed) | Friend | Phase 8 |
