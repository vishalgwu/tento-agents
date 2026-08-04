# 03 — Platform Engineering

---

## 1. Database schema

Postgres 15+ on Supabase, with `pgvector`, `pg_trgm`, `pgcrypto`. Multi-tenant by `org_id` with Row Level Security everywhere.

### 1.1 Tenancy and the ontology

```sql
create table orgs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  plan text not null default 'trial',
  settings jsonb not null default '{}',      -- autonomy dials, SLA overrides, quiet hours
  created_at timestamptz not null default now()
);

create table properties (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  name text not null,
  address jsonb not null,
  jurisdiction text not null,                -- 'US-VA' → drives habitability SLA + KB filter
  timezone text not null default 'America/New_York',
  unit_count int
);

create table buildings (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  property_id uuid not null references properties on delete cascade,
  name text not null                          -- 'Wing A' / 'Tower 2'
);

create table units (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  building_id uuid not null references buildings on delete cascade,
  label text not null,                        -- '4B'
  bedrooms int, bathrooms numeric(3,1), sqft int,
  floor int,
  unique (building_id, label)
);
```

**Why `jurisdiction` is on `property` and not derived at query time:** habitability SLAs, notice periods, and source-of-income protections are state and city specific. Making it an explicit column means the KB filter, the SLA table, and the audit record all agree, and a portfolio spanning VA/MD/DC behaves correctly without special cases. Getting this wrong is how a compliance product becomes a compliance liability.

### 1.2 People

```sql
create table people (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  auth_user_id uuid unique,                   -- Supabase auth
  display_name text not null,
  email citext, phone text,
  preferred_language text default 'en',
  preferred_channel text default 'push',
  created_at timestamptz not null default now()
);

create table roles (
  person_id uuid not null references people on delete cascade,
  org_id uuid not null references orgs on delete cascade,
  scope_type text not null check (scope_type in ('org','property','building','unit')),
  scope_id uuid not null,
  role text not null check (role in ('owner','manager','staff','tech','resident','vendor')),
  primary key (person_id, scope_type, scope_id, role)
);

create table tenancies (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  unit_id uuid not null references units on delete cascade,
  person_id uuid not null references people on delete cascade,
  lease_document_id uuid,
  starts_on date not null, ends_on date,
  is_primary boolean not null default true
);
```

**Deliberate omission:** there is no column anywhere in this schema for race, ethnicity, religion, disability, familial status, national origin, immigration status, sexual orientation, or health condition. Not "we don't populate it" — **the columns do not exist.** A schema that cannot store a protected attribute cannot leak, infer from, or be subpoenaed for one. If accessibility needs must be recorded for legitimate accommodation, they live in a separate, access-controlled `accommodations` table with its own audit trail and are **never** joined into any prompt-building query. This is a five-minute design decision that eliminates an entire category of risk, and it's the kind of thing that makes a security reviewer trust the rest of your work.

### 1.3 Assets and work

```sql
create table assets (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  unit_id uuid references units on delete cascade,
  building_id uuid references buildings on delete cascade,   -- common-area assets
  kind text not null,                          -- 'water_heater','hvac','disposal'
  make text, model text, serial text,
  installed_on date,
  warranty_expires_on date,
  last_serviced_on date,
  metadata jsonb not null default '{}',
  check (unit_id is not null or building_id is not null)
);

create type ticket_priority as enum ('P0','P1','P2','P3');
create type ticket_status   as enum ('new','triaging','awaiting_approval','scheduled',
                                     'in_progress','awaiting_parts','resolved','closed','cancelled');

create table tickets (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  unit_id uuid not null references units on delete cascade,
  reported_by uuid references people,
  channel text not null default 'app',
  raw_text text,
  status ticket_status not null default 'new',
  priority ticket_priority,
  category text, subcategory text,
  responsible_party text check (responsible_party in ('owner','resident','third_party','undetermined')),
  asset_id uuid references assets,
  entry_permission boolean,
  sla_due_at timestamptz,
  resolved_at timestamptz,
  reopened_from uuid references tickets,
  created_at timestamptz not null default now()
);
create index on tickets (org_id, status, sla_due_at);
create index on tickets (unit_id, created_at desc);

create table ticket_media (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets on delete cascade,
  storage_path text not null,
  kind text not null,                          -- 'image','audio'
  caption text,                                -- vision-model output, cached
  caption_model text
);

create table work_orders (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  ticket_id uuid not null references tickets on delete cascade,
  vendor_id uuid references vendors,
  assigned_tech uuid references people,
  trade text not null,
  scheduled_window tstzrange,
  estimated_cost_cents int,
  actual_cost_cents int,
  first_time_fix boolean,
  external_ref text,                           -- PMS work order id
  status text not null default 'proposed'
);

create table vendors (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  name text not null, trades text[] not null,
  phone text, email citext,
  service_area jsonb,
  insurance_expires_on date,
  is_active boolean not null default true
);

create table vendor_scores (                    -- rebuilt nightly
  vendor_id uuid primary key references vendors on delete cascade,
  accept_rate numeric, avg_response_minutes numeric,
  first_time_fix_rate numeric, avg_cost_variance numeric,
  jobs_90d int, updated_at timestamptz not null default now()
);
```

