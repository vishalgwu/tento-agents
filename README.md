# tento-agents · Resident OS

**The multi-agent AI operating system for apartment communities.**
An autonomous orchestration layer that sits on top of legacy PMS software (Yardi, Entrata, AppFolio, Buildium) and runs the workflows those systems only log — starting with the maintenance loop.

> Property management software records what happened. Nobody built the layer that decides what to do next. Resident OS is that layer, and every decision it makes comes with its receipts.

Working codename: **Resident OS**. Internal name for the AI spine: **the Ops Brain**.
Author: Vishal Fulsundar. Status: planning + scaffolding.

---

## The one-line thesis

In a regulated vertical (Fair Housing, ADA, Colorado AI Act, twelve state AGs pursuing AI discrimination claims), the durable product is not the smartest model — it is the **defensible decision record**. Every AI action ships with prompt hash, model version, retrieved citations, guardrail verdicts, confidence score, and a human approval trail.

## The wedge workflow: the Maintenance Loop

A US apartment portfolio generates ~3.3 maintenance requests per unit per year at ~$200 per request. Triage is still a human reading free text and guessing at four things: urgency, trade, who pays, and what the tech will need on arrival. Get it wrong in one direction and you send a licensed plumber for a garbage-disposal reset; get it wrong in the other and a no-heat call sits three days in January, which in CA/NY/TX/IL is a habitability statute with rent abatement attached.

The maintenance loop wins the "which workflow first" argument for a reason most people miss: **it's the only apartment workflow with abundant, cheap ground truth.** Vendor accept/reject, reopen rate, human re-classification, first-time-fix — you get labels for free, so you can measure your agents instead of demoing them.

## The five principles that generate every decision

1. **Reliability compounds multiplicatively** — ≤ 5 LLM calls on the critical path (10 steps at 95% each = 60% end-to-end).
2. **Decompose by blast radius, not job title** — split on permission / context / evaluability, not persona.
3. **Read in parallel, write single-threaded** — many read agents, exactly one writer (the orchestrator).
4. **The model proposes, deterministic code disposes** — every consequential outcome passes through code you can unit-test.
5. **Calibrated abstention beats confident coverage** — "I'm not sure, here's why" is a first-class output.

## Repo layout

```
tento-agents/
├── apps/
│   └── web/                     Next.js 15 — resident, manager, owner, tech, vendor shells
├── packages/
│   ├── ui/                      Shared component library
│   └── shared-types/            Generated from docs/openapi.yaml — do not hand-edit
├── services/
│   ├── brain/                   The Ops Brain — 9 agents, Council, RAG, memory, guardrails
│   ├── api/                     FastAPI HTTP + SSE surface
│   ├── worker/                  Judge, embeddings, rollups, reflection, notifications
│   └── mcp/                     kb-mcp, ops-mcp, policy-mcp (the only write tools live here)
├── knowledge/                   Markdown KB — SOPs, policy, habitability, fair-housing
├── evals/                       Golden set, suites, CI gate, published REPORT.md
├── infra/
│   ├── migrations/              Postgres DDL with RLS everywhere
│   └── seed/                    Synthetic data generator for local + demo
├── .github/workflows/           ci.yml, evals.yml, deploy.yml
└── docs/                        The blueprint — read this first
```

Each folder has its own scoped `README.md`. **Start with [docs/00-START-HERE.md](docs/00-START-HERE.md).**

## Documentation

| Doc | What's in it |
|---|---|
| [docs/00-START-HERE.md](docs/00-START-HERE.md) | One-paragraph pitch, ten up-front verdicts |
| [docs/01-strategy-and-product.md](docs/01-strategy-and-product.md) | YC problem statement, segments, competitors, MVP, journeys, roadmap |
| [docs/02-ai-architecture.md](docs/02-ai-architecture.md) | Nine agents, Council Mode, RAG, memory, guardrails, judge, gateway, MCP |
| [docs/03-platform-engineering.md](docs/03-platform-engineering.md) | Schema, API, monorepo, infra, CI/CD, security, observability, scaling |
| [docs/04-execution-and-career.md](docs/04-execution-and-career.md) | 12-week roadmap, milestones, demo plan, investor narrative |
| [docs/PRD.md](docs/PRD.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/RULES.md](docs/RULES.md) · [docs/PHASES.md](docs/PHASES.md) · [docs/DESIGN.md](docs/DESIGN.md) | Working spec set — single source of truth, edit before code |

## What "done" looks like in 12 weeks

- A deployed product at a real URL with demo accounts for `resident`, `manager`, `owner`.
- A maintenance loop that triages, grounds, checks, decides, and escalates — with a visible trace for every decision.
- A **public eval report** with real numbers: routing accuracy, priority F1, groundedness, escalation precision/recall, cost per ticket, p50/p95 latency. Including the ones we miss.
- An observability stack where a stranger can click one ticket and watch the whole reasoning replay.
- A README a busy person understands in 90 seconds.

## Build mode

**Solo — Vishal.** The directory contract in [docs/PHASES.md §2](docs/PHASES.md) still applies as the *code-organization* rule: each concern has one authoritative folder, so future refactors (and Claude Code) don't scatter the same logic across the tree. `packages/shared-types/` is generated from `docs/openapi.yaml` — never hand-edited. Contract-change protocol is in [PHASES.md §5](docs/PHASES.md).
