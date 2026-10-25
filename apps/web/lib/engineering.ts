/** Audited implementation profile. Keep aligned with docs/ENGINEERING.md. */
export const runtimeCapabilities = [
  {
    number: "01",
    title: "Models, with an explicit route",
    tag: "LLM + ROUTING",
    detail:
      "OpenAI gpt-4.1-mini serves intake, diagnosis, planning and policy audit through a typed gateway at temperature 0. Deployment-owned tier overrides support independent model configuration. Task tiers are logical; the live composition maps every tier to one configured model. Structured responses are validated before the next stage receives them.",
    source: "services/brain/src/brain/production.py",
  },
  {
    number: "02",
    title: "Grounding before generation",
    tag: "RAG + CONTEXT",
    detail:
      "PostgreSQL lexical retrieval filters policy evidence by organization, jurisdiction and effective date. Citation spans and immutable policy claims feed a whole-block context budget: 8,000 tokens overall, including a 1,600-token policy slot. The fictional demo uses a separate five-document SQLite FTS5/BM25 index with exact-span evidence; its sources stay outside the maintenance index.",
    source: "services/brain/src/brain/production.py",
  },
  {
    number: "03",
    title: "Specialists, working in sequence",
    tag: "MULTI-AGENT + MEMORY",
    detail:
      "LangGraph coordinates deterministic safety, intake, retrieval, diagnosis, dispatch planning and an independent policy audit. Typed handoffs constrain each stage. MemorySaver holds per-run state; PostgreSQL saves durable jobs and results. Fenced leases coordinate retry recovery for interrupted jobs.",
    source: "services/brain/src/brain/graph/builder.py",
  },
  {
    number: "04",
    title: "A tenant boundary at every layer",
    tag: "SUPABASE + UPSTASH",
    detail:
      "Supabase provides PostgreSQL and signed authentication. Explicit organization predicates reinforce transaction-local RLS. Upstash Redis supplies rate-limit counters; PostgreSQL stores idempotency receipts. Saved receipts support repeatable request handling.",
    source: "services/api/src/api/main.py",
  },
  {
    number: "05",
    title: "Safety before authority",
    tag: "GUARDRAILS + PII",
    detail:
      "Deterministic safety checks, local injection screening, PII redaction, typed untrusted prompt context, schema validation and evidence checks surround model work. Models propose; server code controls writes. JWT checks, restricted database roles, HttpOnly cookies and same-origin mutations protect access. Each stage works within server-controlled access boundaries.",
    source: "services/brain/src/brain/guardrails/injection.py",
  },
  {
    number: "06",
    title: "Bounded work. Inspectable receipts.",
    tag: "LATENCY + EXECUTION",
    detail:
      "Ticket and job commit before assessment. The runtime uses a 15-second gateway-call timeout, 1,024 output tokens per configured route, a 12-step graph cap, a 180-second worker execution limit and at most three job attempts with fenced leases. Prompt versions, usage and outcomes are retained in execution receipts.",
    source: "services/api/src/api/worker.py",
  },
] as const;

export const engineeringPractices = [
  {
    title: "Structured generation",
    status: "Validated",
    detail:
      "The model gateway requests JSON-object output and validates each specialist response with Pydantic before it enters workflow state. Refused, empty and truncated completions are handled through typed failure paths.",
    source: "services/brain/src/brain/gateway/client.py",
  },
  {
    title: "Evaluation and regression testing",
    status: "Tested",
    detail:
      "Versioned retrieval, injection and fair-housing fixtures support reproducible checks. Automated unit, contract and PostgreSQL integration tests exercise tenant isolation, safety, retries and saved workflow behavior.",
    source: "evals/README.md",
  },
  {
    title: "Execution observability",
    status: "Recorded",
    detail:
      "Model-call receipts retain prompt versions, input/output token usage, cached-token counts, elapsed latency and outcomes. Content-free worker logs add provider first-content timing and versioned token-cost estimates. Saved agent steps and guardrail receipts make each assessment traceable.",
    source: "services/brain/src/brain/gateway/client.py",
  },
  {
    title: "Measured intake latency",
    status: "Synthetic benchmark",
    detail:
      "30 sequential synthetic intake runs over six unique reports measured 0.876s p95 intake latency and 0.562s p95 provider first-content latency. The slowest run was 9.734s. This is a local development benchmark, not a production SLA. Raw observations and configuration are published.",
    source: "docs/PART-2-GENAI.md",
  },
  {
    title: "Measured embedding reuse",
    status: "Paired benchmark",
    detail:
      "A tenant-scoped Upstash embedding cache avoided 20 repeat provider calls in 20 synthetic miss/hit pairs. Warm lookup p95 fell from 320.4ms to 12.8ms (96.0%). This measures embedding reuse, not full ticket processing. Verified-source ingestion preserves source eligibility checks.",
    source: "docs/PART-2-GENAI.md",
  },
] as const;

export const modelRoutes = [
  { task: "Intake normalization", tier: "Small", model: "gpt-4.1-mini" },
  { task: "Diagnosis", tier: "Mid", model: "gpt-4.1-mini" },
  { task: "Dispatch planning", tier: "Mid", model: "gpt-4.1-mini" },
  { task: "Policy audit", tier: "Small", model: "gpt-4.1-mini" },
] as const;

/** Public results: scope and evidence are mandatory alongside every number. */
export const verifiedResults = [
  {
    value: "96.0%",
    title: "Lower warm embedding lookup p95",
    scope:
      "320.4ms → 12.8ms in 20 synthetic OpenAI/Upstash miss-hit pairs; 20 repeat provider calls avoided.",
    source: "output/benchmarks/part2-embedding-cache.json",
  },
  {
    value: "0.876s",
    title: "Measured intake p95",
    scope:
      "30 synthetic runs over six reports. Provider first-content p95: 0.562s; slowest intake: 9.734s. Local benchmark.",
    source: "output/benchmarks/part2-intake-temperature-zero.json",
  },
  {
    value: "40 cases",
    title: "Prompt-injection boundary coverage",
    scope:
      "Five synthetic ingress types. All 40 tests rejected write-capable untrusted context; this measures a capability boundary, not universal detection accuracy.",
    source: "services/brain/tests/test_injection_dataset.py",
  },
  {
    value: "4 stages",
    title: "Typed agent orchestration",
    scope:
      "Intake, diagnosis, planning and policy audit use validated Pydantic handoffs, bracketed citations and server-controlled authority.",
    source: "services/brain/src/brain/graph/nodes.py",
  },
  {
    value: "15 scenarios",
    title: "Inspect the grounded demo",
    scope:
      "Five fictional policy documents, ten exact-span claims and genuine recorded/live results. Four recorded emergencies stopped before model calls.",
    source: "docs/DEMO.md",
  },
  {
    value: "354 tests",
    title: "Verified engineering checks",
    scope:
      "Python regressions passed, alongside PostgreSQL integration, full type checks, frontend builds and authenticated web contract checks.",
    source: "docs/RELEASE-STATUS.md",
  },
] as const;