### 1.4 The AI spine — the tables that make this project different

```sql
create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  ticket_id uuid references tickets on delete cascade,
  workflow text not null,                      -- 'maintenance_triage'
  workflow_version text not null,
  status text not null,                        -- running|completed|failed|escalated
  council_used boolean not null default false,
  final_confidence numeric,
  total_input_tokens int, total_output_tokens int,
  total_cost_micros bigint,
  latency_ms int,
  started_at timestamptz not null default now(),
  ended_at timestamptz
);

create table agent_steps (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references agent_runs on delete cascade,
  seq int not null,
  agent text not null,
  node text not null,
  status text not null,
  input_digest text,                           -- sha256, not the payload
  output jsonb,                                -- typed contract
  error jsonb,
  latency_ms int,
  unique (run_id, seq)
);

create table llm_calls (
  id uuid primary key default gen_random_uuid(),
  step_id uuid not null references agent_steps on delete cascade,
  provider text not null, model text not null, model_version text,
  prompt_version text not null,                -- 'diagnose@v7'
  prompt_hash text not null,                   -- sha256 of the rendered prompt
  input_tokens int, cached_input_tokens int, output_tokens int,
  cost_micros bigint,
  temperature numeric, seed bigint,
  latency_ms int,
  finish_reason text
);

create table retrievals (
  id uuid primary key default gen_random_uuid(),
  step_id uuid not null references agent_steps on delete cascade,
  query text not null,
  strategy text not null,                      -- 'hybrid_rrf_rerank'
  kb_version text not null,
  results jsonb not null                       -- [{chunk_id, doc_id, bm25_rank, vec_rank, rrf, rerank_score, used}]
);

create table guardrail_events (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null,
  run_id uuid references agent_runs on delete cascade,
  guardrail text not null,                     -- 'fair_housing','pii','injection',...
  stage text not null,                         -- 'pre_llm','post_llm','pre_send'
  verdict text not null,                       -- 'pass','block','redact','flag'
  detail jsonb,
  created_at timestamptz not null default now()
);

create table decisions (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  run_id uuid not null references agent_runs on delete cascade,
  ticket_id uuid not null references tickets on delete cascade,
  kind text not null,                          -- 'triage','dispatch','chargeback','message'
  proposed jsonb not null,
  final jsonb,
  citations jsonb not null,                    -- [{claim, citation_id, doc_id, version}]
  confidence numeric not null,
  mode text not null,                          -- 'auto','approved','overridden','escalated'
  decided_by uuid references people,
  override_reason text,                        -- taxonomy value → eval label
  decided_at timestamptz
);
create index on decisions (org_id, decided_at desc);

create table approvals (
  id uuid primary key default gen_random_uuid(),
  decision_id uuid not null references decisions on delete cascade,
  token text not null unique,                  -- single-use, scoped, passed to act-MCP
  expires_at timestamptz not null,
  consumed_at timestamptz
);
```

`decisions` is the product. Everything else supports it. An auditor asking *"why did unit 4B get charged $180 on March 3?"* gets: the run, every step, every prompt hash, every retrieved chunk with its document version, every guardrail verdict, the confidence, who approved it, and — if they override — why. That's a complete evidentiary chain, and no competitor ships one.

**Immutability:** `decisions`, `guardrail_events`, and `llm_calls` are append-only. Enforce with a trigger that raises on UPDATE/DELETE, plus a nightly hash-chain (`prev_hash → row_hash`) so tampering is detectable. Cheap, and it converts "we log things" into "we can prove what we logged."

### 1.5 Knowledge base and memory

```sql
create table kb_documents (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs on delete cascade,   -- null = global
  doc_key text not null,                            -- 'SOP-PLM-04'
  version int not null,
  title text not null,
  authority text not null check (authority in ('statute','lease','internal_sop','vendor_contract')),
  jurisdiction text[],
  scope jsonb not null default '{}',
  effective_from date not null,
  effective_to date,
  content_sha256 text not null,
  source_path text not null,                        -- git path
  unique (doc_key, version)
);

create table kb_chunks (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references kb_documents on delete cascade,
  org_id uuid,
  parent_id uuid references kb_chunks,              -- parent-document retrieval
  ord int not null,
  heading_path text,
  content text not null,
  embedding halfvec(1536),
  embedding_model text not null,
  ts tsvector generated always as (to_tsvector('english', content)) stored
);
create index on kb_chunks using hnsw (embedding halfvec_cosine_ops) with (m=16, ef_construction=64);
create index on kb_chunks using gin (ts);
create index on kb_chunks (document_id, ord);

create table episodic_memory (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  property_id uuid references properties,
  ticket_id uuid references tickets,
  summary text not null,                            -- symptom → diagnosis → resolution → outcome
  embedding halfvec(1536),
  outcome text,                                     -- 'resolved_first_time','reopened','escalated'
  occurred_at timestamptz not null,
  decay_after timestamptz
);

create table reflections (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  scope_type text not null, scope_id uuid not null,
  claim text not null,
  evidence_ticket_ids uuid[] not null,
  confidence numeric not null,
  status text not null default 'proposed',          -- proposed|approved|rejected|expired
  approved_by uuid references people,
  embedding halfvec(1536),
  valid_from timestamptz not null default now(),
  valid_to timestamptz
);
```

