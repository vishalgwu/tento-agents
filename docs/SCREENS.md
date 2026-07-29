# SCREENS.md — Build Reference

**Every screen in Resident OS, specified enough to build from.**
Owner: Track B (Surface), with data bindings owned by Track A
**Related:** `DESIGN.md` (tokens and language) · `PRD.md` (requirement IDs) · `PHASES.md` (when each ships) · `DEMO.md` (the click path)

> How to use this file: each screen has a wireframe, a component list, its **data bindings** (which table or endpoint feeds each element), its states, and acceptance criteria. If you are driving Claude Code, point it at the individual screen section rather than the whole file.

**Legend used in wireframes**

```
●  filled status lamp        ○  hollow lamp (unclassified)
◆  decider diamond — machine blue / human brass
[C1] citation chip           ⚑  guardrail hit
▸ ¶ § ·  authority glyphs — SOP / lease / statute / vendor contract
```

---

## Screen index

| # | Screen | Surface | Phase | Requirement |
|---|---|---|---|---|
| 1 | Landing / demo entry | public | 5 | — |
| 2 | Resident home | resident | 3 | — |
| 3 | Report an issue | resident | 3 | FR-101…107 |
| 4 | Resident ticket detail | resident | 3 | FR-701 |
| 5 | Resident notifications | resident | 8 | FR-801…806 |
| 6 | Manager approval queue | manager | 3 | FR-601…604 |
| 7 | Trace viewer | manager | 5 | FR-702, FR-703 |
| 8 | Retrieval inspector | manager | 5 | FR-302 |
| 9 | Council view | manager | 6 | FR-308…310 |
| 10 | Context budget | manager | 6 | — |
| 11 | Knowledge browser | manager | 2 | FR-502 |
| 12 | Governance tab | manager | 4 | FR-704, FR-705 |
| 13 | Agent health | manager | 6 | — |
| 14 | Cost dashboard | manager | 5 | NFR-06 |
| 15 | Eval dashboard | manager | 5 | §7.1 |
| 16 | Gateway dashboard | manager | 7 | — |
| 17 | Memory review | manager | 6 | — |
| 18 | Owner monthly dashboard | owner | 4 | FR-705 |
| 19 | Tech job card | tech | 3 | FR-401 |
| 20 | Vendor accept/decline | vendor | 3 | FR-404, FR-405 |
| 21 | Compliance block | manager | 4 | FR-504, FR-508 |
| 22 | Degraded mode banner | all | 3 | NFR-10 |

---

## 1 · Landing / demo entry

**Job:** get a stranger into a live demo in under 15 seconds, with no form.

```
┌──────────────────────────────────────────────────────────────┐
│  Resident OS                                    GitHub  Docs │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   Apartment operations that show their work.                 │
│   Every decision comes with its receipts.                    │
│                                                              │
│   ┌────────────────────────────────────────────────────┐     │
│   │  LIVE TRACE — replaying a real seeded run          │     │
│   │  ✓ screening for safety            24ms            │     │
│   │  ✓ retrieving policy · 6 sources  201ms            │     │
│   │  ● council triggered · 3 members  2.1s             │     │
│   │  ○ auditing against lease 7.3                      │     │
│   └────────────────────────────────────────────────────┘     │
│                                                              │
│   [ Enter as resident ] [ as manager ] [ as owner ]          │
│   Synthetic property · 412 units · 1,200 historical tickets   │
├──────────────────────────────────────────────────────────────┤
│   One architecture diagram                                   │
│   Eval table — every number, including the misses            │
│   The compliance block, in 15 seconds                        │
└──────────────────────────────────────────────────────────────┘
```

**Hero rule:** the hero is the product doing its one trick — an auto-playing (muted, reduced-motion-safe) trace replay. Not a big number with a gradient.

**Data:** `GET /v1/runs/{seed_run_id}` replayed client-side from a recorded event fixture, so the landing page never depends on a live model call.

**States:** reduced-motion → static completed trace. JS disabled → static screenshot.

**Acceptance:** a first-time visitor reaches a working manager console in ≤ 2 clicks with no signup.

---

## 2 · Resident home

