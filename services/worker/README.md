# services/worker

Asynchronous background jobs. Nothing on the critical path lives here.

## What runs here

- **Judge** — offline scoring of 100% of runs; online sampled at 10%. Writes `judge_scores`.
- **Embeddings** — chunking + embedding jobs for the KB and for episodic memory promotion.
- **Rollups** — nightly aggregates for the owner dashboard (SLA compliance, cost per unit, recurring-failure units, override reason breakdowns).
- **Reflection** — episodic-memory summarization + approval-gated promotion into semantic memory.
- **Notifications** — the U0–U3 delivery pipeline (eligibility → classify → timing → dedupe → fatigue budget → channel ladder → render → deliver → receipt/retry → escalation).

## Owner

Track **A** per [PHASES.md](../../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../../README.md)
