# Resident OS

Resident OS is an AI operations layer for apartment communities. It begins with one measurable workflow: maintenance. A resident report becomes a safe, cited, policy-checked, human-reviewable dispatch decision with an immutable audit trail.

The repository is intentionally documentation-first while the production system is rebuilt from scratch. The implemented foundation stays tightly scoped to accepted contracts; it does not include stale plans or a pretend end-to-end demo.

## Start here

Read the three canonical documents in order:

1. [Product requirements](docs/PRODUCT.md) - scope, users, requirements, experience, success targets, and release gate.
2. [Technical architecture](docs/TECHNICAL-ARCHITECTURE.md) - invariants, agents, data, security, evaluation, operations, and production topology.
3. [Delivery plan](docs/DELIVERY-PLAN.md) - the phased build sequence from contracts to production launch.

The three PDFs and architecture posters in `docs/` are archived planning
snapshots, retained for visual context only. They are not implementation
authority and are not kept in lockstep with the canonical Markdown documents;
in particular, use the current Markdown rather than their older fixture counts
or phase checkpoints.

## The product in one paragraph

Property-management systems record work but rarely decide what should happen next. Resident OS sits alongside them and runs the Maintenance Loop: it acknowledges a report immediately, detects life-safety risk deterministically, assembles versioned evidence, proposes a decision, checks the decision against policy, obtains the required human approval, and records the complete receipt. The goal is not a more talkative bot. It is safer, explainable apartment operations.

## Core principles

- The model proposes; deterministic code validates and authorises.
- Every consequential decision is grounded in versioned evidence.
- Only the orchestrator holds side-effecting tool authority.
- A model never decides whether or when to notify a person.
- Tenant isolation, append-only audit records, and calibrated abstention are product features.
- Measured evaluation results matter more than unverified claims.

## Canonical scope

The measured MVP is maintenance only: intake, life-safety screening, retrieval, decision proposal, policy audit, approval, dispatch proposal, trace, and evaluation. Community features, wellness, autonomous action, and payments are explicitly deferred until the maintenance loop is safe and measured.

## Planned production topology

Next.js on Vercel serves the resident, manager, owner, technician, vendor, and operations surfaces. A FastAPI API, orchestration, and workers run on Cloud Run. Supabase Postgres with pgvector provides tenant-isolated data and retrieval; Redis and object storage support queues, caching, and media. Narrow internal tools connect approved actions to property-management, vendor, and notification systems.

## Project status

The repository currently contains a local, non-production foundation: the
tenant-scoped schema and RLS migrations, deterministic synthetic seed, and a
FastAPI reliability boundary (request correlation, JWT verification, RLS context,
rate limiting, idempotency, safe errors, readiness), and the initial
tenant-scoped ticket read contract. [`docs/openapi.yaml`](docs/openapi.yaml)
defines `GET /v1/tickets` and `GET /v1/tickets/{id}`; their database queries use
keyset pagination and an explicit organisation predicate in addition to RLS. The
repository also includes the Next.js 15 role-surface foundation (`/app`,
`/manage`, `/owner`, `/tech`, and `/v/[token]`), generated TypeScript OpenAPI
types, and the shared evidence/decision visual primitives. It intentionally has
no connected authentication provider, API mutation, live ticket data, or outbound
email/notification transport. Vendor links fail closed unless their server-side
HMAC secret is configured. The remaining OpenAPI and SSE contracts, public
mutations, and agent workflow remain deliberately pending; do not treat the
foundation as an MVP release. All metrics in the documentation are targets until
an evaluation run publishes reproducible results with a commit SHA.

The eleven files under [`knowledge/`](knowledge/README.md) are temporary,
evaluation-only fixtures. They exercise metadata, source precedence, citations,
and safe abstention; they are neither approved operating policy nor eligible for
a production retrieval index. Their named replacement owners and promotion
checklist are maintained in the knowledge register.

The Phase-2 retrieval foundation validates and versions those sources, chunks and
embeds them, and supplies a read-only hybrid BM25/pgvector candidate layer. It
fuses 30 lexical and 30 dense candidates before applying lifecycle, jurisdiction,
authority, model, and ticket-time effective-date checks. It is not connected to a
production index, API route, model workflow, or operational action.

## Web workspace

The web foundation is a pnpm workspace. It is designed to make the intended
access boundaries clear without simulating an integration that does not exist.

```powershell
pnpm install
pnpm generate:api
pnpm typecheck:web
pnpm build:web
pnpm dev:web
```

`packages/shared-types/src/api.generated.ts` is generated from
[`docs/openapi.yaml`](docs/openapi.yaml); regenerate it instead of editing it.
See [the web README](apps/web/README.md),
[the shared-types README](packages/shared-types/README.md), and
[the UI README](packages/ui/README.md) for the route, security, and component
contracts.

## License

See [LICENSE](LICENSE).
