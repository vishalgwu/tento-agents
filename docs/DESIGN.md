# DESIGN.md

**Design system and per-surface specifications for Resident OS.**
Owner: Vishal (solo) · Last updated: 2026-08-04
**Related:** `PRD.md` (users and jobs) · `ARCHITECTURE.md` (what the UI consumes) · `PHASES.md` (when each surface ships)

---

## 1. Design thesis

The product's argument is: **every decision comes with its receipts.** The interface has to make that argument visually, not just structurally.

So the design language borrows from the subject's own world — **architectural drawing and building signalling**. Floor plans, unit coordinates, drawing title blocks, revision marks, corridor status lamps, the paper tag hanging off a water heater. That vocabulary is native to buildings, it is not a generic SaaS look, and it gives us structural devices that encode real information instead of decorating.

**Three signature elements carry the whole system:**

1. **The status lamp.** Priority is an illuminated indicator with a soft bloom, borrowed from elevator and corridor signalling — not a coloured pill. It reads instantly at a distance, which matters for a manager scanning a queue and a tech glancing at a phone.
2. **The evidence rail.** A vertical rail beside every AI decision holding its citation chips. Hover a chip and the sentence it supports lights up; hover a sentence and its chip lights up. This is the product thesis made physical.
3. **Blue means machine, brass means human.** One semantic colour rule across every surface. Anything the system decided is cyanotype blue. Anything a person authorised is brass. When a manager overrides an AI decision, the card visually changes hands. Nobody else in this category does this, and once you see it you cannot unsee who made a decision.

**The risk we are taking deliberately:** brass as a second accent. Two accent colours is harder to keep disciplined than one, and it would be safer to use a single blue with a neutral for human actions. We are taking it because the machine/human distinction is the product, and a design that cannot show its central idea is a wasted surface. Everything else stays quiet so the brass can be loud where it appears.

**What we are consciously avoiding:** the three looks every AI-designed product currently converges on — warm cream with a high-contrast serif and a terracotta accent; near-black with one acid-green highlight; and the hairline-rule broadsheet grid. Our dark theme is a blue-ink dark, not near-black, and our accent system is semantic rather than decorative.

---

## 2. Surface personalities

One token system, three temperaments. This matters because a resident at 11pm and a manager at 8am want opposite things.

| Surface | Temperament | Density | Default theme | Motion |
|---|---|---|---|---|
| **Resident** (`/app`) | Warm, calm, reassuring. Feels like a good neighbour, not a ticketing system | Generous | Light | Soft, few |
| **Manager** (`/manage`) | Dense, fast, keyboard-first. A cockpit | Tight | Dark | Functional only |
| **Owner** (`/owner`) | Quiet, considered, print-adjacent | Medium | Light | Almost none |
| **Tech** (`/tech`) | Large targets, high contrast, glove-friendly, offline-tolerant | Loose | Dark | None |
| **Vendor** (`/v/[token]`) | Two decisions, zero chrome | Minimal | Light | None |

---

## 3. Tokens

### 3.1 Colour

**Neutrals** — blue-ink darks and cool paper lights. Never pure black, never pure white.

```
--ink-900     #0F151C   deepest surface (dark theme background)
--ink-800     #131A22   raised surface
--ink-700     #1B2530   card
--ink-600     #24303D   elevated card / hover
--slate-500   #3A4855   borders in dark
--slate-400   #5C6B7A   muted text in dark
--slate-300   #8A97A3   secondary text in dark

--chalk-050   #FAFAF8   lightest surface
--vellum-100  #F1F2EE   light theme background
--vellum-200  #E8EAE7   card in light
--vellum-300  #DADDD6   borders in light
--graphite-600 #4A5560  secondary text in light
--graphite-800 #232B33  primary text in light
```

**Semantic accents**

```
--machine       #2E5FA3   cyanotype blue — the system decided this
--machine-dark  #6FA0E0   dark-theme variant
--human         #B08D57   brass — a person authorised this
--human-dark    #D4AF7A   dark-theme variant
```

**Signal palette — the status lamps.** Desaturated for dark surfaces; inverting a light-mode chart palette onto dark produces neon.

```
--p0-ember   #E5484D  / dark #F2696E
--p1-amber   #E8A33D  / dark #F0B75E
--p2-cyan    #3E9BB5  / dark #5FB8D1
--p3-moss    #6B8F5E  / dark #8AAD7C
--neutral    #6E7A86            (informational, no urgency)
```

