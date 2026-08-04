# services/brain

The **Ops Brain** — the AI spine of Resident OS. This is the portfolio-critical surface and the interview material.

## What lives here

- **Agents** (nine components; four are LLM agents on the critical path):
  - `orchestrator/` — LangGraph state machine, sole holder of side-effecting tools
  - `safety_sentinel/` — rules + Haiku, ultra-conservative life-safety detector
  - `intake_normalizer/` — free text / photo / voice → validated `TicketFacts`
  - `context_broker/` — deterministic evidence assembly under a token budget
  - `diagnostician/` — grounded diagnosis with citation IDs
  - `policy_auditor/` — lease + statute + SOP check on the proposed decision
  - `dispatch_planner/` — vendor / tech / parts / cost proposal
  - `communicator/` — templated resident + vendor copy
  - `judge/` — offline scorer (100% offline, 10% online sample)
- **Council Mode** — evidence-split members (SOP-grounded, unit-history-grounded, cost/warranty-grounded), fires on ~10% of tickets, not all
- **Retrieval** — hybrid BM25 + pgvector + RRF + rerank, provenance-preserving envelope
- **Memory** — four-store service (working, episodic, semantic, procedural) behind a swappable interface
- **Guardrails** — input + output pure functions (PII redaction, fair-housing screen, injection defense)
- **Gateway policy** — routing, budgets, caching on top of LiteLLM (transport is bought, policy is our code)

## The five principles that generate every decision here

1. **Reliability compounds multiplicatively** — ≤ 5 LLM calls on the critical path.
2. **Decompose by blast radius, not job title** — split on permission / context / evaluability, not persona.
3. **Read in parallel, write single-threaded** — many readers, exactly one writer (the orchestrator).
4. **The model proposes, deterministic code disposes** — every consequential outcome passes through code you can unit-test.
5. **Calibrated abstention beats confident coverage** — "I'm not sure, here's why" is a first-class output.

Detailed rationale: [docs/02-ai-architecture.md](../../docs/02-ai-architecture.md).

## Framework-independence rule

Every agent is a plain `async` Python function with a typed input and a Pydantic output. LangGraph nodes are three-line wrappers. If LangGraph becomes a problem, we replace ~200 lines of orchestration, not the product.

## Owner

Track **A** per [PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Property management software records what happened. This is the layer that decides what to do next.
> Root: [README.md](../../README.md)