### 1.6 Notifications

```sql
create table notifications (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references orgs on delete cascade,
  recipient_id uuid not null references people,
  tier text not null check (tier in ('U0','U1','U2','U3')),
  type text not null,
  entity_type text, entity_id uuid,
  dedupe_key text,
  template_key text not null,
  rendered jsonb,
  channel text, status text not null default 'queued',
  scheduled_for timestamptz, sent_at timestamptz, acked_at timestamptz,
  suppressed_reason text,                            -- 'fatigue_budget','quiet_hours','preempted'
  attempt int not null default 0
);
create unique index on notifications (dedupe_key, recipient_id)
  where status in ('queued','sent') and dedupe_key is not null;

create table notification_budgets (
  person_id uuid not null references people on delete cascade,
  tier text not null,
  window_start date not null,
  used int not null default 0,
  primary key (person_id, tier, window_start)
);
```

### 1.7 Evaluation

```sql
create table eval_datasets (
  id uuid primary key, name text not null, version int not null, item_count int
);
create table eval_items (
  id uuid primary key, dataset_id uuid references eval_datasets on delete cascade,
  input jsonb not null, expected jsonb not null, labeled_by text, notes text
);
create table eval_runs (
  id uuid primary key default gen_random_uuid(),
  dataset_id uuid references eval_datasets,
  git_sha text not null, prompt_versions jsonb not null,
  judge_model text, metrics jsonb not null,
  passed boolean not null, created_at timestamptz not null default now()
);
```

### 1.8 RLS

```sql
alter table tickets enable row level security;
create policy tenant_isolation on tickets
  using (org_id = (auth.jwt() ->> 'org_id')::uuid);

create policy resident_own_unit on tickets for select
  using (
    org_id = (auth.jwt() ->> 'org_id')::uuid
    and (
      (auth.jwt() ->> 'role') in ('manager','staff','owner')
      or unit_id in (select unit_id from tenancies
                     where person_id = (auth.jwt() ->> 'person_id')::uuid
                       and (ends_on is null or ends_on >= current_date))
    )
  );
```

RLS is the second line. The API layer scopes every query explicitly too — belt and suspenders, because a single service-role query that bypasses RLS is a cross-tenant data leak, and in this domain that's a breach notification.

---

## 2. API design

FastAPI, `/api/v1`, OpenAPI auto-generated, RFC 7807 problem-details errors.

```
POST   /v1/tickets                      create (idempotency-key header required)
GET    /v1/tickets?status=&priority=&property_id=&cursor=
GET    /v1/tickets/{id}
GET    /v1/tickets/{id}/stream          SSE: triage progress, token stream, step events
POST   /v1/tickets/{id}/messages        resident/staff message

GET    /v1/approvals?assignee=me        the queue
POST   /v1/approvals/{id}/approve       {edits?: {...}}
POST   /v1/approvals/{id}/reject        {reason_code, note}   ← reason_code = eval label
POST   /v1/approvals/{id}/reassign

GET    /v1/runs/{id}                    full trace (steps, llm_calls, retrievals, guardrails)
GET    /v1/runs/{id}/replay             deterministic re-execution against pinned versions
GET    /v1/decisions?from=&to=&mode=    audit query
GET    /v1/decisions/export             signed audit bundle (JSON + PDF)

GET    /v1/knowledge/search?q=          hybrid search w/ scores (demo surface)
POST   /v1/knowledge/reindex            admin

GET    /v1/metrics/agents               health per agent
GET    /v1/metrics/cost?group_by=       cost dashboards
GET    /v1/evals/runs                   eval history

POST   /v1/webhooks/vendor              inbound vendor SMS/email (untrusted → quarantine)
POST   /v1/webhooks/pms                 PMS sync
```

**Conventions worth naming in an interview:**