**Data-visualisation series** (dark-tuned, muted, never inverted from light):
`#6FA0E0 · #D4AF7A · #7FBFA8 · #C48FB0 · #A8A55E · #8892C4`
Gridlines: 4–6% lightness above the base surface. Axis labels at `--slate-400`.

### 3.2 Type

Three faces, three jobs. All open-licence.

| Role | Face | Usage |
|---|---|---|
| **Display** | **Archivo** (variable, expanded axis for large sizes) | Page titles, big numerics, metric values |
| **Body** | **Instrument Sans** | All prose, labels, buttons, form text |
| **Data** | **Martian Mono** | IDs, unit labels, hashes, confidences, timestamps, citation chips, eyebrows in small caps |

Martian Mono for identifiers is not decoration — unit `4B`, ticket `#4471`, and prompt hash `a91f…` are *identifiers*, and monospacing them makes them scannable and copy-safe. That is the structural device earning its place.

**Scale** (1.25 ratio, tuned per surface):

```
display-xl  40/44  Archivo 500 expanded   tracking -0.02em
display-l   32/36  Archivo 500            tracking -0.015em
title       24/30  Archivo 500
heading     19/26  Instrument Sans 600
body-l      16/26  Instrument Sans 400
body        14/22  Instrument Sans 400
caption     13/18  Instrument Sans 400
data        13/18  Martian Mono 400       tracking 0
eyebrow     11/14  Martian Mono 500       uppercase, tracking 0.09em
```

**Dark-theme typography rule:** light text on dark surfaces reads bolder than the same weight on light. Drop one step in weight in the dark theme (body 400 → 350 where the variable axis allows) and add 2% line height. Skipping this is why most inverted dark themes shimmer.

### 3.3 Spacing, radius, elevation

```
space: 2 4 8 12 16 24 32 48 64 96        (4px base)
radius: sm 4 · md 8 · lg 12 · xl 20 · pill 999
```

**Elevation is background shift, not shadow**, in dark. Borders at low opacity get lost, borders at high opacity feel heavy, and the in-between never looks right. So dark-theme cards are borderless and separated by surface steps (`ink-800 → ink-700 → ink-600`). Light theme keeps a 1px `vellum-300` border, because on paper-toned surfaces a hairline reads as a drawn rule, which suits the language.

Shadows exist only on floating layers (sheets, popovers, toasts): `0 8px 24px rgba(10,16,22,0.28)`.

### 3.4 Motion

One orchestrated moment, everything else near-instant.

| Token | Value | Use |
|---|---|---|
| `--ease-out` | `cubic-bezier(.2,.8,.2,1)` | entrances |
| `--ease-in-out` | `cubic-bezier(.4,0,.2,1)` | state change |
| `--dur-fast` | 120ms | hover, focus, toggle |
| `--dur-base` | 200ms | card, sheet, tab |
| `--dur-slow` | 400ms | the plot reveal (below) |

**The one orchestrated moment — the plot reveal.** When a run is streaming, each completed step draws in as though a pen plotter is inking it: a 400ms left-to-right wipe on the step's rule, then the label fades in, then the lamp ignites with a 200ms bloom. Nothing else in the product animates like this, so streaming reasoning becomes the memorable moment by contrast rather than by volume.

`prefers-reduced-motion: reduce` → steps appear instantly, lamps do not bloom, no wipes. Everything remains fully legible.

---

## 4. Core components

### 4.1 Status lamp

A 10px circle with a 4px inner core and an outer bloom at 18% opacity. Never used with a coloured background pill. Always paired with the text label for accessibility — colour never carries meaning alone.

```
● P0   ember, bloom 22%, slow 1.6s pulse (only P0 pulses)
● P1   amber, bloom 18%, static
● P2   cyan,  bloom 14%, static
● P3   moss,  bloom 10%, static
○ —    hollow ring, unclassified
```

### 4.2 Evidence rail

Right-aligned vertical rail, 220px on desktop, collapsible drawer on mobile. Each citation is a chip in Martian Mono: `[C1] SOP-PLM-04 §2`. Chip carries an authority glyph — `§` statute, `¶` lease, `▸` internal SOP, `·` vendor contract.

