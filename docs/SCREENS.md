# SCREENS.md — Build Reference

**Every screen in Resident OS, specified enough to build from.**
Owner: Vishal (solo)
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
| 13 | Agent health | **ml-ops** | 6 | FR-1002 |
| 14 | Cost dashboard | **ml-ops** | 5 | NFR-06 |
| 15 | Eval dashboard | **ml-ops** | 5 | §7.1 |
| 16 | Gateway dashboard | **ml-ops** | 7 | — |
| 17 | Memory review | manager | 6 | — |
| 18 | Owner monthly dashboard | owner | 4 | FR-705 |
| 19 | Tech job card | tech | 3 | FR-401 |
| 20 | Vendor accept/decline | vendor | 3 | FR-404, FR-405 |
| 21 | Compliance block | manager | 4 | FR-504, FR-508 |
| 22 | Degraded mode banner | all | 3 | NFR-10 |
| **23** | **ML Ops Console** — the shell that hosts 13–16 plus six new panels | **ml-ops** | 5–7 | FR-1001…1009 |

> **Screens 13–16 are not standalone pages.** They are panels inside screen 23. Building them as separate routes was the earlier plan and it was wrong: an engineer debugging a quality regression needs agent health, cost, evals, and the gateway *on one surface with a shared time range*, because the answer is almost always a correlation between two of them. See §23.

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

## 23 · ML Ops Console — the engineer's surface

**Job:** one place where an ML engineer can answer *"is the system working, and if not, which part."* Everything about models, agents, prompts, outputs, evals, failures, and drift lives here.

**Route:** `/ops` · **Role:** `admin` only, never exposed to `manager`, `owner`, or `resident` · **Phase:** shell + panels A/B/C in Phase 5, panels D–F in Phase 6, G–H in Phase 7.

### 23.0 Why this absorbs screens 13–16

The earlier plan had agent health, cost, evals, and the gateway as four separate routes. That is wrong for the way debugging actually happens.

A real investigation reads: *"groundedness dropped — did retrieval get worse, did a prompt version change, did cost per run move at the same time, did the gateway start falling back to a substitute model?"* Four answers, four tabs, four independently-scoped time ranges, and the correlation you need is invisible. **One shell, one global time range, one filter set.** Panels are collapsible sections in a single scroll, not tabs — tabs hide the correlation.

Global controls, applied to every panel at once:

```
[ last 24h ▾ ]  [ all properties ▾ ]  [ prompt set: v7 ▾ ]  [ compare to: previous period ▾ ]
```

### 23.1 Layout

```
┌ ML OPS ─────────────────────────────── last 24h · 342 runs ─────┐
│                                                                 │
│  ⚑ Degraded — 1 signal outside band                             │  ← A · verdict
│    Online groundedness 0.918 vs offline 0.961, started ~14h ago  │
│                                          [ Investigate ]        │
├─────────────────────────────────────────────────────────────────┤
│  QUALITY 0.918 │ RELIABILITY 99.1% │ COST $0.024 │ HUMAN 17.2%   │  ← A · quadrants
├─────────────────────────────────────────────────────────────────┤
│  B · AGENT SCORECARD          ranked by degradation              │
│  ● diagnostician  sonnet-5  diagnose@v7  97.1% · 2.1s · esc 6.2% │
│  ● dispatch       sonnet-5  dispatch@v3  98.2% · 910ms          │
│  ● intake         haiku     intake@v4    99.4% · 412ms          │
├─────────────────────────────────────────────────────────────────┤
│  C · FAILURE FEED             7 uncited · 4 schema · 3 miss     │
│  [typed events with why + fix + promote-to-golden-set]          │
├─────────────────────────────────────────────────────────────────┤
│  D · MODEL REGISTRY           what is live, at what price       │
│  E · PROMPT REGISTRY          versions, hashes, A/B splits      │
│  F · EVAL HISTORY             metrics by commit + calibration   │
│  G · DRIFT                    online vs offline, embeddings     │
│  H · OUTPUT INSPECTOR         sample real outputs by filter     │
└─────────────────────────────────────────────────────────────────┘
```

---

### Panel A · Health verdict and quadrants

**One line, not a grid.** An engineer opening this at 9am needs "is anything wrong" answered before reading anything else. The verdict is computed, not curated:

```python
def verdict(signals) -> Verdict:
    breaches = [s for s in signals if s.outside_band]
    if any(s.severity == "critical" for s in breaches): return DOWN
    if breaches: return DEGRADED
    if any(s.trending_toward_band_edge for s in signals): return WATCH
    return HEALTHY
```