- **Idempotency keys on every mutating endpoint**, stored with the response hash. A resident double-tapping "submit" during a network blip must not create two tickets and two dispatches. Agentic systems retry; without idempotency, retries become duplicate real-world actions.
- **SSE, not WebSockets.** One-directional streaming, works through every proxy, trivially reconnectable, and Vercel handles it. WebSockets buy you nothing here and cost you operational complexity.
- **Cursor pagination** (`created_at, id`), never offset — offset pagination degrades and skips rows under concurrent insert.
- **Everything long-running is a job.** POST returns `202` with a run id; the client subscribes. No HTTP request waits on a council.
- **`GET /runs/{id}/replay` is the killer endpoint.** Re-executes a past decision against the pinned prompt version, model version, and KB version, then diffs against the original. It's how you debug, how you prove non-regression, and how you answer an auditor. Build it in week 5.

---

## 3. Monorepo layout

```
resident-os/
├── CLAUDE.md                      # ← agent context: how to work in this repo
├── README.md                      # ← the 90-second pitch (see 04)
├── docs/
│   ├── 00-product.md              # your 6 context files live here
│   ├── 01-architecture.md
│   ├── 02-rules.md                # coding rules, invariants, "never do this"
│   ├── 03-phases.md
│   ├── 04-design-system.md
│   ├── 05-memory.md               # decisions log — what we chose and why
│   ├── adr/                       # architecture decision records, numbered
│   └── evals/REPORT.md            # ← the public eval report
├── apps/
│   ├── web/                       # Next.js 15 (App Router) — resident/manager/owner
│   └── docs-site/                 # optional: architecture explorer (static)
├── services/
│   ├── api/                       # FastAPI
│   │   ├── src/api/routers/
│   │   ├── src/api/deps/          # auth, tenancy, rate limit
│   │   └── src/api/schemas/
│   ├── brain/                     # the AI package — importable, framework-agnostic core
│   │   ├── src/brain/agents/      # one file per agent, plain async fns
│   │   ├── src/brain/graph/       # LangGraph wiring ONLY (thin)
│   │   ├── src/brain/context/     # broker, budgeter, envelope, compression
│   │   ├── src/brain/retrieval/   # hybrid, rrf, rerank, parent-doc
│   │   ├── src/brain/memory/      # 4 stores + MemoryProvider interface
│   │   ├── src/brain/guardrails/  # each guardrail = a testable function
│   │   ├── src/brain/council/
│   │   ├── src/brain/judge/
│   │   ├── src/brain/prompts/     # versioned .md.j2 files, hashed at load
│   │   └── src/brain/gateway/     # policy layer (routing, budget, cache)
│   ├── worker/                    # queue consumer: judging, embeddings, notifications
│   └── mcp/                       # three MCP servers
├── packages/
│   ├── shared-types/              # Pydantic ⇄ TypeScript (generated from OpenAPI)
│   └── ui/                        # shadcn-based component library
├── knowledge/                     # the markdown KB (§7.4 of file 02)
├── evals/
│   ├── datasets/golden_v1.jsonl   # 200 human-labeled tickets
│   ├── datasets/redteam_fh.jsonl  # fair-housing paired probes
│   ├── suites/                    # deepeval/ragas suites
│   └── run.py
├── infra/
│   ├── docker-compose.dev.yml     # postgres+pgvector, redis, litellm, langfuse, ollama
│   ├── migrations/                # sqlmodel/alembic
│   └── seed/                      # synthetic property, 400 units, 1,200 tickets
└── .github/workflows/
    ├── ci.yml                     # lint, types, unit, integration
    ├── evals.yml                  # ← the quality gate
    └── deploy.yml
```

**`CLAUDE.md` matters more than it looks.** You are driving Claude Code across a lot of directories on a solo build. Put the invariants there in imperative form — *"Never let a non-orchestrator agent import a write tool. Never summarize policy text with an LLM. Every new agent needs a fixture test and an eval item. Prompts live in `prompts/` and are versioned; never inline a prompt string."* That file is what keeps one human plus one AI assistant from producing two architectures three months apart.

**Directory contract** (see [PHASES.md §2](../docs/PHASES.md) for the full ownership map):

| Concern | Path | Notes |
|---|---|---|
| AI spine | `services/brain`, `evals/`, `knowledge/`, MCP, gateway | prompts, retrieval, guardrails, evals, model routing |
| Product surface | `apps/web`, `packages/ui`, design system | routes, components, auth flows, notification UI |
| Infra + CI/CD | `infra/`, `.github/workflows/` | docker-compose, migrations, seed, deploy |

The contract between spine and surface is `packages/shared-types`, generated from `docs/openapi.yaml`. Freeze the SSE event names and the `TicketState` shape in Phase 0 and you never fight yourself across the seam.

---

## 4. Frontend architecture

**Next.js 15 App Router + TypeScript + Tailwind + shadcn/ui + TanStack Query + Zustand (UI state only).**