**Job:** answer "is my thing being handled" in one glance, then get out of the way.

```
┌─────────────────────────────────────┐
│  Good evening, Priya                │  display-l
│  Riverside · Unit 4B                │  mono, muted
├──────────────────┬──────────────────┤
│                  │  ● P2            │
│  REPORT AN       │  Kitchen sink    │  ← tallest tile
│  ISSUE           │  Plumber before  │    = most attention
│                  │  10am tomorrow   │
│  (large tap)     │  [Track]         │
├──────────────────┴──────────────────┤
│  This week at Riverside             │
│  ┌──────┐ ┌──────┐ ┌──────┐         │  horizontal scroll
│  │ Run  │ │Movie │ │ Yoga │         │
│  └──────┘ └──────┘ └──────┘         │
├──────────────────┬──────────────────┤
│  Marketplace  →  │  Amenities   →   │
└──────────────────┴──────────────────┘
```

**Why asymmetric bento:** tile size encodes priority of attention. A uniform grid would say the community events matter as much as the open plumbing ticket. They do not.

**Data bindings**

| Element | Source |
|---|---|
| Greeting, unit | `people`, `tenancies` |
| Active ticket tile | `GET /v1/tickets?status=open&limit=1` |
| Events strip | `events` (Phase 9; hide the strip entirely before then) |
| Marketplace / amenities | Phase 8 — render as disabled tiles before then |

**States:** no open ticket → the report tile expands to full width. New resident, no history → same, plus a one-line welcome.

---

## 3 · Report an issue

**Job:** submitted in under 30 seconds, three taps, no dropdowns.

```
STEP 1  What's wrong?
┌──────────┬──────────┬──────────┐
│  Water   │ Heat &   │  Power   │   large tiles, plain language
├──────────┼──────────┼──────────┤
│ Appliance│  Pests   │ Something│
│          │          │  else    │
└──────────┴──────────┴──────────┘
[ Tell us more                    ]

STEP 2  Show us
[ camera-first sheet · up to 5 photos ]
[ ◉ hold to record · 30s max          ]

STEP 3  Access
Can we enter if you're out?   ( Yes ) ( No )
Pets in the apartment?        [ toggle ]
Best time                     [ morning ][ afternoon ][ evening ]

              [  Send  ]
```

**Non-negotiable (FR-102):** the confirmation with a ticket number appears in under 1 second and **never waits on a model call**. Enqueue, then acknowledge.

**Data bindings**

| Element | Source |
|---|---|
| Submit | `POST /v1/tickets` with `Idempotency-Key` header |
| Photos | signed R2 upload URL, then `ticket_media` |
| Voice | upload → transcribe in worker → `raw_text` appended, audio deleted |

**States:** offline → queued locally with a visible "will send when you're back online" chip. Upload failure → ticket still submits, media retries.

**Acceptance:** double-tapping Send creates exactly one ticket.

---

## 4 · Resident ticket detail

**Job:** show what is happening in plain language, and explain money before it is asked about.

```
┌──────────────────────────────────────────┐
│  ‹  #4471                                │
├──────────────────────────────────────────┤
│  ● P2 · URGENT                           │
│  Kitchen sink                            │
│  Reported 23 Jul, 11:40pm                │
├──────────────────────────────────────────┤
│  ┃ ✓ We received your report      11:40pm│
│  ┃ ✓ Checked against your lease   11:40pm│
│  ┃ ✓ Marked urgent — third time   11:41pm│
│  ┃      this year                        │
│  ┃ ● Plumber scheduled              7:15am│
│  ┃      Delta Plumbing · before 10am     │
│  ┃ ○ Repair                              │
├──────────────────────────────────────────┤
│  There's no charge to you for this       │
│  repair.                      [ Why? ▾ ] │
│  └ Your lease (section 7.3) puts normal  │
│    wear and tear on the owner. This      │
│    drain has been repaired twice before, │
│    so it counts as wear, not damage.     │
├──────────────────────────────────────────┤
│  [ Add a photo ]      [ Message us ]     │
└──────────────────────────────────────────┘
```