Bidirectional hover linking between chip and the sentence it supports. Clicking a chip opens the source excerpt in a sheet with the surrounding section (parent-document context) and the document's effective date.

**Any claim with no chip renders in an "unsupported" style** — italic, `--slate-400`, with a hollow marker. If the system ever produces one, the interface must not hide it.

### 4.3 Confidence meter

Not a percentage badge. A 5-segment horizontal gauge with the calibrated bands marked:

```
ABSTAIN │▓▓▓░░│ REVIEW │▓▓░░░│ AUTO
        0.60          0.85
  confidence 0.79 · calibrated on 200 items
```

The caption naming the calibration set is deliberate. It tells a technical reviewer this number means something, and it tells a manager not to over-trust it.

### 4.4 Title block

Page headers use the architectural drawing title block: a bordered strip with fields in Martian Mono.

```
┌──────────────────────────────────────────────────────────────┐
│ PROPERTY  Riverside     UNIT 4B      TICKET #4471            │
│ OPENED    23 Jul 11:40  REV 3        DECIDED BY  ◆ machine   │
└──────────────────────────────────────────────────────────────┘
```

`DECIDED BY` shows a blue diamond for machine, a brass diamond for human. `REV` counts revisions to the decision — genuinely useful, and it is exactly what a revision block means on a drawing.

### 4.5 Other primitives

Buttons (primary = machine blue; authority = brass, used only for approve/authorise; ghost; destructive) · inputs with inline validation · data table with sticky header, zebra at 2% opacity, and column-level density toggle · sheet (right, 480px) · toast (bottom-right, 4s, never for errors that need action) · empty state (an invitation with one action, never a shrug) · skeleton (surface-step shimmer, no gradient sweep).

---

## 5. Surface: Resident app (`/app`)

Mobile-first, light theme, generous spacing, warm copy. The resident should never see the word "agent," a model name, or a confidence score.

### 5.1 Home — asymmetric bento

```
┌─────────────────────────────────────┐
│  Good evening, Priya                │  display-l
│  Riverside · Unit 4B                │  data, muted
├──────────────────┬──────────────────┤
│                  │  ● P2            │
│  REPORT AN       │  Kitchen sink    │  ← active ticket, tall
│  ISSUE           │  Plumber before  │
│                  │  10am tomorrow   │
│  (large tap      │                  │
│   target)        │  [Track]         │
├──────────────────┴──────────────────┤
│  This week at Riverside             │
│  ┌────────┐ ┌────────┐ ┌────────┐   │  ← horizontal scroll
│  │ Run    │ │ Rooftop│ │ Yoga   │   │
│  │ club   │ │ movie  │ │ Sat 9a │   │
│  └────────┘ └────────┘ └────────┘   │
├──────────────────┬──────────────────┤
│  Marketplace  →  │  Amenities   →   │
└──────────────────┴──────────────────┘
```

Asymmetric bento, not a uniform grid: the active ticket is the tallest tile because it is the thing the resident actually came for. Tile sizes encode priority of attention, which is the only reason to use a bento at all.

### 5.2 Report an issue — three taps

Step 1: **What's wrong?** — six large category tiles with plain-language labels (Water · Heat & Air · Power · Appliance · Pests · Something else), plus a text field. No dropdowns.
Step 2: **Show us** — camera-first sheet, up to 5 photos, optional 30-second voice note with a live waveform.
Step 3: **Access** — "Can we enter if you're out?" with a clear yes/no, pets toggle, preferred window chips.

Submit → **instant** confirmation with the ticket number. The acknowledgment never waits on a model.

### 5.3 Ticket detail — the resident's version of the trace

Residents get a **plain-language** timeline, not the engineering trace. Same underlying events, different vocabulary.

```
┌──────────────────────────────────────────┐
│  ● P2  Kitchen sink                      │
│  #4471 · Reported 23 Jul, 11:40pm        │
├──────────────────────────────────────────┤
│  ┃ ✓ We received your report      11:40pm│
│  ┃ ✓ Reviewed against your lease  11:40pm│
│  ┃ ✓ Marked urgent — third time    11:41pm│
│  ┃      this year                         │
│  ┃ ● Plumber scheduled              7:15am│
│  ┃      Delta Plumbing · before 10am     │
│  ┃ ○ Repair                               │
├──────────────────────────────────────────┤
│  There's no charge to you for this        │
│  repair.  Why? →                          │
└──────────────────────────────────────────┘
```

