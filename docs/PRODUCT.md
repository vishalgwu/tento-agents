# Resident OS Product Requirements

## Status and intent

Resident OS is an AI operations layer for apartment communities. It works beside a property-management system rather than replacing one. The first product is the Maintenance Loop: turn a resident's issue into a safe, grounded, reviewable dispatch decision, then retain the evidence needed to explain that decision later.

This document is the canonical product source of truth. It replaces the former strategy, PRD, design, screen, and demo files. Requirements and scope changes belong here before code changes.

## Product thesis

Property-management software records work; Resident OS decides the next safe action. The product differentiates on a defensible decision record, not on chat fluency. Every consequential decision must retain its inputs, evidence, model and prompt version, guardrail outcomes, confidence, human action, and resulting execution receipt.

The initial customer is a mid-market apartment operator with 1,000 to 15,000 units. The system starts with maintenance because it has frequent, measurable outcomes: priority correction, vendor acceptance, time to repair, first-time fix, reopen rate, cost, and override reason.

## Canonical scope

| Release | Included | Excluded |
| --- | --- | --- |
| Measured MVP, phases 0-5 | Maintenance intake, life-safety screening, evidence retrieval, diagnosis, policy audit, manager approval, dispatch proposal, trace, evaluation, and ML operations | Payments, rent collection, tenant screening, legal advice, health data, community feed, marketplace, and autonomous sending |
| Product expansion, phases 6-8 | Council mode, controlled memory, observability, notification policy, community and marketplace surfaces | Autonomous high-blast-radius action |
| Phase 9+ | Wellness/engagement and an evidence-gated autonomy dial | Any health inference or protected-attribute profiling |

Community functionality is deliberately deferred. The project should prove one measured decision loop before it becomes a broader resident platform.

## Users and jobs

| User | Job | Success condition |
| --- | --- | --- |
| Resident | Report a problem and know it is handled | Acknowledgement with a ticket number in under one second; plain-language status and charge explanation |
| Property manager | Clear a queue without making an expensive or unsafe mistake | Decision, evidence, SLA risk, and approve/edit/reject controls are visible together |
| Maintenance technician | Arrive prepared and resolve on the first visit | Job, access notes, likely cause, parts hint, and safety context are available |
| Vendor | Accept or decline a job with minimum friction | Signed link, no account, clear scope and timing; decline reason feeds future ranking |
| Asset owner | Understand costs, service level, recurring failures, and AI governance | Monthly outcomes and a complete exportable audit record |
| ML/operations engineer | Detect model, retrieval, cost, or drift failure | A single restricted console connects quality, reliability, cost, failures, and evaluation history |

## Maintenance loop

1. A resident submits free text, up to five photos, and an optional voice note.
2. The API persists the ticket and acknowledges it before any model work.
3. Deterministic life-safety rules screen the input. A qualifying signal follows the P0 protocol immediately.
4. The system extracts ticket facts, retrieves policy and operational evidence, and proposes a priority, diagnosis, responsible party, and dispatch plan.
5. Deterministic policy and evidence checks either allow a calibrated decision, require manager approval, or abstain and escalate.
6. The manager approves, edits, reassigns, or rejects. Only the approved path can execute through an authorised tool.
7. Resident and vendor communications use approved templates; deterministic notification policy decides eligibility, timing, channel, retry, and escalation.
8. The completed run becomes an auditable trace and an input to evaluation and operational learning.

## Product requirements

### Intake and safety

- **FR-101:** A resident can create a ticket with free text, up to five photos, optional voice, access permission, pets, and preferred access window.
- **FR-102:** The service returns a ticket number within one second without waiting for model inference.
- **FR-201:** Every ticket passes deterministic life-safety detection before other processing.
- **FR-202:** A small-model safety second opinion can escalate a ticket; the deterministic and model signals combine with OR logic, never AND logic.
- **FR-203:** A P0 event pages the approved human path without another model call in between.

### Decision and dispatch