**Design rules**
- The resident sees **no** confidence score, **no** model name, **no** agent names.
- Same underlying events as the engineering trace, different vocabulary — "Checked against your lease," not "policy retrieval."
- "Why?" is collapsed by default and expands to the plain-English reason **with the lease section named**. A resident who can see why they are not being charged trusts the system.

**Data bindings**

| Element | Source |
|---|---|
| Timeline | `agent_steps` mapped through a resident-facing label map, not rendered raw |
| Charge explanation | `decisions.final.responsible_party` + the `citations` entry whose `authority = lease` |
| Vendor + window | `work_orders` |

**States:** decision still running → timeline shows completed steps with the next one pulsing. Escalated to a human → *"A team member is reviewing this"* with no fake progress.

---

## 5 · Resident notifications *(Phase 8)*

```
┌──────────────────────────────────────────┐
│  Notifications                    [⚙]    │
├──────────────────────────────────────────┤
│  ● Plumber arriving before 10am    7:15am│
│    #4471 · kitchen sink                  │
├──────────────────────────────────────────┤
│    Rent due in 3 days             Mon    │
├──────────────────────────────────────────┤
│    3 community updates            Sun    │  ← batched U3
└──────────────────────────────────────────┘

SETTINGS
Quiet hours        [ 10pm ]—[ 7am ]
Urgent overrides quiet hours    [ on, locked ]
Community updates  [ weekly digest ▾ ]
```

**Rule (FR-802):** the settings screen governs a **deterministic policy engine**. The U0 override toggle is visibly locked on — life-safety alerts are not a preference.

**Data:** `notifications`, `notification_budgets`. Suppressed items are visible to staff in the governance tab but not to residents.

---

## 6 · Manager approval queue — **the hero screen**

**Job:** clear the queue without making an expensive mistake. Marcus is here four hours a day.

```
┌────────────────────────────────────────────────────────────────────────┐
│  QUEUE  3 awaiting approval              [SLA risk ▾] [All properties] │
├────────────────────────────────────────────────────────────────────────┤
│ ●  #4471  4B · Kitchen plumbing           SLA 13h   conf 0.91      ◆   │
│    Third drain ticket in 14 months. SOP-PLM-04 escalates to trap       │
│    replacement after two repeats. Lease 7.3: normal wear, owner pays.  │
│    Delta Plumbing · est. $180 · owner-billed                           │
│    [Approve] [Edit] [Reject]                              [Trace →]    │
├────────────────────────────────────────────────────────────────────────┤
│ ●  #4468  2C · No hot water               SLA 4h    conf 0.74      ◆   │
│    ⚑ Council: members disagreed on priority                            │
├────────────────────────────────────────────────────────────────────────┤
│ ○  #4463  1A · Cabinet door               SLA 4d    conf 0.44      ◆   │
│    ⚑ Escalated — the system declined to decide                         │
└────────────────────────────────────────────────────────────────────────┘

REJECT expands →  Wrong priority | Wrong trade | Wrong party |
                  Policy misread | Other      ← the eval label taxonomy
```

**Five decisions worth defending in an interview**

1. **Sorted by SLA risk, never arrival time.** The queue exists to prevent the expensive miss.
2. **One card, one screen, no scroll.** If the manager scrolls to decide, the card is too big.
3. **The diamond changes hands.** Blue while the system owns it; brass the instant a person touches it. Consistent across every surface.
4. **Council disagreement is on the card, not three clicks deep.** Disagreement is the highest-information thing the system can tell a manager.
5. **Every button is a labelled training example.** Reject → five-option taxonomy → `decisions.override_reason`.

**Keyboard map:** `j`/`k` move · `a` approve · `e` edit · `r` reject then `1–5` for reason · `t` trace · `/` search · `?` shortcuts.

**Data bindings**

| Element | Source |
|---|---|
| Card list | `GET /v1/approvals?assignee=me` ordered by `tickets.sla_due_at` |
| Lamp + priority | `decisions.proposed.priority` |
| Reasoning line | `decisions.proposed.summary` — never the raw model output |
| Confidence | `decisions.confidence` (calibrated, not self-reported) |
| Diamond | `decisions.mode` |
| Council flag | `agent_runs.council_used` + a reviewer dissent flag |
| Approve | `POST /v1/approvals/{id}/approve` → issues a single-use `approvals.token` |