"Why?" expands to the plain-English reason with the lease section named. A resident who can see *why* they are not being charged trusts the system; a resident told only the outcome does not.

**Copy voice:** plain verbs, sentence case, no exclamation marks, no apologies from the system. *"A plumber will be there before 10am"* — not *"We're so sorry for the inconvenience! Our team is working hard!"*

---

## 6. Surface: Manager console (`/manage`)

Dark theme by default. Dense. Keyboard-first — `j`/`k` to move, `a` approve, `e` edit, `r` reject, `/` search, `?` shortcuts. Marcus lives here for four hours a day and every saved second compounds.

### 6.1 The queue — the most important screen in the product

```
┌────────────────────────────────────────────────────────────────────────┐
│  QUEUE  11 awaiting approval          [SLA risk ▾] [All properties ▾]  │
├────────────────────────────────────────────────────────────────────────┤
│ ●  #4471  4B · Kitchen plumbing              SLA 13h    conf 0.91  ◆   │
│    3rd drain ticket in 14 months · trap replacement · owner · $180     │
│    [Approve]  [Edit]  [Reassign]  [Reject ▾]                  Trace ▸  │
├────────────────────────────────────────────────────────────────────────┤
│ ●  #4468  2C · No hot water                  SLA 4h     conf 0.74  ◆   │
│    Water heater 2019 Rheem · in warranty to Mar 2027 · owner · $0      │
│    ⚠ Council: members disagreed on priority                            │
│    [Approve]  [Edit]  [Reassign]  [Reject ▾]                  Trace ▸  │
├────────────────────────────────────────────────────────────────────────┤
│ ○  #4463  1A · Cabinet door                  SLA 4d     conf 0.44  ◆   │
│    ⚠ Escalated — lease is ambiguous on cabinet hardware wear           │
└────────────────────────────────────────────────────────────────────────┘
```

Design decisions worth defending:

- **Sorted by SLA risk, never arrival time.** The queue's job is to prevent the expensive miss.
- **One card, one screen, no scroll.** If the manager has to scroll to decide, the card is too big.
- **The diamond shows who decided.** Blue diamond until a human touches it, then brass.
- **Council disagreement is surfaced in the card**, not buried in the trace. A disagreement is the highest-information thing the system can tell a manager.
- **Every button is a labelled training example.** Reject opens the reason taxonomy in a two-key flow (`r` then `1–5`).

### 6.2 Trace viewer

Two-pane: nested span tree on the left, detail on the right. Virtualised, because agent traces nest deeply and a tree that stutters on expand destroys debugging speed.

```
┌─ TRACE #4471 ────────────────────┬─ STEP DETAIL ──────────────────────┐
│ ▾ guardrails.input        24ms   │  DIAGNOSTICIAN                     │
│     pii 2 redacted · clean       │  sonnet-5 · diagnose@v7 · a91f3c   │
│ ▾ safety+intake          412ms   │  in 4,012 (1,000 cached) · out 486 │
│ ▾ context.broker         338ms   │  $0.0158 · 2,140ms                 │
│   ▸ retrieval.hybrid     201ms   │                                    │
│   ▸ memory.episodic       88ms   │  ┌ PROMPT ────────────────── copy ┐│
│   ▸ context.budget         6ms   │  │ system + schema (cached)       ││
│ ▾ council           ⚑   2,140ms  │  │ [C1] SOP-PLM-04 §2 …           ││
│   ▸ member.policy      1,802ms   │  │ [C2] lease 4B §7.3 …           ││
│   ▸ member.history     2,010ms   │  └────────────────────────────────┘│
│   ▸ member.cost        1,640ms   │  ┌ OUTPUT ───────────────────────┐ │
│   ▸ council.synthesis    980ms   │  │ likely_cause: …               │ │
│ ▾ dispatch.planner       910ms   │  │ claims: 4 · citations 4/4 ✓    │ │
│ ▾ guardrails.policy      120ms   │  │ confidence 0.79               │ │
│ ▾ decision.gate            3ms   │  └───────────────────────────────┘ │
└──────────────────────────────────┴────────────────────────────────────┘
```

