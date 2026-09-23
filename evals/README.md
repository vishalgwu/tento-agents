# Evaluation datasets

This directory contains versioned evaluation fixtures, not production
knowledge. They measure retrieval quality without granting authority to make a
resident, vendor, owner, legal, or safety decision.

## `datasets/retrieval_v1.jsonl`

The retrieval benchmark has exactly 50 newline-delimited JSON records. Each
record has a stable `id`, a realistic `query`, a `query_type`, the one or more
source `expected_document_ids`, and `should_retrieve`. A date-sensitive case
also includes `ticket_occurred_at` in UTC. The retriever must use that ticket
time to apply effective-date filtering; it must not substitute the current
time.

The dataset intentionally covers 12 natural-resident queries, 8 identifier
lookups, 10 synonym/paraphrase queries, 8 jurisdiction-specific queries, 7
effective-date-sensitive queries, and 5 abstention/no-match queries. Expected
document IDs are resolved against the temporary evaluation-only `knowledge/`
fixture register. A match measures source retrieval only; it never makes a
temporary fixture suitable for a live answer or action.

Keep this file human-authored and edit it without running a retriever first.
When a knowledge document is revised, update the source ID or time metadata
only after a reviewer verifies the expected source. The integrity test at
`services/brain/tests/test_retrieval_dataset.py` prevents accidental schema,
count, lifecycle, and identifier drift.

## Measuring retrieval

`retrieval.py` scores document IDs, not arbitrary chunk text, so all strategies
are compared against the same human-authored expected sources. Supply one JSON
object containing a complete ranking for every dataset item and each required
strategy:

```json
{
  "dense_only": {"retrieval-001": ["SOP-PLM-04"]},
  "lexical_only": {"retrieval-001": ["SOP-PLM-04"]},
  "hybrid_rrf": {"retrieval-001": ["SOP-PLM-04"]},
  "hybrid_rerank": {"retrieval-001": ["SOP-PLM-04"]}
}
```

Run the evaluator only after collecting all 50 real rankings from the same
fixture index. It writes a Markdown table with recall@5/10, MRR, nDCG@10,
no-match accuracy, and the exact checked-out Git SHA:

```powershell
.\tento\Scripts\python.exe evals\retrieval.py `
  --rankings path\to\retrieval-rankings.json `
  --output evals\reports\retrieval-v1.md `
  --require-rerank-lift
```

The final flag exits non-zero after publishing the report if hybrid + rerank
does not improve at least one measured metric without regressing any retrieval
or no-match metric. Delete the reranker rather than keeping an unmeasured or
non-improving component. Do not commit a made-up report: the repository has no
published retrieval numbers until a real run produces one.