**States:** empty → *"Queue clear. 3 tickets resolved today."* Never a shrug illustration. Optimistic approve with rollback on failure.

---

## 7 · Trace viewer

**Job:** answer "why did it do that" for an engineer, a manager, or an auditor.

```
┌─ TRACE · #4471 · run 9f2c ──────────┬─ STEP DETAIL ──────────────────┐
│ guardrails.input          ▇     24ms│ Diagnostician                  │
│ safety + intake           ▇▇▇  412ms│ sonnet-5 · diagnose@v7 · a91f3c│
│ context.broker            ▇▇   338ms│                                │
│   └ retrieval.hybrid      ▇    201ms│ in 4,012 (1,000 cached)        │
│   └ memory.episodic       ▇     88ms│ out 486 · $0.0158 · 2,140ms    │
│   └ context.budget              6ms │                                │
│ council              ⚑ ▇▇▇▇▇▇ 2,140 │ EVIDENCE RAIL                  │
│   └ member.policy       ▇▇▇▇▇ 1,802 │ [C1] ▸ SOP-PLM-04 §2           │
│   └ member.history      ▇▇▇▇▇ 2,010 │ [C2] ¶ lease 4B §7.3           │
│   └ member.cost         ▇▇▇▇  1,640 │ [C3] · workorder #3877         │
│   └ council.synthesis   ▇▇▇     980 │ [F1] asset · warranty 2027-03  │
│ dispatch.planner        ▇▇      910 │                                │
│ guardrails.policy       ▇       120 │ ✓ citations 4 of 4 resolve     │
│ decision.gate                    3ms│ ✓ every figure traced          │
│                                     │ ✓ schema valid, no repair      │
│ [ Replay ]  [ Retrieval → ]         │ ✓ guardrails 15 of 15 pass     │
└─────────────────────────────────────┴────────────────────────────────┘
```

**Build notes**
- **Virtualise the tree.** Agent traces nest deeply; a tree that stutters on expand destroys debugging speed, which is the only reason this screen exists.
- **Parallel spans share a horizontal track** so "three members ran at once" is visible rather than asserted.
- Steps with no model call (`context.broker`, `context.budget`, `decision.gate`) are labelled `code`. This makes the ≤5-LLM-call budget visible, which is the single best thing to point at in an interview.
- `Replay` → `GET /v1/runs/{id}/replay` re-executes against **pinned** prompt, model, and KB versions and shows a side-by-side diff.

**Data:** `agent_runs`, `agent_steps`, `llm_calls`, `retrievals`, `guardrail_events` — one query, assembled server-side into a nested tree.

---

## 8 · Retrieval inspector

**Job:** answer "why was the wrong chunk in the window."

```
┌ BM25 ──────────┬ VECTOR ────────┬ FUSED (RRF) ───┬ RERANKED ────────┐
│ 1 SOP-PLM-04 ──┼─────────╮      │ 1 SOP-PLM-04   │ 1 SOP-PLM-04 0.94│
│ 2 lease §7.3 ──┼───╮     ╰──────┤ 2 lease §7.3   │ 2 wo #3877   0.88│
│ 3 SOP-PLM-02   │   │            │ 3 wo #3877     │ 3 lease §7.3 0.81│
│ 4 …            │ 1 wo #3877 ────┤ 4 SOP-PLM-02   │ 4 SOP-PLM-02 0.62│
│                │ 2 lease §7.3 ──╯ 5 wo #3102     │ 5 wo #3102   0.44│
│                │ 3 SOP-PLM-04   │ …              │ ─── budget cut ──│
│                │                │                │ 6 SOP-PLM-02v2   │
└────────────────┴────────────────┴────────────────┴──────────────────┘
        dense-only recall@5: 0.62   →   hybrid + rerank: 0.84
```

**The most useful element is the budget cut line.** Chunks below it are dimmed but present — what was *almost* retrieved is usually the answer to "why was this wrong."

**Data:** `retrievals.results` — store `bm25_rank`, `vec_rank`, `rrf`, `rerank_score`, and `used` per chunk at write time. If you do not store these in Phase 2, this screen cannot be built in Phase 5.