Parallel spans render as genuinely parallel bars sharing a horizontal track, so "three members ran at once" is visible rather than asserted. Any span with a guardrail hit gets a ⚑. The **Replay** button re-runs the decision against pinned versions and shows a side-by-side diff.

### 6.3 Retrieval inspector

Three columns — BM25 rank, vector rank, fused RRF — with connector lines showing how each chunk moved between lists, then a rerank delta column, then a "made the window" boundary rendered as a horizontal cut line at the token budget. Chunks below the cut are dimmed but present, because *what was almost retrieved* is often the answer to "why was this wrong."

### 6.4 Council view

Three columns of equal width, one per member, each showing its verdict, its confidence, its claims, and — critically — **what it could not see**, listed explicitly. Below, an agreement matrix, then the synthesis with dissent quoted rather than smoothed away.

If members disagree, the disagreement is styled as the headline of the screen, not as a warning banner. Disagreement is the feature.

### 6.5 Governance tab

Decisions by mode (auto / approved / overridden / escalated) over time · override reason distribution · guardrail event stream with filters · fair-housing block log · **Export audit bundle** for a date range, producing signed JSON plus a printable PDF that uses the title-block language throughout. The PDF is the artifact an operator's counsel would attach to a file, so it is designed for print: light theme, serif-free, hairline rules, page furniture.

---

## 7. Surface: Owner dashboard (`/owner`)

Light theme, calm, print-adjacent. Monthly cadence, so it optimises for comprehension, not interaction.

```
┌────────────────────────────────────────────────────────────────┐
│  RIVERSIDE · MARCH 2026                                        │
├──────────────┬──────────────┬──────────────┬───────────────────┤
│ COST/UNIT    │ SLA MET      │ PREVENTIVE   │ REOPEN RATE       │
│ $54          │ 94.2%        │ 31%          │ 6.1%              │
│ ▾ 8% vs Feb  │ ▴ 2.1pt      │ ▴ 4pt        │ ▾ 1.2pt           │
├──────────────┴──────────────┴──────────────┴───────────────────┤
│  Spend by trade                    Response time distribution  │
│  [horizontal bars]                 [box plot by priority]      │
├────────────────────────────────────────────────────────────────┤
│  RECURRING FAILURES — capital replacement candidates           │
│  4B kitchen drain     3 events / 14mo   $540 spent   [Review]  │
│  2C water heater      2 events / 8mo    $310 spent   [Review]  │
├────────────────────────────────────────────────────────────────┤
│  AI GOVERNANCE                                                 │
│  412 decisions · 78% approved · 14% overridden · 8% escalated  │
│  0 fair-housing blocks reached a resident                      │
│  [Export audit bundle]                                         │
└────────────────────────────────────────────────────────────────┘
```

Single-metric focus at the top with delta and direction, progressive disclosure below. The governance strip is the block no competitor ships, so it gets its own bordered region rather than hiding in a tab.

---

## 8. Surface: Tech mobile (`/tech`)

Dark, high contrast, 56px minimum touch targets, works with gloves and in a boiler room.

```
┌──────────────────────────┐
│  ● P2   #4471            │
│  RIVERSIDE · 4B          │
│  ────────────────────    │
│  Kitchen sink · plumbing │
│                          │
│  LIKELY                  │
│  P-trap failure, 3rd     │
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
│  [  ON MY WAY  ]         │
│  [  CAN'T MAKE IT  ]     │
└──────────────────────────┘
```

The "BRING" block is the highest-value thing the AI produces for a tech, so it gets equal weight with the diagnosis. First-time-fix rate is the metric this screen exists to move.

---

## 9. Surface: Vendor (`/v/[token]`)

No account, no navigation, no branding beyond a wordmark. Job, address, window, access notes, photos, parts hint. Two buttons: **Accept** / **Decline** — decline opens a five-option reason list. Works on a five-year-old Android in a van.

---

## 10. Engineering surfaces

These are simultaneously operational tools and the recruiter demo. They are designed, not thrown together.

