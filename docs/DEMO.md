# Part 2B: supplied-policy demo

The project is a **demonstration application**. The supplied Maple Court policy pack is sufficient for the fictional workflow; real-property policy approval is not a prerequisite for this demo.

## What was corrected

Five supplied Markdown policies retain their original bodies and synthetic notices. Normalization adds unique full source IDs, versioned YAML metadata, US-VA demo routing labels, SHA-256 checksums and `temporary_fixture` / `production_eligible: false`. The supplied manifest reused MC-OPS for four documents; the normalized manifest uses MC-OPS-001/003/004/005. Ten claims use exact contiguous source spans rather than paraphrased citation anchors. Twelve supplied scenarios are preserved and three ordinary-maintenance examples are explicitly marked as generated synthetic extensions.

Two routine scenarios include explicit fictional staff authorization and resident-access assumptions. These assumptions are visible in the demo and confer no real credentials. They apply only to exact bundled scenarios, not arbitrary submitted text.

## Connected demonstration

Open [/demo](https://tento-resident-os.vercel.app/demo). Public visitors can select fifteen scenarios, inspect actual recorded graph outcomes, read exact policy quotations and expand the stage trace. No sign-in or model call is needed for recorded exploration. The default cabinet example is an introductory routine scenario.

A signed-in user can choose **Run a fresh assessment**. Next.js checks same-origin requests and the HttpOnly session cookie, then calls JWT-authenticated `/v1/demo/run` with a generated idempotency key. Existing tenant scope, Redis rate limits and replay protection still apply. The demo flag must be enabled. The graph is bounded by its existing step cap and a 150-second request timeout; models still pass through the audited gateway and original schema/citation/decision checks.

The sandbox uses only its packaged fictional documents, an isolated SQLite FTS5/BM25 index, per-run in-memory checkpoints and in-memory model receipts. It never loads these documents into the Supabase maintenance knowledge index and has no ticket/work-order/notification write capability. Normal maintenance workflows and stored records remain separate. This intentionally avoids extra infrastructure for a small project demo.

## Actual recordings and evaluation

Recorded 2026-10-25T21:42:16.268586+00:00: **15 scenarios**, with 1 validated demo plan, 4 emergency outcomes and 10 abstentions. Every emergency stopped before normal model work. Model receipts and real outcomes are retained; abstentions are not replaced with scripted successes. One recorded routine extension failed the auditor's citation-membership check and remains an abstention.

A real integration issue was corrected: existing Python validators required bracketed provenance IDs, but the generated JSON schemas did not explain that pattern to the model. The diagnosis, planning and audit schemas now expose it; the diagnosis/planning prompts are versioned to v2 and the policy-audit prompt to v3 and tell the auditor not to treat a proposal's operational fact IDs as policy grants. Validation was preserved.

The independent retrieval check ranks the original report text against five fictional documents, without expected IDs entering the ranker. On 14 source-labeled development queries, macro Precision@3 was 0.5714, Recall@3 0.9048, and Recall@5 1.0000. The graph instead retrieves from normalized symptoms and limits context candidates to three documents. These are different, explicitly scoped query paths. Top-five recall is easy with a five-document corpus; these are not production quality scores or evidence of a retrieval percentage improvement. Relevant policy retrieval does not grant authority to answer a legal question.

[Raw rankings](../output/benchmarks/part2-demo-retrieval.json) · [actual recordings](../apps/web/lib/demo-recordings.json) · [normalized pack](../services/brain/src/brain/demo_data/README.md).

## Reproduce

```powershell
$env:PYTHONPATH="services/brain/src"
python -m evals.demo_benchmark --live
```

The command reads ignored credentials, executes real model calls, saves genuine recordings and retrieval measurements, and consumes provider tokens. It does not import policy fixtures or write resident records. Recorded exploration is free of per-visit model calls. Live outcomes may vary and must continue to pass validation.

## Completion and boundaries

No human policy-source handoff is required for this demo. The previous policy checklist PDF is superseded accordingly. Real-property use would still require verified sources, real staff/vendor records and operational acceptance; this release does not claim those.

MCP, personal cross-session memory and semantic RAGAS faithfulness are not claimed as implemented here. The demo uses the existing model gateway, contextual retrieval, bounded multi-agent orchestration, per-run memory, PII/injection screening and deterministic authority boundaries. Scope-specific future extensions remain documented in PART-2-GENAI.md.

## Release verification

Code release d72f4c0 passed 354 local Python tests, full mypy across 124 files, frontend build/type checks, the expanded proxy contract suite, Web CI and Python/PostgreSQL CI. Both Vercel projects were deployed. The main-page link, recorded exploration, emergency scenario and genuine authenticated fresh four-stage assessment were verified in the deployed browser. Layout checks at 558px and 1265px found no horizontal overflow. No production policy import or operational write was performed. [Release evidence](RELEASE-STATUS.md).