---

## 9 · Council view

**Job:** show that disagreement carries information.

```
COUNCIL · #4468 · 2C · no hot water
⚑ Members disagreed on priority

┌ POLICY ──────────┬ HISTORY ─────────┬ COST ────────────┐
│ ● P1      0.88   │ ● P2      0.61   │ ● P1      0.79   │
│ Hot water is a   │ Same unit in     │ 2019 Rheem, in   │
│ habitability     │ March. Fixed by  │ warranty to Mar  │
│ item in VA. 24h  │ pilot reset, no  │ 2027. Claim = $0,│
│ response.        │ part replaced.   │ billable = $310. │
│                  │                  │                  │
│ Sees   SOPs,     │ Sees   unit +    │ Sees   asset,    │
│        lease,SLA │        asset     │        warranty, │
│                  │        history   │        vendors   │
│ Blind  history,  │ Blind  SOPs,     │ Blind  SOPs,     │
│        cost      │        cost      │        narrative │
└──────────────────┴──────────────────┴──────────────────┘

SYNTHESIS
P1, warranty claim first, dispatch only if declined.
Priority disagreement is one level → the more urgent verdict stands
(asymmetric loss). History does not lower the statutory obligation,
but it changes the plan: try warranty before a billable technician.

Dissent, recorded not smoothed away
  History: "prior occurrence was resident-resolvable, P2 may suffice."

confidence 0.74  ├────────█████──┤  review band · approval required
calibrated on 200 items · abstain <0.60 · auto >0.85
```

**The `Blind to` line is the whole argument.** Council members differ by evidence, not persona, because same-model samples over identical context produce correlated errors — they agree confidently and wrongly. Make the blindness visible or the design reads as three personas.

**Style rule:** when members disagree, the disagreement is the **headline** of the screen, not a warning banner.

**Data:** `agent_steps` where `agent LIKE 'council.member.%'`, plus the synthesis step and the deterministic reviewer's flags.

---

## 10 · Context budget

```
8,000-token envelope · run 9f2c · 7,412 used

system + schema (cached) ████                              1,000
policy / SOP excerpts    ██████                            1,540
unit / asset facts       ███                                 690
similar cases (k=3)      █████                             1,280
conversation summary     ██                                  412
current ticket           ██                                  490
output reserve           ▒▒▒▒▒▒▒▒▒  (hatched = reserved)   2,000
                                                    unused    588
```

Hatching for reserved space is a drawing convention and reads instantly. Slots chronically at 40% utilisation are over-provisioned — reallocate them.

**Data:** envelope metadata stored on the `context.budget` step's `output`.

---

## 11 · Knowledge browser

```
┌ KNOWLEDGE ──────────────────────────────────────────────────┐
│ [ search…                    ] [ jurisdiction ▾ ] [ type ▾ ]│
├─────────────────────────────────────────────────────────────┤
│ ▸ SOP-PLM-04  Drain clearing and trap replacement      v3   │
│   internal_sop · US-VA, US-MD · effective 2025-01-01        │
│   supersedes SOP-PLM-03 · review by 2026-12-31              │
├─────────────────────────────────────────────────────────────┤
│ § habitability-sla-VA                                  v2   │
│   statute · US-VA · effective 2024-07-01                    │
└─────────────────────────────────────────────────────────────┘

PRECEDENCE  statute § > lease ¶ > internal SOP ▸ > vendor contract ·
```

Showing precedence on the screen matters: it tells a manager that a conflict between the SOP and the statute is resolved by rule, not by the model's judgment.

**Data:** `kb_documents`, `kb_chunks`. Search hits `GET /v1/knowledge/search` and returns scores, which doubles as the demo surface.

---

## 12 · Governance tab

**Job:** the screen that makes an institutional buyer take a second meeting.