| Surface | Central visual | Design note |
|---|---|---|
| **Eval dashboard** | Metric-history sparklines by commit, with the tolerance band drawn as a shaded corridor and breaches marked | The **calibration reliability diagram** is the hero chart. Almost no portfolio has one; give it the largest tile |
| **Cost dashboard** | Stacked area of cost by agent over time; cache-hit gauge; $/ticket trend against the $0.05 ceiling as a drawn limit line | Show the ceiling as a rule, not a colour change — the language is drawing |
| **Agent health** | Small-multiples grid, one card per agent: success rate, p50/p95, schema repair rate, escalation rate | Uniform card size so anomalies pop by shape, not by scale |
| **Context budget** | Stacked horizontal bar of the 8k envelope by slot, with the reserve hatched | Hatching for reserved space is a drawing convention and reads instantly |
| **Gateway** | Sankey of task class → tier → provider, plus fallback rate and budget consumption | The only place a Sankey earns its keep |
| **Memory review** | Proposed reflections with their evidence tickets as linked chips, approve/reject in brass | Brass here reinforces: memory only becomes durable when a human says so |

---

## 11. States, always designed

| State | Rule |
|---|---|
| **Empty** | An invitation with exactly one action. Manager queue empty → *"Queue clear. 3 tickets resolved today."* Never a shrug illustration |
| **Loading** | Skeletons matching final layout. For runs, show the step timeline immediately with pending steps hollow — the structure is information before the content arrives |
| **Error** | State what happened and what to do. *"Couldn't reach the model provider. The ticket is saved and queued — we'll retry automatically."* Errors do not apologise and are never vague |
| **Degraded** | A persistent, non-dismissible strip: *"Running in reduced mode — decisions are rule-based and all tickets go to review."* Honesty about degradation is a trust asset |
| **Offline (tech)** | Cached job list, queued status updates, explicit sync indicator |
| **Blocked by guardrail** | Never silently rewritten. Show the block, the reason, and the human action required |

---

## 12. Accessibility

Non-negotiable, checked in CI with axe.

- WCAG 2.2 AA contrast on both themes. Every signal colour is paired with a text label — **colour never carries meaning alone**, which also means the lamps work for colour-blind users because P0/P1/P2/P3 is always written.
- Full keyboard traversal of the manager queue with a visible 2px `--machine` focus ring at 3:1 against its background.
- Semantic landmarks, correct heading order, live regions for streaming step announcements (polite, throttled — a screen reader must not read every token).
- `prefers-reduced-motion` honoured everywhere.
- 360px minimum viewport on resident and tech surfaces.
- Touch targets ≥ 44px (≥ 56px on tech).
- Voice input is an alternative, never a requirement.

---

## 13. Copy voice

Words are design material, not decoration.

- **Name things by what people control**, never by how the system is built. A resident reports an issue; they do not "submit a work order intake."
- **Active voice, sentence case.** A control says exactly what happens: "Approve and dispatch," not "Submit."
- **Same word through the whole flow.** The button that says "Approve" produces a toast that says "Approved."
- **Specific beats clever.** *"Third drain ticket in 14 months"* beats *"Recurring issue detected."*
- **Never say "AI" to a resident** beyond the required disclosure. Say what happened.
- **Never claim certainty the system does not have.** *"Likely a P-trap failure"* — not *"The problem is."*

---

## 14. Landing page

The hero is not a big number with a gradient. The hero is **the product doing its one trick**: a live, auto-playing (muted, reduced-motion-safe) trace stream of a real seeded ticket being reasoned through, with the evidence rail filling in beside it. Below the fold, three buttons — **Resident · Manager · Owner** — each dropping straight into a pre-logged-in demo. No form, no gate.

Then one architecture diagram, then the eval table with real numbers **including the ones we missed**, then the fair-housing block demo. That last section is the closing argument: it demonstrates judgment rather than capability, and judgment is the rarer signal.

---

## 15. Implementation notes

- Tailwind with tokens exposed as CSS custom properties in `packages/ui/tokens.css`; **never a raw hex in a component**.
- shadcn/ui as the primitive layer, restyled to these tokens — not used at its defaults, which would erase the whole design position.
- Charts: Recharts, with the dark-tuned series palette above and gridlines derived from surface tokens.
- Fonts self-hosted with `font-display: swap` and subset to Latin. Three families is the ceiling; do not add a fourth.
- Watch CSS specificity between section-level and element-level selectors — cancelling padding rules between `.section` and `.card` is the most common way this system will visually rot.
- Every dashboard reads real seeded data. **No placeholder numbers ever ship**, not even temporarily.
