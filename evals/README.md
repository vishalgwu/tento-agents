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