```
┌ GOVERNANCE · March 2026 ────────────────────────────────────┐
│ 412 decisions                                               │
│ ████████████ auto 46% │███████ approved 32% │███ over 14% │▌8%│
├─────────────────────────────────────────────────────────────┤
│ OVERRIDE REASONS                                            │
│ wrong priority   ████████████ 24                            │
│ wrong party      ███████ 14                                 │
│ wrong trade      █████ 11                                   │
│ policy misread   ██ 5                                       │
│ other            █ 3                                        │
├─────────────────────────────────────────────────────────────┤
│ GUARDRAIL EVENTS                              [ filter ▾ ]  │
│ fair_housing  block  pre_send   #4402  14 Mar 09:12         │
│ pii           redact pre_llm    #4399  14 Mar 08:40         │
│ injection     quarantine webhook #4381 13 Mar 16:22         │
├─────────────────────────────────────────────────────────────┤
│ ✓ 412 of 412 decisions carry a complete evidence chain      │
│ ✓ hash chain verified nightly · last 26 Jul 03:00           │
│ [ Export audit bundle ]  JSON + signed PDF, date range      │
└─────────────────────────────────────────────────────────────┘
```

**The override-reason distribution is a product feature, not an admin log.** It tells an operator where the system is weak, and it tells you where to spend the next eval cycle.

**Export PDF is designed for print** — light theme, hairline rules, page furniture, title-block header on every page. This is the artifact an operator's counsel attaches to a file.

**Data:** `decisions`, `guardrail_events`, hash-chain verification job output.

---

## 13 · Agent health

```
┌ INTAKE ────────┬ DIAGNOSTICIAN ─┬ DISPATCH ──────┬ AUDITOR ───────┐
│ success  99.4% │ success  97.1% │ success  98.2% │ success  99.8% │
│ p50 412ms      │ p50 2.1s       │ p50 910ms      │ p50 120ms      │
│ p95 980ms      │ p95 6.4s       │ p95 2.8s       │ p95 340ms      │
│ repair    1.2% │ repair    2.8% │ repair    1.9% │ repair    0.1% │
│ escalate  0.4% │ escalate  6.2% │ escalate  3.1% │ escalate  0.0% │
└────────────────┴────────────────┴────────────────┴────────────────┘
```

Small multiples, uniform card size, so anomalies pop by **shape** rather than by scale.

**Alert-worthy, not just displayed:** escalation rate moving ±50% week over week in *either* direction. A drop means the system got overconfident, which is worse than a rise.

**Data:** aggregates over `agent_steps` and `llm_calls`, rolled up nightly by the worker.

---

## 14 · Cost dashboard

```
$0.021 per ticket        ─────────────────────────── $0.05 ceiling
      ▁▂▃▂▁▂▁▁▂▁▁▁

BY AGENT                          CACHE
diagnostician  ████████ $0.0091   prompt prefix   ▇▇▇▇▇▇▇▇▇ 91%
dispatch       ████ $0.0048       policy block    ▇▇▇▇▇▇▇   72%
intake         ██ $0.0021         embeddings      ▇▇▇▇▇▇▇▇▇ 96%
communicator   ██ $0.0017         retrieval       ▇▇▇       31%
auditor        █ $0.0018          tool results    ▇▇▇▇▇     48%
safety         █ $0.0011

Monthly · this property · 137 tickets          $2.88
Projected · 500 units · 1,650 tickets/yr        $38
```

The ceiling is drawn as a **rule**, not signalled by a colour change — consistent with the drawing language, and it survives colour-blind viewing.

**Data:** `llm_calls` aggregated; cache hit rates from the gateway policy layer.

---

## 15 · Eval dashboard

**Job:** the screen that makes a hiring manager believe everything else.

```
Eval run · golden_v1 · 200 items      sha 4c1e9a · judge pinned · seed 42

P0 recall        0.99  target ≥0.99   Priority F1     0.87  ≥0.85
Trade routing    0.91  target ≥0.90   Chargeback      0.89  ≥0.92  ← MISSED
Groundedness     0.96  target ≥0.95   Escalation prec 0.64  ≥0.60
Fair-housing        0  target  = 0    Council lift  +0.043  > 0
Cost/ticket    $0.021  target <$0.05  p95 latency    17.4s  < 20s

CALIBRATION
1.0│                                        ╱ ●
   │                                   ╱●
0.8│                              ╱ ●
   │                         ╱●              ── perfect
0.6│                    ╱ ●                  ●  observed
   │               ╱●
0.4│          ╱●
   └──────────────────────────────────────────
    0.45  0.55  0.65  0.75  0.85  0.95

ECE 0.041 · mildly overconfident between 0.60 and 0.80,
which is why the review band sits there rather than in the auto band.
```

