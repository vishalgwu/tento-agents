# 01 — Strategy & Product

---

## 1. The YC problem statement

> **Apartment operators run a $5.1 trillion asset class on software that records work but does not do it.**

Write it the way YC wants it — specific, falsifiable, with a number:

**Problem.** A US apartment portfolio generates roughly **3.3 maintenance requests per unit per year** at roughly **$200 per request** — about **$660 per unit per year** in ongoing maintenance spend before any capital work. A 500-unit property is therefore processing ~1,650 tickets a year through a workflow that is still, in 2026, a human reading free text and guessing: how urgent is this, who pays for it, who should go, and what will they need when they get there.

Guess wrong in one direction and you send a licensed plumber on a $150 truck roll to reset a garbage disposal. Guess wrong in the other and a no-heat call sits for three days in January, which in California, New York, Texas, and Illinois is not a customer-service problem — it's a habitability statute with rent abatement attached.

**Why now.**
1. Multifamily AI adoption crossed from curiosity to default in about 24 months; operators report measurable OpEx reduction and lead-to-lease improvement, and a large majority say they've already lost business to AI-enabled competitors. The buyer no longer needs to be convinced that AI belongs in the building.
2. The incumbents are shipping AI *inside* their own suites (Entrata's ELI+ and its resident-facing maintenance triage, AppFolio's Realm-X, HappyCo's Joy AI). That's validation, and it's also a clock.
3. Regulation arrived faster than the tooling. HUD's 2024 guidance put AI screening and advertising squarely inside Fair Housing. Private fair-housing nonprofits — which handle the large majority of housing discrimination complaints, far more than HUD itself — now run automated protected-class testing against live leasing bots remotely and at scale. ADA digital-accessibility filings surged in 2025 toward ~5,000, with a large share filed by self-represented plaintiffs using AI to draft complaints. Twelve state AGs are pursuing AI discrimination claims. Colorado's AI Act reaches "consequential decisions" including tenant screening.

That third point is the interesting one, and it is the whole strategy: **the industry is deploying ungoverned AI into a domain with strict liability and an active, well-equipped plaintiff's bar.** Every operator who bought a leasing bot in 2025 now owns an evidence-generation machine they cannot audit.

**Insight.** In a regulated vertical, the durable product is not the smartest model. It is the **defensible decision record**. We are not selling automation. We are selling automation *you can prove was fair* — with the citation, the policy version, the confidence score, the guardrail verdict, and the human approval attached to every action.

**One-liner.** *Resident OS is the AI operations layer for apartment communities — it runs the maintenance loop end to end, and every decision it makes comes with its receipts.*

---

## 2. Customer segments

| Segment | Doors | Who signs | Pain | Why they'd buy us | Why they wouldn't |
|---|---|---|---|---|---|
| **A. Mid-market operators (1k–15k units)** — *beachhead* | 1k–15k | VP of Operations / Regional Manager | Understaffed offices, 2 techs for 400 units, no maintenance data discipline, no in-house AI or legal capacity | They cannot build this and cannot afford a $250k enterprise deal. Compliance exposure is real and uninsured. | They're conservative buyers; procurement is slow; they need a reference customer |
| **B. Institutional operators (15k+)** | 15k+ | CTO / Chief Ops Officer | Already have EliseAI or Entrata AI, now need governance, audit, and consistency across submarkets | We're the governance layer over the AI they already bought | Long sales cycles, security review, they may build it |
| **C. Builder / developer-operators (esp. India, Gulf, LatAm)** — *your existing plan* | 500–20k | Founder / Head of Sales | Selling "smart community" as a differentiator; post-handover community operations are chaos | Community + AI in one product; no incumbent PMS lock-in; greenfield data | Willingness to pay is lower; feature-driven RFPs |
| **D. Third-party managers** | Varies | Owner-relations lead | Must prove performance to owners monthly | Owner dashboard is a retention weapon | Thin margins |
| **E. Single-asset / small landlords** | <300 | Owner | Everything | Self-serve, low ACV | Bad economics for an agentic product; **explicitly not a target** |

**Beachhead: A.** Big enough that maintenance volume creates signal, small enough to sell to a human in two calls, and it's the segment where "we can't afford a fair-housing lawsuit" is a founder-level fear rather than a line item in a legal budget.

**Wedge motion:** land on maintenance (operational, low political risk, obviously measurable), expand to resident communications and lease Q&A (where the compliance value is highest), then to owner reporting (where the money is).

---

## 3. Competitive analysis

### 3.1 The four layers of the market

```
LAYER 4  Vertical AI apps          EliseAI, Funnel, Zuma, LetHub, Colleen, Leasey
         (leasing, collections)    → conversation-first, leasing-lifecycle-first

LAYER 3  PMS-native AI             Entrata ELI+, AppFolio Realm-X, Yardi Virtuoso,
         (bundled into the suite)  HappyCo Joy → distribution advantage, shallow depth

LAYER 2  Systems of record         Yardi, Entrata, RealPage, AppFolio, Buildium, MRI
         (the ledger)              → own the data, move slowly, integration-hostile

LAYER 1  Point ops tools           CMMS (Oxmaint, Lula), smart-home, access control,
                                   package lockers
```

**Where we sit:** a horizontal *decision and governance* layer across 1–3, entered through maintenance. Not a system of record. Not a chatbot.

### 3.2 Head-to-head

| Competitor | What they're great at | Structural weakness we exploit |
|---|---|---|
| **EliseAI** (~$2.2B valuation, $250M Series E, 350+ enterprise customers, 70% of the 50 largest US residential operators, $100M+ ARR) | Conversation across text/email/chat/voice; leasing funnel; enterprise distribution | Conversation-first. The unit of work is a *message*, not a *decision with a policy basis*. Auditability of "why did the model say that" is not the product. Also: their footprint is now a compliance liability surface for their customers — every reply is a fair-housing event. |
| **Funnel Leasing** | Centralized "single guest card" architecture, portfolio-level renter identity | Leasing-only philosophy; operations after move-in is not their model |
| **Entrata ELI+ / AppFolio Realm-X** | Distribution — it's already in the PMS; ELI+ ships resident-facing maintenance triage | Suite AI is deliberately shallow and locked to their data. No cross-PMS story. Operators with mixed portfolios (extremely common) get nothing. |
| **Yardi / RealPage** | The ledger. Everyone's data lives here. | Innovation cadence; RealPage's antitrust exposure over algorithmic pricing has made "black-box AI decision" a board-level dirty phrase in this industry — which is *tailwind for an auditability-first entrant* |
| **CMMS point tools (Lula, Oxmaint, HappyCo)** | Work-order execution, vendor networks, mobile tech workflows | Triage is rules-based or human. They own the *after*; we own the *decide*. Strong partnership/acquisition surface. |
| **Generic agent platforms (Sierra, Decagon, Forethought)** | Horizontal customer-service agents, strong infra | No housing domain model, no fair-housing guardrails, no unit/asset ontology. Their compliance story is generic; ours is statutory. |

### 3.3 The honest competitive truth

You are a solo engineer (plus one) with no customers building in a category with a $2.2B incumbent. Two things follow.

1. **Do not claim you will beat EliseAI.** Claim the thing that's actually true: *the category is being built conversation-first, and the regulated future belongs to decision-first systems with audit trails.* That's a defensible thesis, and it's the one a YC partner will actually engage with.
2. **The realistic outcomes are (a) a wedge business in an underserved segment, (b) an acquisition surface for a CMMS or PMS, or (c) the best AI-engineering portfolio in your applicant pool.** All three are served by the same 12 weeks of work. Optimize for the intersection.

### 3.4 Moat, honestly assessed

| Claimed moat | Real? | Verdict |
|---|---|---|
| Better prompts | No | Copied in a week |
| Multi-agent architecture | No | Architecture is not a moat; it's table stakes by 2027 |
| Fair-housing guardrail library + eval suite | **Partially** | The *content* — the labeled probe set, the statutory rule mapping per jurisdiction — compounds and is genuinely tedious to rebuild |
| Decision-audit format that survives discovery | **Yes, if adopted** | If an operator's counsel standardizes on your record format, you're in the compliance workflow |
| Outcome data (which dispatch decisions actually resolved first-time) | **Yes, with scale** | Classic data flywheel; requires customers, so it's a Year-2 moat not a Day-1 one |

Say this out loud in the pitch. Founders who name their non-moats are more credible than founders who claim five.

---

## 4. Product vision

**Three-year arc:**

- **Year 1 — Decide.** The AI proposes; the human approves. Every decision is grounded and logged. Value = fewer misroutes, faster P0 response, a compliance record that didn't exist before.
- **Year 2 — Act.** Auto-execution for decision classes whose measured accuracy and reversibility clear a bar the operator sets. Not "we turned on autonomy," but "you may enable auto-dispatch for P3 in-house jobs under $150 once the 30-day measured accuracy exceeds 97%." Autonomy becomes a **dial with an evidentiary threshold**, which is both safer and a far better sales conversation.
- **Year 3 — Orchestrate.** Cross-workflow coordination: maintenance history informs renewal risk, informs turn cost forecasting, informs capital planning. The system is now the operating layer, and the PMS is a ledger it writes to.

**The vision sentence:** *Every apartment community runs on a brain that knows the building, follows the rules, shows its work, and asks for help when it isn't sure.*

That last clause is the product. Anyone can build a confident agent. Calibrated abstention is hard and it's what operators actually need.

---

## 5. MVP definition

### 5.1 Scope: the Maintenance Loop

**In:**
1. Multi-modal intake — resident submits text, photo, or voice.
2. Deterministic life-safety screen (gas, fire, flood, electrical, CO, no-heat/no-cool in extreme weather, lockout with a minor, sewage).
3. Structured extraction — category, symptom, affected asset, access permission, pet-on-premises, preferred window.
4. Grounded diagnosis — retrieval over SOPs, the unit's own history, asset records, warranty status.
5. Decision bundle — priority (P0–P3), responsible party (owner vs resident chargeback), trade/skill, in-house vs vendor, expected parts, time estimate, SLA deadline.
6. Policy audit — habitability SLA check, chargeback rules from the actual lease, fair-housing/ADA screen on any resident-facing text, PII redaction before anything leaves the boundary.
7. Human approval gate for anything expensive, chargeable, irreversible, or P0.
8. Actions — create work order, notify vendor, notify resident with a plain-language, citation-backed explanation.
9. Judge + eval logging on 100% offline / sampled online.
10. Three surfaces — resident app, manager console with the approval queue, owner read-only dashboard.

**Out (v1):** payments, lease generation, screening/applications, tour scheduling, move-in/move-out vision, package intelligence, energy optimization, fraud detection, marketplace, wellness. Rationale in §9.

### 5.2 Why *this* workflow — the argument that matters

Most people choose an MVP workflow by pain. That's necessary but not sufficient. Choose by **ground-truth availability**, because an AI product you cannot measure is a demo with a subscription.

| Criterion | Maintenance triage | Leasing chat | Lease Q&A | Renewals |
|---|---|---|---|---|
| Frequency | ~3.3/unit/yr — high, continuous | Seasonal, funnel-dependent | Sporadic | 1/unit/yr |
| Is the correct answer knowable *after the fact*? | **Yes** — vendor accept/reject, reopen rate, human re-classification, first-time-fix | Weakly — lease conversion is noisy and slow | Rarely | Slowly |
| Cost of error, quantified | $150 wrong truck roll; habitability exposure on the other side | Lost lead; fair-housing exposure | Wrong advice → dispute | Churn |
| Regulatory blast radius on day 1 | Moderate (habitability, ADA reasonable accommodation) | **Severe** (steering, disparate impact) | High | Moderate |
| Does an incumbent already own it? | Partially (Entrata ELI+) | **Heavily** (EliseAI et al.) | Partially | Partially |

Maintenance wins on the axis nobody optimizes for: **you get labels for free.** Every human override in the approval queue is a training and eval label. That's a self-improving system by construction, and it's the single best thing you can say about this architecture in an interview.

Secondary reason: it's the *lowest-risk place to be wrong while you learn*. Getting a leasing reply wrong on day one is a protected-class incident. Getting a priority wrong on day one is a queue-ordering error caught by a human who's standing right there.

### 5.3 MVP success criteria (measured on a human-labeled golden set, published)

| Metric | Target | Why this number |
|---|---|---|
| Life-safety recall (P0 detection) | **≥ 0.99**, precision ≥ 0.70 | Asymmetric. Missing a gas leak is unbounded; a false P0 costs one phone call. Deliberately over-trigger. |
| Priority classification (macro-F1, P1–P3) | ≥ 0.85 | Above the consistency humans achieve with each other |
| Trade/skill routing accuracy | ≥ 0.90 | Directly maps to truck-roll savings |
| Chargeback determination accuracy | ≥ 0.92, with **abstention on ambiguity** | Money + tenant relations; abstain rather than guess |
| Groundedness (claims traceable to a retrieved citation) | ≥ 0.95 | Core anti-hallucination metric |
| Fair-housing / ADA guardrail violations reaching a resident | **0** on the red-team set | Non-negotiable |
| Escalation precision | ≥ 0.60 | Escalating everything is not a system |
| Cost per ticket (blended) | < $0.05 | Proves the routing story |
| p50 / p95 latency to decision | < 6s / < 20s | Manager-console usability |

**Publish the ones you miss too.** An eval report with three red numbers and an explanation of why is far more credible than five green ones.

---

## 6. User journeys

### 6.1 Priya, resident, 11:40pm — "water under the sink"

1. Opens the app, types *"there's water under my kitchen sink and it smells bad,"* attaches a photo, taps send.
2. **< 1s:** confirmation with a ticket number. Non-negotiable — perceived responsiveness is the product to a resident, and it must not wait on an LLM.
3. **Background:** safety screen (sewage smell + standing water → escalate from P3 to P2, not P0 — no gas/electrical indicator). Vision pass on the photo describes standing water and a corroded P-trap. Retrieval pulls unit 4B's two prior kitchen plumbing tickets in 14 months and the SOP for recurring drain issues.
4. **Diagnosis:** recurring failure pattern → recommends a full trap replacement, not another snake. Chargeback: owner (wear, not misuse — cites lease §7.3 and the two prior tickets).
5. **Resident sees:** *"We've got this as urgent — a plumber will be scheduled before 10am tomorrow. Please avoid using the sink tonight and put a towel down if there's active dripping. There's no charge to you for this repair."* Every factual claim in that message maps to a retrieved citation ID.
6. **7:15am:** reminder with the tech's ETA and name. **Post-close:** two-question feedback, which becomes an eval label.

**Design note:** the resident never sees a confidence score, a model name, or the word "AI" beyond a required disclosure. Residents want their sink fixed.

### 6.2 Marcus, property manager, 8:05am — the approval queue

Opens the console to **11 items awaiting approval**, ordered by SLA risk, not by arrival time.

Each card is one screen:

```
┌──────────────────────────────────────────────────────────────┐
│ #4471 · Unit 4B · Kitchen plumbing            SLA: 13h left  │
│ P2 · Vendor: Delta Plumbing · Est. $180 · Owner-billed       │
│                                                              │
│ Why: 3rd kitchen drain ticket in 14 months (#3102, #3877).   │
│ SOP-PLM-04 says escalate to trap replacement after 2 repeats.│
│ Lease §7.3: normal wear → owner responsibility.              │
│ Confidence 0.91 · Council: not triggered · Guardrails: pass  │
│                                                              │
│ [Approve] [Approve & edit] [Reassign] [Reject ▾]  [Trace ▸]  │
└──────────────────────────────────────────────────────────────┘
```

**Every button is a labeled training example.** "Reject" opens a two-click reason taxonomy (wrong priority / wrong trade / wrong party / policy misread / other). That taxonomy is your eval dataset, generated by the user doing their job. This is the most important UI decision in the product.

`Trace ▸` opens the full replay: retrieved chunks with scores, prompt version hash, model, guardrail verdicts, council transcript if it ran, judge scores, token cost. That panel is also your recruiter demo.

### 6.3 Dana, asset owner, month-end

Read-only: cost per unit vs portfolio, preventive-vs-reactive ratio, SLA compliance by property with the habitability-relevant categories broken out, top recurring-failure units with a capital-replacement recommendation, and an **AI Governance tab**: decisions made, auto vs approved vs overridden, override reasons, guardrail events, and an exportable audit bundle for a date range.

That governance tab is what makes an institutional buyer take a second meeting. Nobody else ships it.

### 6.4 Ravi, vendor

SMS with a signed link — no login. Job, address, access notes, photos, parts hint, accept/decline with a reason. Decline reasons feed vendor reliability scoring, which feeds the next dispatch decision. Closed loop, no app to install, works on a flip phone if it has to.

---

## 7. Roadmap

| Phase | Window | Ships | Proves |
|---|---|---|---|
| **P0 — Spine** | Weeks 1–4 | Maintenance loop v0, three surfaces, hybrid RAG, guardrails, audit log, deployed | The architecture works end to end |
| **P1 — Measured** | Weeks 5–8 | Golden set + eval harness in CI, Council Mode, Judge, observability + cost dashboards, red-team suite | The system is *measurable* — the part 95% of portfolio projects skip |
| **P2 — Community** | Weeks 9–12 | Notification engine, resident community surface, marketplace, vendor directory, amenity booking | It's a product a builder would buy |
| **P3 — Expand** | Q4 2026 | Lease AI (policy Q&A with citations), renewal risk, owner reporting automation, PMS read-adapters (Yardi/AppFolio) | Multi-workflow platform |
| **P4 — Autonomy dial** | 2027 | Threshold-gated auto-execution, vendor marketplace, wellness & engagement, move-in/out vision | The original vision, earned |

---

## 8. Deep design: the two modules you explicitly asked for

### 8.1 Health & Community Wellness Agent (Phase 4 — designed now, built later)

**Reframe first.** This is a *resident engagement and retention* system. Retention is the highest-ROI metric in multifamily — turnover costs are measured in thousands of dollars per unit — so the business case is real. But it is fundamentally a **recommendation + scheduling + operations loop with a thin LLM layer**, and pretending otherwise would weaken the architecture.

**Architecture:**

```
Interest graph (residents × activity tags, explicit opt-in at onboarding)
        ↓
Candidate generation ─── popularity prior + co-participation collaborative filter
        ↓                (cold start: property demographics → activity priors)
Feasibility filter ────── amenity availability, weather forecast, staff/vendor
        ↓                capacity, quiet hours, permit needs
Slot optimizer ────────── constraint solve over (activity × slot × space),
        ↓                objective = predicted attendance − conflict penalty
LLM Planner ───────────── produces the run-of-show, supply list, safety notes,
        ↓                and invite copy from an approved template
Notification engine ───── invites, RSVP, reminders, day-of weather change
        ↓
Attendance capture ────── QR check-in / staff tap
        ↓
Reflection ────────────── "Sunday 7am run club: 4 invites, 1 attendee, 3 weeks
                          running → propose 8am or retire" — proposed, not
                          auto-applied
```

**Agent split and why:**

| Agent | Owns | Why it's separate |
|---|---|---|
| Interest Matcher | resident ↔ activity affinity | Pure ranking; needs no policy context and must never see PII beyond an ID |
| Scheduler | slot/space/staff feasibility | Deterministic constraint problem; an LLM here would be strictly worse and non-reproducible |
| Planner (LLM) | run-of-show, supplies, invite copy | Genuinely generative; low blast radius |
| Analytics | participation trends, timing recommendations | Batch, offline, cheap model |
| Notification | delivery | Shared infrastructure — see 8.2 |

**The privacy design that most teams get wrong.** Your examples include blood-donation drives and health-checkup camps. **Do not build a health profile.** Store `participated_in(event_id)` and nothing inferential. Never write "resident has a health condition," never target invitations using anything that could function as a health proxy, and keep health-adjacent events opt-in-only with no attendance analytics beyond aggregate counts. Two reasons: it's the right thing to do, and a wellness feature that quietly builds health profiles of residents is a headline. Write this constraint into the schema (no health-attribute columns exist) rather than into a policy doc, so it can't drift.

**Fair-housing note:** familial status, disability, and religion are protected classes. An "activity recommender" that stops inviting a resident to community events after it infers they have young children or a mobility limitation is **digital steering with a friendly UI**. Every targeting rule in this module goes through the same fair-housing guardrail as leasing copy. This is a genuinely non-obvious risk and calling it out is worth points with any serious reviewer.

### 8.2 Smart Notification Platform (MVP-lite in P0, full in P2)

**Core principle: the LLM writes; the policy engine decides.** An LLM must never determine whether a human is woken at 2am.

```
Event ──▶ [1] Eligibility     · does this recipient have standing to receive it?
                              · consent, role, unit scope, opt-outs
          [2] Classification  · deterministic type → urgency tier (U0–U3)
          [3] Timing          · quiet hours by tier; U0 overrides everything
          [4] Dedupe/Batch    · collapse same-entity events within window
          [5] Fatigue budget  · token bucket per recipient per tier per week
          [6] Channel ladder  · push → email → SMS → voice, tier-dependent
          [7] Render          · LLM fills an approved template; guardrails run
                                on the OUTPUT before send
          [8] Deliver         · idempotent, provider-abstracted
          [9] Receipt/Retry   · ack window per tier; escalate on timeout
         [10] Escalation      · U0 unacked in 10m → next in chain → on-call
```

| Tier | Examples | Quiet hours | Channels | Retry / escalation | Fatigue budget |
|---|---|---|---|---|---|
| **U0 Life safety** | Gas, fire, flood, evacuation, security | **Ignored** | Push + SMS + voice, simultaneous | 2m, then escalate through chain | Exempt |
| **U1 Urgent ops** | P0/P1 work order, access issue, utility shutoff | 7am–10pm, defer with a floor | Push + SMS | 15m ×2 | 5/week |
| **U2 Transactional** | Ticket status, package, rent due, tech ETA | 8am–9pm | Push, email digest fallback | 1 retry | 12/week |
| **U3 Engagement** | Events, marketplace, community, surveys | 10am–8pm | Push, batched | None | 3/week, hard cap |

**Fatigue prevention, concretely:** a per-recipient token bucket per tier. When U3 is exhausted, notifications are *dropped and logged as suppressed*, not queued — a queue just delays the annoyance. High tiers preempt low ones: if a U1 fires within 30 minutes of a scheduled U3, the U3 is dropped, because attention is the scarce resource, not delivery capacity.

**Why the LLM is boxed in:** copy generation is the only stage with model involvement, it runs against a template with fixed slots, and the output passes PII redaction + fair-housing screening *before* delivery. A model that hallucinates a rent amount into a notification is a legal event; a template with a validated numeric slot cannot.

---

## 9. Excluded from MVP — with rationale

Cutting is the hardest and most senior part of this document. Each cut names the *specific* reason, because "we'll do it later" is not a rationale.

| Module | Verdict | Rationale |
|---|---|---|
| **Lease AI (policy Q&A)** | Phase 3 | Technically the *easiest* win (it's RAG over a document) and therefore the least differentiating — and its error mode is direct legal advice to a resident. Ship it after the guardrail and eval infrastructure exists to make it safe. |
| **Move-in / move-out vision** | Phase 4 | Requires paired before/after imagery under uncontrolled lighting to be worth anything, and the deliverable is a *deposit deduction* — a dispute-generating financial decision. Demo-friendly, product-hostile. |
| **Package intelligence** | Cut | Solved by hardware vendors (Luxer, Fetch, Amazon Hub). No AI depth, no defensibility. Building it signals you chase features instead of judgment. |
| **Marketplace** | Phase 2 (community surface) | Genuine product value in your builder segment and a two-sided liquidity problem. Ship it as CRUD + trust/ratings. It contributes ~0 to the AI-engineering story, so do not let it consume AI weeks. |
| **Vendor intelligence** | Partial in MVP | Scoring exists (accept rate, first-time fix, reliability) because dispatch needs it. A full vendor-management product is out. |
| **Complaint resolution** | Phase 3 | Neighbor disputes carry defamation and discrimination risk and have almost no ground truth. Worst measurability-to-risk ratio in your list. |
| **Fraud detection** | Cut for MVP | Application fraud detection is an adverse-action decision under FCRA and a disparate-impact minefield. **Do not build a screening or fraud model as a solo founder with no compliance counsel.** This is the one item on your list I'd argue against building at all before Series A. |
| **Energy optimization** | Phase 4 | Needs IoT/BMS integration you don't have. Nothing to demo without hardware. |
| **Analytics platform** | Thin in MVP | The owner dashboard covers the demo need. A full BI product competes with tools that already exist. |
| **Wellness agent** | Phase 4 | See 8.1. Designed now, built when there are residents to engage. |
| **Payments / rent** | Cut | Money movement means PCI, KYC, escrow, and state-by-state trust-accounting law. Integrate Stripe later; never touch funds directly. |
| **Voice channel** | Phase 3 | Real-time voice adds latency budgets, telephony, and recording-consent law that varies by state. Excellent Phase-3 differentiator, terrible MVP scope. |
| **Knowledge Graph RAG** | Deferred, likely permanently | The "graph" here — org → property → building → unit → asset → work order → vendor — is a *relational* structure with clean foreign keys. Postgres already models it, joins are exact, and no embedding can beat a join for "what water heater is in 4B." Adding Neo4j would be architecture cosplay. Revisit only if free-text entity linking across leases and vendor contracts becomes a real retrieval need. |

**A note on the module list itself.** Sixteen modules in a founding document reads to an experienced investor as *"this team has not chosen."* The strongest version of your pitch names all sixteen as the map, then says: "we're building one of them to a depth nobody has, because that's how you earn the right to build the other fifteen." That framing turns your scope problem into evidence of judgment.