- **FR-301:** Extract validated facts: category, symptom, affected asset, access, pets, preferred window, and available media facts.
- **FR-302:** Retrieve SOPs, lease clauses, jurisdictional SLA policy, unit history, asset state, warranty, and vendor information with source IDs and scores.
- **FR-303:** Every material factual claim in a generated recommendation must resolve to supporting evidence or be expressed as unknown.
- **FR-401:** Propose trade, in-house versus vendor, candidate vendor, time window, parts, estimated cost, and responsible party.
- **FR-402:** Vendor ranking considers service area, availability, response time, accept rate, first-time-fix rate, cost variance, and warranty eligibility.
- **FR-501:** Audit each proposed decision against statute, lease, internal SOP, and vendor contract in that order of precedence.
- **FR-601:** Queue decisions by SLA risk rather than arrival time; provide approve, edit, reassign, and reject without navigation away from the decision.

### Transparency, communication, and operations

- **FR-701:** Store execution steps, prompt hash/version, model/version, retrieved sources/scores, guardrail verdicts, confidence, token counts, cost, latency, approval, and execution receipt.
- **FR-702:** Provide a trace understandable by a non-engineer and a resident-facing status view that never exposes internal prompts, model names, or confidence scores.
- **FR-801:** Support urgency tiers U0-U3. A model may write within a validated template; it may never decide whether or when to notify.
- **FR-1001:** The admin-only ML operations console uses one shared time range for agent, prompt, model, output, evaluation, failure, cost, and drift state.

## Experience and visual system

The interface expresses one idea: every decision comes with receipts. Use the shared visual vocabulary of architectural drawings and building operations: blue-ink darks, paper lights, a status lamp paired with a textual priority label, evidence chips, and a decider mark that distinguishes a machine proposal from a human authorisation.

| Surface | Core responsibility | Must show |
| --- | --- | --- |
| Resident `/app` | Submit and track an issue | Plain-language timeline, current next step, charge explanation, accessibility-first mobile controls |
| Manager `/manage` | Review risk and authorise action | SLA-ordered approval queue, evidence, cost, confidence band, decision controls, trace link |
| Owner `/owner` | Review business and governance outcomes | Cost/unit, SLA, preventive share, reopen rate, recurring failures, human override and audit coverage |
| Tech `/tech` | Complete an assigned job | Job context, access, likely cause, parts, safe status updates, offline tolerance |
| Vendor `/v/[token]` | Accept or decline an external job | Signed no-login link, scope, photos, timing, decline reason |
| Operations `/ops` | Diagnose the system | Health verdict, agent scorecard, failure feed, model/prompt registry, evaluation and drift |

The manager queue is the primary demonstration screen. It must make the evidence, recommendation, cost, risk, and human choice legible at a glance. The resident view uses the same underlying facts but translates them into simple language.

### Accessibility and trust

- Colour never carries priority alone; every lamp has a text label.
- All critical controls are keyboard accessible and meet WCAG AA contrast.
- Reduced-motion mode replaces animation with a completed state.
- The product never fabricates progress. If a decision is escalated, the resident sees that a human is reviewing it.
- Demo mode is visibly labelled as synthetic and blocks every real outbound transport.

## Quality targets

These are launch targets, not claimed results. Publish measured results, including misses, with their evaluation run and commit SHA.

| Metric | Target |
| --- | --- |
| Ticket acknowledgement | 99.9% under 1 second |
| P0 life-safety recall | at least 0.99; precision at least 0.70 |
| Priority macro-F1, P1-P3 | at least 0.85 |
| Trade-routing accuracy | at least 0.90 |
| Chargeback accuracy with abstention | at least 0.92 |
| Groundedness | at least 0.95 |
| Fair-housing guardrail leaks | zero on the red-team set |
| Escalation precision | at least 0.60 |
| Decision latency | p50 under 6 seconds; p95 under 20 seconds |
| Cost per ticket | under $0.05 |

## MVP release gate

The measured MVP is ready only when an unaided visitor can submit a synthetic ticket, see the reasoning stream and cited recommendation, approve it in the manager console, and inspect the audit trace. CI must fail on a deliberately broken prompt or guardrail fixture. The published evaluation report must contain reproducible measured numbers and at least one explained miss if a target is not met.