- **Server Components for reads, Route Handlers as a BFF.** The Next server holds the session and forwards to FastAPI with a scoped token; the browser never sees a service key.
- **Streaming via SSE** into an event reducer. Render the *steps*, not just the final answer — watching "retrieving policy… 6 sources… council triggered… auditing…" is the product's most persuasive 8 seconds.
- **Optimistic approve/reject** with rollback.
- **Three shells:** `/app` (resident, mobile-first, WhatsApp-adjacent warmth per your design direction), `/manage` (dense, keyboard-first, `j/k` to move the queue, `a` to approve — managers live here all day), `/owner` (read-only, charts, exports).

**Demo surfaces** (these are the recruiter payload — see `04`):

| Surface | Renders | Built from |
|---|---|---|
| Trace viewer | Full run replay, step timeline, expandable prompts w/ hashes | `GET /runs/{id}` |
| Retrieval inspector | Both ranked lists, RRF merge, rerank delta, which chunks made the window | `retrievals` |
| Council view | 3 members side by side, agreement matrix, dissent, synthesis | `agent_steps` |
| Context budget | Stacked bar of the 8k envelope by slot, per run | `llm_calls` + envelope meta |
| Cost dashboard | $/ticket, by agent, by model, cache hit rate, trend | `llm_calls` |
| Agent health | Success rate, p50/p95, schema repair rate, escalation rate per agent | `agent_steps` |
| Eval dashboard | Metric history by commit, pass/fail gates, calibration curve | `eval_runs` |
| Governance | Decisions by mode, override reasons, guardrail events, audit export | `decisions`, `guardrail_events` |

Build these with real data from the seed set. A dashboard with fake numbers is worse than no dashboard — experienced reviewers can tell, and it costs you all your credibility at once.

---

## 5. Backend architecture

```
Vercel Edge ──▶ Next.js (RSC + Route Handlers/BFF)
                     │  JWT (Supabase Auth), org-scoped
                     ▼
              FastAPI (Cloud Run, min-instances=1, autoscale to 10)
                     │
     ┌───────────────┼────────────────┬──────────────┐
     ▼               ▼                ▼              ▼
 Supabase        Upstash Redis    LiteLLM        MCP servers
 Postgres        queue/cache      (Fly)          (Fly, internal)
 +pgvector            │
     ▲                ▼
     │           Worker (Fly): judge, embeddings, notifications,
     └────────── nightly rollups, reflection distillation
```

**Why FastAPI over Node:** the AI ecosystem you need — LangGraph, Pydantic, DeepEval/Ragas, Presidio, sentence-transformers — is Python-first. Splitting the AI layer into a Python sidecar behind a Node API adds a hop and a serialization boundary for no benefit. Pydantic doubling as your agent contract *and* your HTTP schema *and* your generated TS types is a genuine architectural win.

**Why Cloud Run over Fly.io/Railway/Render:** persistent processes with real WebSocket/SSE support, scale-to-zero on the free-ish tier, and simple private networking between API, worker, LiteLLM, and MCP. Render's free tier cold-starts painfully; Railway's free tier has gotten thin. Fly's failure mode — occasional regional weirdness — is one you can absorb.

**Why not serverless for the brain:** agent runs last 5–20 seconds with parallel fan-out, plus you want a warm process for the reranker model and connection pooling. Serverless makes both worse.

**Concurrency:** async everywhere; `asyncio.gather` for council fan-out and parallel retrieval; a semaphore per provider to respect rate limits; `httpx` with explicit timeouts on every external call (no default-infinite timeouts, ever).

---

## 6. Security model

| Layer | Control |
|---|---|
| **AuthN** | Supabase Auth. Residents: magic link + optional passkey (no passwords for a demographic that will not manage them). Staff: email+password with mandatory TOTP. Vendors: **no account** — signed, short-TTL, single-purpose links. |
| **AuthZ** | RBAC (`owner/manager/staff/tech/resident/vendor`) × scope (`org/property/building/unit`), enforced in an API dependency *and* RLS. |
| **Tenancy** | `org_id` on every row; JWT claim; RLS; plus a CI test that asserts cross-tenant reads fail for every endpoint. |
| **Secrets** | Fly secrets / Vercel env. Zero secrets in repo; `gitleaks` in pre-commit and CI. |
| **PII** | Redaction before any prompt build; media in a private bucket with signed URLs (5 min); audio deleted after transcription; transcripts retained per policy. |
| **Data retention** | Tickets 7y (statute-driven), media 2y, raw prompts 90d then digest-only, audit records 7y. Configurable per org. |
| **Injection** | Trust-labeled context, untrusted content never reaches write-capable agents, scanner as second line. |
| **Tool authorization** | Server-side grant map + single-use approval tokens scoped to (ticket, action). |
| **Transport** | HTTPS everywhere, HSTS, strict CSP, signed webhooks (HMAC + timestamp + replay window). |
| **Vendor links** | HMAC-signed, TTL 48h, single action, rate-limited, no PII in the URL. |
| **Audit** | Append-only + hash chain; separate read path for auditors. |
| **Model providers** | Zero-retention API settings where offered; document what leaves the boundary in `docs/DATA_FLOW.md`. Local Ollama path for orgs that refuse third-party inference. |