Four quadrants below, each the single most diagnostic number in its class: **quality** (groundedness), **reliability** (run completion), **cost** (blended $/ticket vs ceiling), **human** (override rate). Override rate belongs here and is usually forgotten — it is the only quality signal that comes from a human rather than from a model grading a model.

**Data:** `metric_rollups` (§23.9), not live aggregation over `llm_calls`. Scanning the raw tables for a dashboard is how you make your own observability the slowest thing in the system.

---

### Panel B · Agent scorecard

**Ranked by degradation, never alphabetically.** The suspicious agent is always row one.

Per agent: current model, live prompt version, run count, success rate, p50/p95, schema repair rate, escalation rate, cost per run, and a health lamp. Expanding a row gives the *change narrative* — not more numbers, but a sentence saying what moved and what did not:

> Groundedness fell 0.043 in 14h. Prompt unchanged. Retrieval recall@5 flat. Suspect input distribution shift — 3 new SOP docs merged yesterday may be crowding the policy slot.

**That narrative is generated from rules over the rollups, not by an LLM.** "Prompt unchanged, retrieval flat, KB changed" is a join, and it is the most useful thing on the screen. An LLM writing this would occasionally invent a cause.

Degradation ranking score:

```
degradation = 0.35·quality_delta_vs_baseline
            + 0.25·escalation_delta
            + 0.20·(1 - success_rate)
            + 0.10·schema_repair_rate
            + 0.10·latency_p95_delta
```

---

### Panel C · Failure feed

Typed failure events from the taxonomy in `ARCHITECTURE.md` §14, grouped with counts, each expandable to **detail · why · fix**.

Three actions per event:

| Action | Effect |
|---|---|
| **Promote to golden set** | Queues the case in `label_queue`. **Does not add it to the eval set** — it needs a human-written expected answer first. Auto-adding production failures would let the model's own behaviour define ground truth |
| **Trace** | Opens screen 7 scoped to that run |
| **Known, dismiss** | Suppresses this failure signature for 7 days, logged |

**This panel is the reason the console exists.** It closes the loop: production failure → labelled eval item → CI gate → prevented regression. Without it the eval set is frozen at whatever you imagined in week 5, and the system stops learning from its own mistakes.

The `why` and `fix` lines are **written by the engineer when triaging**, stored on the event, and shown to whoever sees it next. Institutional memory for failures, in the same spirit as `MEMORY.md`.

---

### Panel D · Model registry

```
MODEL              TIER   TASKS                       RUNS   $/RUN   p50    QUALITY
claude-haiku-4.5   small  safety, intake, comms,      1,368  0.0017  340ms  —
                          policy audit
claude-sonnet-5    mid    diagnose, dispatch,           684  0.0070  1.6s   0.918
                          council, judge
claude-opus-4.8    large  escalated review                4  0.0210  4.2s   —
gemini-flash       mid    judge cross-check              34  0.0009  890ms  —
llama-3.3 (ollama) local  offline fallback                0  0.0000  —      —
```

Answers "what is actually live and what is it costing me," which drifts from what you *think* is live the moment a fallback fires. Deprecation warnings surface here when a provider announces an EOL date.

---

### Panel E · Prompt registry

```
diagnose@v7   live 100%   sha a91f3c   since 12 Jul   groundedness 0.918 ▾
diagnose@v6   archived    sha 3d81e0   12 Jun–12 Jul  groundedness 0.961
intake@v4     live  90%   sha 77c2b1   since 04 Jul   field F1 0.94
intake@v5     canary 10%  sha 91ae04   since 31 Jul   field F1 0.95 (n=34, wide CI)
```

Every prompt is a versioned file with a content hash recorded on every call (`llm_calls.prompt_hash`), so this panel is a group-by, not new bookkeeping. Shows live/canary splits, per-version quality, and a **one-click rollback** that flips the version pointer — a config change, not a redeploy.

The canary row deliberately shows `n=34, wide CI`. A dashboard that reports a canary's metric without its sample size invites you to promote on noise.

---

### Panel F · Eval history

Screen 15's content, plus commit-level history: each eval run as a row with git SHA, dataset version, judge model and version, every metric, and pass/fail per band. Sparkline per metric with the tolerance band drawn as a shaded corridor.

The **calibration reliability diagram** is the hero chart here, and the console adds one thing screen 15 lacked: an overlay of *online* calibration against *offline*. If production confidence is calibrated differently from your eval set, your auto-execution threshold is wrong in production, which is the most consequential silent failure this system can have.

---

### Panel G · Drift

Four signals, all of which move slowly and none of which trigger a normal alert:

| Signal | Detects |
|---|---|
| **Online vs offline metric delta** | Distribution shift — CI passes while production degrades. The single most important signal on this screen |
| **Judge score distribution over time** | Judge drift, or genuine quality change. Ambiguous by design, which is why it is shown rather than alerted |
| **Input embedding drift** (Phoenix projection) | Residents are asking about new things — usually a KB gap |
| **Retrieval score distribution** | Corpus drift after KB edits; falling top-1 rerank scores mean the KB no longer covers the questions |

**Alert on the first. Display the rest.** Alerting on all four produces noise that gets muted, and a muted alert is worse than no alert.

---

### Panel H · Output inspector

The panel that stops the console from being all aggregates. Sample real outputs with filters that surface the interesting tail:

```
[ confidence < 0.6 ] [ human overridden ] [ judge flagged ] [ council disagreed ]
[ guardrail fired ] [ regenerated ] [ random sample ]
```

Each row: input, output, citations, confidence, judge scores, human decision and reason. Side-by-side diff when a human edited the output — **the edit itself is the most information-dense artifact in the system**, because it shows precisely what the model got wrong in a way no metric captures.

Two actions: promote to golden set (via `label_queue`), or open the trace.

---

### 23.9 What this needs from the schema

Four tables that do not exist yet in `ARCHITECTURE.md` §3. All four are additive.

```sql
create table failure_events (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  run_id uuid references agent_runs on delete cascade,
  step_id uuid references agent_steps on delete cascade,
  kind text not null,              -- taxonomy: uncited_claim, schema_repair, ...
  signature text not null,         -- stable hash for grouping + dismissal
  agent text not null,
  detail jsonb not null,
  triage_why text,                 -- written by the engineer
  triage_fix text,
  status text not null default 'open',   -- open|dismissed|promoted|resolved
  dismissed_until timestamptz,
  created_at timestamptz not null default now()
);
create index on failure_events (org_id, kind, created_at desc);
create index on failure_events (signature, status);

create table prompt_versions (
  id uuid primary key default gen_random_uuid(),
  key text not null,               -- 'diagnose'
  version int not null,
  content_sha256 text not null,
  source_path text not null,
  status text not null,            -- live|canary|archived
  traffic_pct int not null default 0,
  activated_at timestamptz,
  retired_at timestamptz,
  unique (key, version)
);

create table metric_rollups (
  bucket timestamptz not null,     -- hourly
  org_id uuid not null,
  scope text not null,             -- 'agent:diagnostician' | 'model:sonnet-5' | 'system'
  metric text not null,
  value numeric not null,
  sample_n int not null,
  primary key (bucket, org_id, scope, metric)
);

create table label_queue (
  id uuid primary key default gen_random_uuid(),
  source text not null,            -- failure_event | output_inspector | override
  source_id uuid not null,
  run_id uuid references agent_runs,
  input jsonb not null,
  observed jsonb not null,
  expected jsonb,                  -- NULL until a human writes it
  labeled_by text,
  labeled_at timestamptz,
  promoted_to_dataset uuid references eval_datasets,
  created_at timestamptz not null default now()
);
```

`metric_rollups` is the important one. **Never aggregate `llm_calls` live for a dashboard** — the worker rolls up hourly, and every panel reads rollups. Otherwise your observability becomes the heaviest query in the system, and it gets heavier exactly as things go wrong.

### 23.10 API

```
GET  /v1/ops/health                     verdict + quadrants
GET  /v1/ops/agents?window=24h          scorecard with degradation ranking
GET  /v1/ops/failures?kind=&status=     failure feed
POST /v1/ops/failures/{id}/triage       {why, fix}
POST /v1/ops/failures/{id}/dismiss      {days}
POST /v1/ops/label-queue                promote from failure or output
GET  /v1/ops/models                     registry with live cost/latency
GET  /v1/ops/prompts                    registry with traffic split
POST /v1/ops/prompts/{key}/rollback     {to_version}
GET  /v1/ops/evals?limit=               run history
GET  /v1/ops/drift?signal=              drift series
GET  /v1/ops/outputs?filter=            output inspector
```

### 23.11 Acceptance

- [ ] Opening `/ops` answers "is anything wrong" in under 5 seconds of reading
- [ ] Every panel respects one global time range and filter set
- [ ] No panel queries a raw event table — all read `metric_rollups`
- [ ] A failure can be promoted to `label_queue` and appears there requiring a human expected answer
- [ ] Prompt rollback is a config flip with no redeploy, verified in staging
- [ ] The change narrative in panel B is rule-generated and never model-generated
- [ ] `/ops` is `admin`-only; a `manager` token returns 403, asserted in CI
- [ ] Every number on screen traces to a rollup row with a sample size

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