**Design rules**
- **The missed metric is styled as missed and stays on the dashboard.** Publishing a red number with an explanation is more credible than five green ones, and it is the fastest signal that you have operated something.
- The **calibration reliability diagram is the hero chart** — give it the largest tile. Almost no portfolio project has one.
- Always show the git SHA, the pinned judge model, and the seed. An unreproducible metric is not a metric.

**Data:** `eval_runs.metrics`, `eval_items`, calibration bins computed at eval time and stored.

---

## 16 · Gateway dashboard *(Phase 7)*

```
ROUTING                                       FALLBACK
safety ────┐                                  primary    99.6%
intake ────┼──▶ SMALL (haiku) ──▶ anthropic   secondary   0.3%
comms ─────┤         62% of calls             local       0.1%
audit ─────┘
diagnose ──┐                                  BUDGET · this org
dispatch ──┼──▶ MID (sonnet)  ──▶ anthropic   ████████░░ $18 of $50
council ───┤         37% of calls             circuit breaker: closed
judge ─────┘──────────────────▶ google (cross-family)
escalate ──────▶ LARGE (opus) ──▶ anthropic
                     <1% of calls
```

Judge deliberately routes to a different model family than generation, to avoid self-preference bias. Show that on the screen — it is a question you will be asked.

---

## 17 · Memory review *(Phase 6)*

```
┌ PROPOSED REFLECTIONS ───────────────────────────────────────┐
│ "Riverside building C has low water pressure, causing       │
│  recurring cartridge failures in single-handle faucets."    │
│  scope: building C · confidence 0.81                        │
│  evidence  #3102  #3877  #4102  #4471                       │
│  [ Approve → promote ]  [ Reject ]  [ Needs more evidence ] │
└─────────────────────────────────────────────────────────────┘
```

**Approve is a brass button.** Memory only becomes durable when a person says so — that is the anti-poisoning design, made visible.

**Data:** `reflections` where `status = 'proposed'`. Approval sets `status='approved'` and `approved_by`.

---

## 18 · Owner monthly dashboard

```
RIVERSIDE · March 2026 · 412 units

Cost per unit   SLA met      Preventive    Reopen rate
$54             94.2%        31%           6.1%
down 8%         up 2.1pt     up 4pt        down 1.2pt

RECURRING FAILURES · CAPITAL REPLACEMENT CANDIDATES
4B   Kitchen drain    3 events / 14mo    $540
2C   Water heater     2 events /  8mo    $310
7A   HVAC blower      4 events / 18mo    $880

┌ AI GOVERNANCE ──────────────────────────────────────────────┐
│ 412 decisions                                               │
│ ████████ auto 46% │██████ approved 32% │███ over 14% │▌ 8%   │
│ ✓ 0 fair-housing blocks reached a resident                  │
│ ✓ 412 of 412 decisions carry a complete evidence chain      │
│ ✓ audit log hash chain verified nightly                     │
│ [ Export audit bundle ]     [ Override reasons ]            │
└─────────────────────────────────────────────────────────────┘
```

Light theme, print-adjacent, monthly cadence — optimised for comprehension, not interaction. The governance strip gets its own bordered region rather than a tab, because it is the block no competitor ships.

---

## 19 · Tech job card

```
┌──────────────────────────┐
│  ● P2   #4471            │
│  RIVERSIDE · 4B          │
│  ──────────────────────  │
│  Kitchen sink · plumbing │
│                          │
│  LIKELY                  │
│  P-trap failure, third   │
│  event. Replace assembly │
│  — do not snake.         │
│                          │
│  BRING                   │
│  1½" P-trap kit          │
│  Slip-joint pliers       │
│  Bucket + towels         │
│                          │
│  ACCESS                  │
│  Entry permitted · cat   │
│  in the apartment        │
│                          │
│  [    ON MY WAY    ]     │
│  [  CAN'T MAKE IT  ]     │
└──────────────────────────┘
```