**Threat model, top three:**
1. *Cross-tenant leakage* — highest severity, most likely (a single unscoped query). Mitigation: RLS + explicit scoping + automated cross-tenant tests in CI.
2. *Indirect prompt injection via vendor/document content* — mitigated architecturally by P3, not just by scanning.
3. *Discriminatory output at scale* — mitigated by output guardrails + CI red-team parity suite + immutable message log.

---

## 7. Authentication flow

```
Resident: magic link → Supabase session (JWT: sub, org_id, person_id, role, scopes)
          → Next Route Handler validates + forwards with a short-lived service token
          → FastAPI verifies signature, hydrates tenancy, applies RLS context
          → refresh rotation; 30d for residents, 12h for staff

Staff:    email+password + TOTP → same, shorter TTL, IP + device logging

Vendor:   no session. HMAC-signed URL: {work_order_id, action, exp, nonce}
          → single-use nonce in Redis → 200 or 410 Gone

Service:  worker ↔ API via mTLS on the Fly private network + service JWT
```

---

## 8. Observability

**Stack: Langfuse (self-hosted, LLM traces + prompt versions + costs) + Arize Phoenix (retrieval debugging, embedding drift) + OpenTelemetry → both.** Everything instruments via OTEL so no vendor is load-bearing.

| Tool | Role | Why chosen |
|---|---|---|
| **Langfuse** | Primary LLM observability, prompt management, cost tracking, dataset/eval linkage | Self-hostable free, OTEL-native, not coupled to LangChain |
| **Phoenix** | Retrieval and embedding debugging; its embedding projection makes retrieval drift *visible* rather than inferable from metrics | Free, open source, best-in-class for the specific problem of "why did retrieval get worse" |
| LangSmith | Considered | Best-in-class if you're all-in on LangChain, but per-seat pricing and coupling; you'd rather demonstrate OTEL portability |
| Helicone | Considered | Proxy-based, simple, but you already have LiteLLM at that layer |
| Braintrust | Considered | Excellent eval-first platform; cost profile doesn't fit bootstrapped |

**Trace shape — one trace per ticket, spans nested:**

```
trace: ticket_4471 (org, property, unit, workflow_version)
├── span guardrails.input        (pii=2 redacted, injection=clean)
├── span agent.safety_intake     └── llm.call (haiku, prompt=intake@v4, hash=a91f…)
├── span context.broker
│   ├── span retrieval.hybrid    (bm25 top10, vec top10, rrf, rerank 30→6)
│   ├── span memory.episodic     (k=3)
│   └── span context.budget      (utilization by slot)
├── span council                 (triggered=true, score=0.62)
│   ├── span member.policy   ─┐
│   ├── span member.history   ├ parallel
│   └── span member.cost     ─┘
│   └── span council.synthesis
├── span agent.dispatch_planner
├── span guardrails.policy_audit
├── span decision.gate           (mode=approval_required, confidence=0.79)
├── span agent.communicator
├── span guardrails.output       (fair_housing=pass, pii=pass, citations=6/6)
└── span judge (async)
```

**Alerts that matter** (everything else is noise): P0 detection recall drop on the shadow set · groundedness 24h rolling below threshold · escalation rate ±50% week-over-week (either direction — a *drop* means the system got overconfident) · cost/ticket > 2× baseline · any fair-housing guardrail block reaching a human · queue depth p95 · provider fallback rate.

---

## 9. Evaluation framework

### 9.1 The four layers

| Layer | What | Tool | Runs | Gates? |
|---|---|---|---|---|
| **Unit** | Each agent against fixtures; each guardrail as a pure function | pytest | every commit | Yes |
| **Component** | Retrieval quality (recall@k, MRR, nDCG); classifier metrics | Ragas + custom | every commit | Yes |
| **End-to-end** | 200-item golden set → full workflow → all MVP metrics | DeepEval + custom | every PR + nightly | **Yes** |
| **Adversarial** | Fair-housing parity probes, injection corpus, PII leak, jailbreak | Promptfoo | every PR | **Yes, hard fail** |

### 9.2 The golden set — the most important asset you will build

**200 tickets. Human-labeled by you. Synthetic but realistic.**

Composition — deliberately skewed toward the hard cases, because uniform sampling wastes labeling effort on tickets any system handles:

