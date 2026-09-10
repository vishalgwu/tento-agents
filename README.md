# Resident OS

Resident OS is an AI operations layer for apartment communities. It begins with one measurable workflow: maintenance. A resident report becomes a safe, cited, policy-checked, human-reviewable dispatch decision with an immutable audit trail.

The repository is intentionally documentation-first while the production system is rebuilt from scratch. It does not contain stale scaffolding, duplicated plans, or demo-only implementation folders.

## Start here

Read the three canonical documents in order:

1. [Product requirements](docs/PRODUCT.md) - scope, users, requirements, experience, success targets, and release gate.
2. [Technical architecture](docs/TECHNICAL-ARCHITECTURE.md) - invariants, agents, data, security, evaluation, operations, and production topology.
3. [Delivery plan](docs/DELIVERY-PLAN.md) - the phased build sequence from contracts to production launch.

For a compact, printable version, see [Resident OS Production Blueprint](docs/Resident-OS-Production-Blueprint.pdf).

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

Planning and contract-freeze stage. Follow `docs/DELIVERY-PLAN.md` Phase 0 before creating application code. All metrics in the documentation are targets until an evaluation run publishes reproducible results with a commit SHA.

## License

See [LICENSE](LICENSE).