**The `BRING` block gets equal weight with the diagnosis.** First-time-fix rate is the metric this screen exists to move, and parts-on-truck is the biggest lever on it.

56px minimum touch targets, works with gloves, cached job list with queued status updates when offline.

---

## 20 · Vendor accept / decline

```
┌──────────────────────────────────────────┐
│  Delta Plumbing                          │
│  ────────────────────────────────────    │
│  Kitchen drain · trap replacement        │
│  Riverside, 1400 River Rd, Unit 4B       │
│  Before 10:00am, Fri 24 Jul              │
│                                          │
│  Access: entry permitted, cat inside     │
│  Likely parts: 1½" P-trap assembly       │
│  [ photo ] [ photo ]                     │
│                                          │
│  [      Accept      ]                    │
│  [      Decline     ]                    │
└──────────────────────────────────────────┘

DECLINE →  Not available | Outside my area | Wrong trade |
           Rate too low  | Other
```

**No account, no login, no app.** HMAC-signed URL, 48-hour TTL, single-use nonce, no PII in the URL. Decline reasons feed `vendor_scores`, which feeds the next dispatch decision. Closed loop.

---

## 21 · Compliance block — **the closing argument**

**Job:** demonstrate judgment, not capability. Fifteen seconds of screen time.

```
┌────────────────────────────────────────────────────────────┐
│  ⚑  Response blocked before sending                        │
│                                                            │
│  Resident asked:                                           │
│  "I use a housing voucher — is that a problem for this     │
│   unit?"                                                   │
│                                                            │
│  Guardrail    fair_housing · pre_send                      │
│  Reason       source-of-income is a protected class in      │
│               this jurisdiction; automated response not     │
│               permitted                                     │
│  Action       routed to a human · logged · resident told    │
│               a team member will reply                      │
│                                                            │
│  Nothing was sent. Nothing was rewritten.                  │
├────────────────────────────────────────────────────────────┤
│  CI · red-team parity suite            42 of 42 passing    │
│  voucher holder · wheelchair access · service animal ·     │
│  family with children · non-English name                   │
└────────────────────────────────────────────────────────────┘
```

**This screen should not look impressive.** That is the point. The system did nothing, loudly, and logged it. Pair it on screen with the CI job showing paired protected-class probes passing — that is exactly the test a fair-housing testing organisation would run against you, so you run it against yourself every commit.

---

## 22 · Degraded mode banner

```
┌────────────────────────────────────────────────────────────┐
│ ⚑ Running in reduced mode — decisions are rule-based and   │
│   all tickets go to review. Tickets are still being        │
│   accepted normally.                                       │
└────────────────────────────────────────────────────────────┘
```

Persistent, non-dismissible, present on every surface including the resident app (in resident vocabulary). Honesty about degradation is a trust asset, and the banner is proof that the degradation ladder exists rather than being claimed.

---

## Cross-cutting requirements

**Every screen ships with all five states designed:** empty, loading, error, degraded, and blocked-by-guardrail. Skipping these is how a demo falls apart in front of a stranger.

| State | Rule |
|---|---|
| Empty | An invitation with exactly one action. Never a shrug illustration |
| Loading | Skeleton matching final layout. For runs, show the step structure immediately with pending steps hollow — structure is information before content arrives |
| Error | What happened + what to do. *"Couldn't reach the model provider. The ticket is saved and queued — we'll retry automatically."* Errors do not apologise |
| Degraded | Screen 22 |
| Blocked | Screen 21 — never silently rewritten |

**Accessibility, checked in CI with axe:** WCAG 2.2 AA on both themes · every lamp paired with a text label so colour never carries meaning alone · full keyboard traversal of the queue with a visible focus ring · semantic landmarks · live regions for streaming steps, polite and throttled · `prefers-reduced-motion` honoured · 360px minimum viewport · 44px touch targets (56px on tech).

**Data honesty rule:** every dashboard renders real seeded data. No placeholder numbers ship, not even temporarily. Experienced reviewers can tell, and it costs all your credibility at once.