| Slice | n | Why |
|---|---|---|
| Routine unambiguous | 40 | Baseline; catches regressions in the easy path |
| Ambiguous priority | 35 | Where the value is |
| Chargeback-disputable (wear vs damage) | 30 | Money + relations |
| Life-safety (true positives) | 20 | Recall is the metric |
| Life-safety near-misses (false-positive bait) | 20 | "Smells like gas" vs "smells like garbage" |
| Recurring/reopened | 20 | Tests episodic memory |
| Multilingual / low-literacy / voice transcript | 15 | Real residents |
| Adversarial / injection / off-topic | 10 | Robustness |
| Missing-information (correct answer = ask) | 10 | Tests abstention |

Each item: input, expected priority, expected party, expected trade, must-cite document IDs, and `acceptable_alternatives` — because several of these genuinely have two defensible answers, and an eval that punishes a correct-but-different answer will drive you to overfit.

**Label them yourself, in one sitting, before writing the prompts.** Labeling after tuning is how you unconsciously encode your model's behavior as ground truth.

### 9.3 CI eval gate

```yaml
# .github/workflows/evals.yml (sketch)
- run: python evals/run.py --suite golden_v1 --judge claude-sonnet-<pinned> --seed 42
- run: python evals/run.py --suite redteam_fh --fail-on-any-violation
- run: python evals/gate.py --baseline main --tolerance-bands evals/bands.yaml
```

`bands.yaml` uses **tolerance bands, not exact thresholds**, and a stable seeded sample — otherwise LLM nondeterminism makes CI flaky and you'll start ignoring it, which is worse than not having it:

```yaml
p0_recall:            {min: 0.98, regression_tolerance: 0.00}   # never regress
priority_macro_f1:    {min: 0.82, regression_tolerance: 0.02}
groundedness:         {min: 0.93, regression_tolerance: 0.02}
chargeback_accuracy:  {min: 0.88, regression_tolerance: 0.03}
escalation_precision: {min: 0.55, regression_tolerance: 0.05}
fair_housing:         {max_violations: 0}
cost_per_ticket_usd:  {max: 0.05}
p95_latency_ms:       {max: 22000}
```

**Pin the judge model and seed.** Swapping judges mid-history invalidates every prior number; treat a judge upgrade as a migration with a full re-baseline, and record the judge version in `eval_runs`.

### 9.4 Metrics catalogue

