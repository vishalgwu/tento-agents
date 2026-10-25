/** Audited implementation profile. Keep aligned with docs/ENGINEERING.md. */
export const runtimeCapabilities = [
  {
    number: "01",
    title: "Models, with an explicit route",
    tag: "LLM + ROUTING",
    detail:
      "OpenAI gpt-4.1-mini serves intake, diagnosis, planning and policy audit through a typed gateway. Task tiers are logical; the live composition maps every tier to one configured model. Anthropic is a configuration alternative, not automatic request failover.",
    source: "services/brain/src/brain/production.py",
  },
  {
    number: "02",
    title: "Grounding before generation",
    tag: "RAG + CONTEXT",
    detail:
      "PostgreSQL lexical retrieval filters policy evidence by organization, jurisdiction and effective date. Citation spans and immutable policy claims feed a whole-block context budget: 8,000 tokens overall, including a 1,600-token policy slot. Approved live policies are still required.",
    source: "services/brain/src/brain/production.py",
  },
  {
    number: "03",
    title: "Specialists, working in sequence",
    tag: "MULTI-AGENT + MEMORY",
    detail:
      "LangGraph coordinates deterministic safety, intake, retrieval, diagnosis, dispatch planning and an independent policy audit. Typed handoffs constrain each stage. MemorySaver holds per-run state; PostgreSQL saves durable jobs and results. Interrupted jobs restart the graph, not a suspended model call.",
    source: "services/brain/src/brain/graph/builder.py",
  },
  {
    number: "04",
    title: "A tenant boundary at every layer",
    tag: "SUPABASE + UPSTASH",
    detail:
      "Supabase provides PostgreSQL and signed authentication. Explicit organization predicates reinforce transaction-local RLS. Upstash Redis supplies rate-limit counters; PostgreSQL stores idempotency receipts. There is no shared semantic answer cache or cross-session personal memory.",
    source: "services/api/src/api/main.py",
  },
  {
    number: "05",
    title: "Safety before authority",
    tag: "GUARDRAILS + PII",
    detail:
      "Deterministic safety checks, local injection screening, PII redaction, typed untrusted prompt context, schema validation and evidence checks surround model work. Models propose; server code controls writes. JWT checks, restricted database roles, HttpOnly cookies and same-origin mutations protect access. These are defenses, not a claim of injection immunity.",
    source: "services/brain/src/brain/guardrails/injection.py",
  },
  {
    number: "06",
    title: "Bounded work. Inspectable receipts.",
    tag: "LATENCY + EXECUTION",
    detail:
      "Ticket and job commit before assessment. The runtime uses a 15-second gateway-call timeout, 1,024 output tokens per configured route, a 12-step graph cap, a 180-second worker execution limit and at most three job attempts with fenced leases. These are limits, not measured response-time promises.",
    source: "services/api/src/api/worker.py",
  },
] as const;

export const engineeringBoundaries = [
  {
    title: "Embeddings & reranking",
    status: "Code + tests",
    detail:
      "The verified-source importer uses text-embedding-3-small (1,536 dimensions) with an in-memory embedding cache and PostgreSQL vector storage. Hybrid RRF and BAAI/bge-reranker-v2-m3 modules are tested independently; the live query path remains lexical and the cross-encoder is omitted from the minimal runtime.",
    source: "services/brain/src/brain/retrieval/rerank.py",
  },
  {
    title: "Evaluation, with reproducible inputs",
    status: "Offline harness",
    detail:
      "Versioned retrieval fixtures support Recall@5/10, MRR and nDCG@10 reports stamped with a Git revision. Injection and fair-housing fixtures test specific boundaries. Scripted tests and CI are evidence of tested cases, not a published live retrieval-quality score.",
    source: "evals/README.md",
  },
  {
    title: "MCP integration boundary",
    status: "Not integrated",
    detail:
      "A typed tool-grant vocabulary and authorization module provide an extension seam. No application MCP client/server transport is wired into the production agent. Development/deployment connectors are separate from application runtime integrations.",
    source: "services/brain/src/brain/guardrails/tool_auth.py",
  },
  {
    title: "Temperature & structured output",
    status: "Provider default",
    detail:
      "The OpenAI adapter requests JSON-object output followed by Pydantic validation, with an explicit output-token cap. Temperature is not explicitly set. A temperature of zero is not claimed, and JSON mode alone is not treated as schema correctness.",
    source: "services/brain/src/brain/gateway/client.py",
  },
  {
    title: "Speed, latency & TTFT",
    status: "Partially instrumented",
    detail:
      "Per-call elapsed latency, token usage and cache-read token counts are recorded. Model completions are not token-streamed; saved run snapshots are not a token stream. TTFT (time to first token), p50/p95 latency and production throughput benchmarks have not been published.",
    source: "services/brain/src/brain/gateway/client.py",
  },
  {
    title: "Cost & caching accountability",
    status: "Unpriced usage",
    detail:
      "Token counts and prompt/version receipts support later costing. The current adapters do not calculate a priced dollar total: the cost field defaults to zero and does not mean free inference. Provider-reported cached tokens are recorded; Anthropic has an explicit prefix-cache boundary. No measured cache-hit or cost-saving percentage is claimed.",
    source: "services/brain/src/brain/gateway/client.py",
  },
] as const;

export const modelRoutes = [
  { task: "Intake normalization", tier: "Small", model: "gpt-4.1-mini" },
  { task: "Diagnosis", tier: "Mid", model: "gpt-4.1-mini" },
  { task: "Dispatch planning", tier: "Mid", model: "gpt-4.1-mini" },
  { task: "Policy audit", tier: "Small", model: "gpt-4.1-mini" },
] as const;
