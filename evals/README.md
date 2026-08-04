# evals

The evaluation harness. This is the module that turns Resident OS from a demo into a **measured** system, and it is the single most credible thing in the repo.

## What lives here

```
evals/
├── datasets/
│   ├── golden.jsonl          # 200 human-labeled maintenance tickets
│   ├── p0_safety.jsonl       # Adversarial life-safety set (recall target ≥ 0.99)
│   ├── red_team_fh.jsonl     # Fair-housing / ADA probes (target: 0 leaks)
│   └── retrieval_qd.jsonl    # 50 hand-written query→doc pairs for recall@k
├── suites/
│   ├── priority_f1.py
│   ├── groundedness.py
│   ├── chargeback_accuracy.py
│   ├── escalation_precision_recall.py
│   └── council_lift.py
├── gate/
│   └── ci_gate.py            # Tolerance-banded pass/fail for CI
└── REPORT.md                 # Published eval report with real numbers
```

## Target metrics (measured, published — including the ones we miss)

| Metric | Target |
|---|---|
| Life-safety recall (P0) | ≥ 0.99, precision ≥ 0.70 |
| Priority macro-F1 (P1–P3) | ≥ 0.85 |
| Trade routing accuracy | ≥ 0.90 |
| Chargeback accuracy (with abstention) | ≥ 0.92 |
| Groundedness | ≥ 0.95 |
| Fair-housing guardrail leaks | **0** on the red-team set |
| Escalation precision | ≥ 0.60 |
| Cost per ticket | < $0.05 |
| p50 / p95 decision latency | < 6s / < 20s |

## Rules

- Retrieval eval runs in **Week 1**, before any agent exists. Retrieval quality caps everything downstream.
- CI eval gate wired to a deliberately-broken prompt as the canary — the gate must catch it.
- Every approval-queue reject is a training label. The reject-reason taxonomy *is* the eval dataset.

## Owner

Track **A** per [PHASES.md](../docs/PHASES.md).

---
> Resident OS — the AI operations layer for apartment communities.
> Root: [README.md](../README.md)