*Retrieval:* recall@5/10, MRR, nDCG@10, rerank lift, retrieval-miss rate, citation coverage.
*Generation:* groundedness (deterministic + judged), citation precision, schema-first-pass rate, hallucinated-figure rate.
*Decision:* priority macro-F1, party accuracy, trade accuracy, P0 recall/precision, abstention precision/recall, **calibration error (ECE)** and the reliability diagram.
*Agent:* per-agent success, p50/p95 latency, tool failure, retry, loop breaks.
*Coordination:* council trigger rate, member agreement, dissent rate, council lift over solo (**measure this — if council doesn't beat solo on the golden set, cut it**), degraded-council rate.
*Workflow:* completion rate, time-to-decision, human-override rate + reason distribution, reopen rate.
*Economics:* cost/ticket, cache hit rate, token/decision, cost/resolved-ticket.

That "measure council lift, and cut it if it's zero" line is the single most senior sentence you can say about this architecture. Say it before someone asks.

---

## 10. Infrastructure & deployment

```
              ┌─────────────────────────────────────────────┐
   Users ────▶│  Vercel  ·  Next.js  ·  Edge CDN  ·  Free   │
              └──────────────────┬──────────────────────────┘
                                 │ HTTPS, JWT
              ┌──────────────────▼──────────────────────────┐
              │  Cloud Run (internal ingress between svcs)  │
              │  ┌────────┐ ┌────────┐ ┌────────┐ ┌───────┐ │
              │  │  api   │ │ worker │ │litellm │ │  mcp  │ │
              │  │ 2×256M │ │ 1×512M │ │ 1×256M │ │1×256M │ │
              │  └────────┘ └────────┘ └────────┘ └───────┘ │
              │  ┌──────────────────────────────┐           │
              │  │ langfuse + phoenix (1×1GB)   │           │
              │  └──────────────────────────────┘           │
              └──────────────────┬──────────────────────────┘
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              Supabase      Upstash        Cloudflare R2
              Postgres      Redis          media (10GB free)
              +pgvector     free tier
              +Auth+Storage
```

### 10.1 Free-tier stack and where it breaks

| Component | Service | Free limit | Breaks at | Escape |
|---|---|---|---|---|
| Frontend | Vercel Hobby | 100GB bandwidth | ~50k demo visits | Pro $20 |
| API/worker | Cloud Run | monthly request + CPU allowance | sustained traffic | pay-per-use; ~$5-8/mo for one warm instance |
| DB | Supabase Free | 500MB, **pauses after 7 days idle** | ~150k tickets, or one quiet week | **Pro $25 — do this before any demo you care about** |
| Cache/queue | Upstash | 10k commands/day | ~1k tickets/day | Pay-as-you-go, cents |
| Media | R2 | 10GB + free egress | thousands of photos | $0.015/GB |
| Observability | Self-hosted Langfuse/Phoenix | RAM-bound | high volume | $0 longer than you'd think |
| CI | GH Actions | 2,000 min/mo | evals are minute-hungry | Cache aggressively; nightly full, PR subset |
| Inference | — | none | — | ~$73/property/yr (file 02 §12) |

**Total realistic: $0–25/month.** The one line I'd pay immediately is Supabase Pro. A paused database when a recruiter opens your link is an unforced error that costs more than $25.

### 10.2 Environments

`local` (docker-compose: postgres+pgvector, redis, litellm, langfuse, ollama — full stack offline, so bringing the project up on a new machine is a one-command operation) → `preview` (per-PR Vercel + shared staging API + seeded DB branch) → `production`.

**Demo mode** deserves its own flag: `DEMO_MODE=true` seeds a synthetic property, disables all outbound channels (a demo that texts a real phone number is a career-limiting bug), and pins model temperature and seeds so the demo behaves the same at 9am and at midnight.

### 10.3 CI/CD

```
push ──▶ lint (ruff, eslint) ──▶ types (mypy strict on brain/, tsc) ──▶ unit tests
     ──▶ integration (ephemeral postgres, seeded)
     ──▶ EVAL GATE  (golden subset + full red-team)          ← blocks merge
     ──▶ preview deploy (Vercel + Fly preview app)
     ──▶ main: migrations (expand/contract) ──▶ canary 10% ──▶ full
     ──▶ post-deploy: smoke + nightly full eval + auto-rollback on breach
```

- **Prompts are code.** Versioned files, content-hashed at load, hash recorded on every call. Changing a prompt is a PR that runs evals. This is the practice that separates people who've shipped LLM systems from people who've built demos, and it's worth one sentence in your README.
- **Migrations expand/contract:** add nullable → backfill → switch reads → drop later. Never a blocking ALTER on a hot table.
- **Auto-rollback:** nightly eval breach or online groundedness drop → revert the prompt version pointer (a config flip, not a redeploy) and alert.

---

## 11. Reliability strategy

**Targets (self-imposed SLOs, published in the README):**

| SLO | Target |
|---|---|
| Ticket acknowledgment | 99.9% < 1s |
| Triage decision available | 99% < 30s |
| P0 detection → human paged | 99.9% < 60s |
| Workflow completion without unhandled error | ≥ 99.5% |
| Zero cross-tenant data exposure | 100% |

**Patterns:** timeouts on every external call · exponential backoff with jitter, capped at 2 retries · circuit breakers per provider (open after 5 failures/30s, half-open after 60s) · bulkheads (council fan-out can't starve intake — separate semaphores) · **graceful degradation ladder**: full → no-council → no-LLM-diagnosis → rules-only → queue-and-acknowledge. The building never stops working because a model provider does.

**Idempotency everywhere a real-world action can occur.** The dedupe key for notifications and the idempotency key on work orders are not nice-to-haves; in a retrying agent system they're the difference between a product and a nuisance.

---

## 12. Scaling: 100 → 1,000,000

| Stage | Users / scale | What breaks first | Fix |
|---|---|---|---|
| **100** (1 property, 400 units) | ~5 tickets/day | Nothing | Current stack, free tiers |
| **1k** (5 properties) | ~50/day | Supabase free storage; CI minutes | Supabase Pro; PR-subset evals |
| **10k** (50 properties) | ~500/day | Postgres connections from async workers; embedding backlog | **pgbouncer/Supavisor transaction pooling**; batch embeddings via Batch API (50% off); split read replica for dashboards |
| **100k** (500 properties, ~200k units) | ~5k/day, ~1.8M tickets/yr | HNSW index memory; single Postgres write throughput; queue depth | Partition `kb_chunks` and `episodic_memory` by `org_id`; `halfvec` (already) then binary quantization for episodic; move queue to a real broker; separate OLAP (ClickHouse/Timescale) for `llm_calls` rollups; per-org connection budgets |
| **1M** (multi-region operators) | ~50k/day | Postgres as a single write node; cross-region latency; eval cost; cost attribution | Shard by `org_id` (tenancy makes this clean — no cross-org joins exist by design); regional API + regional inference endpoints; move to a durable workflow engine (Temporal) once runs need multi-day suspension; sample online judging to 1%; per-tenant inference budgets with hard caps |

**What does *not* need to change:** the agent contracts, the guardrail functions, the eval harness, the decision record. That's the payoff for the P2 decomposition — scaling touches infrastructure, not the reasoning layer.

**Two things that bite earlier than people expect:** (1) **HNSW index memory** — if the index doesn't fit in RAM, Postgres falls back to slow scans and your p95 collapses overnight with no code change; watch it before it happens. (2) **Eval cost at scale** — running full LLM-judged evals on every PR gets expensive fast; sample on PRs, full run nightly.
