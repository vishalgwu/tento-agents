# Part 2: measured GenAI engineering

Part 1 is the deployed MVP recorded at `156133f`: four workspaces, authenticated maintenance reporting, autonomous bounded assessment and safe abstention. Its records and access boundaries are preserved.

## Part 2A: implemented measurement and caching upgrade

- **Routing:** server-owned small/mid/large model overrides via OPENAI_MODEL_SMALL/MID/LARGE. Blank overrides retain OPENAI_MODEL. Current deployment remains GPT-4.1-mini across the active stages; no untested model switch or automatic escalation is implied.
- **Generation controls:** validated finite temperature in [0,2], explicit production temperature 0 for the current model, and configurable output cap. Omit temperature for models which do not support it. Temperature 0 is not a guarantee of identical outputs.
- **Streaming measurement:** first non-empty provider content is timed with a monotonic clock. Partial JSON remains private until completion and Pydantic validation. Interrupted, refused and truncated streams fail safely and close the connection.
- **Cost estimates:** versioned standard GPT-4.1-mini rates distinguish uncached input, cached input and output. Per-attempt estimates populate existing audit receipts; content-free worker logs include price version and first-content latency. Unknown models or missing usage are marked unpriced in logs. Historic zero receipts are not retroactively priced.
- **Upstash embedding reuse:** verified-source ingestion uses a tenant-scoped, model/content-keyed Redis vector cache with a 24-hour TTL, validated dimensions, bounded values and fail-open cache misses. It stores no raw source text and confers no source authority. Ingestion still rejects synthetic fixtures. No conversational or semantic answer cache is introduced.
- **Reproducibility:** opt-in benchmark CLIs save dataset/source hashes, exact route settings, sample counts, observations, token usage and measured tails. They never connect to the production database.

## Recorded measurements — 25 October 2026

| Measurement | Observed result | Scope |
| --- | ---: | --- |
| Intake latency p50 / p95 | 0.740s / 0.876s | 30 sequential synthetic runs; six unique reports |
| Provider first-content p50 / p95 | 0.391s / 0.562s | Worker-to-provider stream; not browser-visible token delivery |
| Slowest intake run | 9.734s | Includes the first-run tail; no samples discarded |
| Schema-valid completions | 30 / 30 | Intake schema and authoritative access/pet fields |
| Estimated model token cost | $0.009739 total; $0.000325 per run | 30 priced completed streams; standard text-token estimate |
| Embedding lookup p95, miss → repeat hit | 320.355ms → 12.762ms | 20 synthetic paired single-text inputs, OpenAI + hosted Redis |
| Warm lookup p95 reduction | 96.0% | Relative to paired cache misses, not whole-app latency |
| Repeat embedding provider calls | 0 / 20 | 20 cold calls followed by 20 reuse requests |

Raw evidence: [intake run](../output/benchmarks/part2-intake-temperature-zero.json), [cache run](../output/benchmarks/part2-embedding-cache.json), and [initial development baseline](../output/benchmarks/part2-intake-baseline.json). Source hashes distinguish the exact measured implementations from the parent Git revision. Sample repetition and miss-then-hit ordering limit statistical generalization. The earlier baseline is retained, not presented as a controlled before/after experiment.

Rates: [official GPT-4.1-mini documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini), checked 25 October 2026: $0.40 uncached input, $0.10 cached input and $1.60 output per million tokens. Estimates exclude embedding API charges, infrastructure, tax and interrupted attempts without final usage. Reconcile actual charges with provider billing.

## Resume bullets supported by these runs

- **Instrumented and benchmarked GPT-4.1-mini intake** across **30 synthetic runs (six unique reports)**, measuring **0.876s p95 intake latency**, **0.562s p95 provider first-content latency** and **$0.000325 estimated token cost per run**.
- **Implemented a tenant-isolated Upstash embedding cache**, reducing warm lookup p95 by **96.0% (320.4ms to 12.8ms)** and avoiding **20 repeat provider calls** in a **20-pair synthetic OpenAI/Redis benchmark**.

Keep the sample scope with each bullet. These are development benchmark results, not production SLAs, user repair-time improvements, RAG faithfulness scores or aggregate LLM cost savings. The first intake tail was 9.734s. No percentage reliability gain or retrieval improvement is inferred from passing unit tests.

## Reproduce

Use the existing ignored .env; credentials are read internally. Each --live command consumes provider tokens. These commands do not import policies or modify resident records.

```powershell
$env:PYTHONPATH="services/brain/src"
python -m evals.model_benchmark --live --samples 30 --output output/benchmarks/intake-new.json
python -m evals.cache_benchmark --live --samples 20 --output output/benchmarks/cache-new.json
```

The cache benchmark uses a random tenant namespace, 60-second test TTL and explicit cleanup. Production ingestion retains its 24-hour TTL. The model benchmark's first request includes local startup work; provider TTFT starts immediately before the SDK request. There is no warm-up exclusion.

## Part 2B: supplied-policy demo completed

The supplied synthetic Maple Court pack resolves the demo's policy-data dependency. Five normalized fixture sources, ten exact-span claims and fifteen scenarios now support an isolated public recorded explorer and authenticated live graph reruns at [/demo](https://tento-resident-os.vercel.app/demo). No real-property approval is needed for this project demo. [Implementation, measured retrieval results and boundaries](DEMO.md).

The earlier read-only check of the maintenance tenant remains historical evidence: its approved index had no policy sources. Synthetic demo sources have not been promoted into that index. Real-property operation would still require verified sources. The previous human-source checklist is superseded for demonstration use.

## Part 2C: tool and memory extensions

Add MCP only for a concrete authenticated read-tool consumer or an approved external service; preserve server-owned tenant scope and narrow grants. Persistent conversational memory needs a defined resident interaction, retention/deletion policy and cross-session authorization tests. The current run checkpoints and durable PostgreSQL results remain the appropriate execution memory for this MVP. These extensions are not advertised as shipped capabilities.

## Verification

Local validation: 348 Python tests passed; five isolated PostgreSQL tests require a dedicated migrated *_test database. Hosted Upstash round-trip, tenant isolation, TTL and cleanup passed. Ruff lint/format and focused type checks passed. Full mypy passed across 119 files; web proxy regression, TypeScript, production build, Python CI and real PostgreSQL integration passed. Both Vercel projects were deployed and production health/access checks passed. [Release evidence](RELEASE-STATUS.md).
